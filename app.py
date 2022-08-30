from kubernetes import client, config
import os
import consul
import time
import shutil
from datetime import datetime
from app.utils import cleanup_job_suffix
from prometheus_client import Gauge, start_http_server

CONFIG_PATH = "handbrake-job-creator"


def main():
    print("INFO: Starting...", flush=True)
    start_http_server(8080)
    if os.environ.get('USE_K8S_CONFIG_FILE'):
        config.load_kube_config()
    else:
        config.load_incluster_config()

    directory = get_watch_path()
    move_path = get_move_path()
    namespace = get_namespace()
    sleep_time_seconds = get_sleep_time()
    file_discovered_metrics = Gauge('handbrake_job_creator_files_in_process', 'Job Creator Found A File',
                                    labelnames=["type", "quality"])
    files_to_process_metrics = Gauge('handbrake_job_creator_files_to_process', 'Job Creator Found Some Files',
                                     labelnames=["type", "quality"])
    job_creator_job_created = Gauge('handbrake_job_creator_job_created', 'Job Creator Created a Job',
                                    labelnames=["type", "quality", "filename"])
    while True:
        dir = os.listdir(directory)
        files_to_process_metrics.labels(get_job_type(), get_quality_level()).set(len(dir))
        for filename in dir:
            # do it again to ensure we get an accurate count of files as the directory grows from the other side
            refresh_dir = os.listdir(directory)
            files_to_process_metrics.labels(get_job_type(), get_quality_level()).set(len(refresh_dir))
            full_path = os.path.join(directory, filename)
            file_size = get_file_size(full_path)
            print(
                "INFO: {} - Found '{}' and it's size is {}".format(datetime.now().strftime("%b %d %H:%M:%S"), filename,
                                                                   file_size),
                flush=True)
            file_discovered_metrics.labels(get_job_type(), get_quality_level()).inc()
            time.sleep(sleep_time_seconds)
            # loop until the file size stops growing
            while file_size != get_file_size(full_path):
                print(
                    "INFO: {} - File is still growing, waiting".format(datetime.now().strftime("%b %d %H:%M:%S")),
                    flush=True)
                file_size = get_file_size(full_path)
                time.sleep(sleep_time_seconds)
            # now move the file into the "encoding queue"
            print(
                "INFO: {} - Moving '{}' to '{}/{}'".format(datetime.now().strftime("%b %d %H:%M:%S"), full_path,
                                                           move_path,
                                                           filename),
                flush=True)
            shutil.move(full_path, "{}/{}".format(move_path, filename))
            file, extension = os.path.splitext(filename)
            # create the encoding job
            batch_v1 = client.BatchV1Api()
            if job_exists(batch_v1, generate_job_name(file), namespace):
                print("INFO: Done with {} did not create any new job".format(filename), flush=True)
                # @TODO remove the file from encoding_queue!
            else:
                output_filename = filename
                #  (with 1080p in the name), it will rename it to 720p
                find_value = get_file_name_needle()
                replace_value = get_file_name_replace_value()
                if find_value and replace_value:
                    output_filename = filename.replace(find_value, replace_value)
                # 2.5x file size to account for copying into the container, encoding the file and other storage needs
                job = create_job_object(generate_job_name(file), filename, output_filename, (file_size * 2.5))
                create_job(batch_v1, job, namespace)
                # @TODO move the file back if the create_job call fails
                print("INFO: Done with {}".format(filename), flush=True)
            file_discovered_metrics.labels(get_job_type(), get_quality_level()).dec()
            job_creator_job_created.labels(get_job_type(), get_quality_level(), filename).set(1)
        time.sleep(sleep_time_seconds)


def get_file_size(file):
    return os.stat(file).st_size


def generate_job_name(filename):
    job_suffix = cleanup_job_suffix(filename)
    # truncate the job suffix to 48 characters to not exceed the 63 character limit
    return "handbrake-job-{}".format(job_suffix[:48])


def get_container_version():
    return get_config("JOB_CONTAINER_VERSION")


def get_watch_path():
    return get_config("WATCH_PATH")


def get_move_path():
    return get_config("MOVE_PATH")


def get_nfs_server():
    return get_config("NFS_SERVER_IP")


def get_output_path():
    return get_config("JOB_OUTPUT_PATH")


def get_input_path():
    return get_config("JOB_INPUT_PATH")


def get_job_type():
    return get_config("JOB_TYPE")


def get_file_name_needle():
    return get_config("FILE_NAME_REPLACE_NEEDLE")


def get_file_name_replace_value():
    return get_config("FILE_NAME_REPLACE_VALUE")


def get_namespace():
    return get_config("JOB_NAMESPACE")  # expected as an env value only


def get_quality_level():
    quality = get_config("QUALITY")  # expected as an env value only
    if quality not in ['720p', '1080p', '4k']:
        raise LookupError("Unexpected quality level value")
    return quality


def get_job_resource_request_cpu():
    return get_config("JOB_RESOURCE_REQUEST_CPU")


def get_job_resource_limit_cpu():
    return get_config("JOB_RESOURCE_LIMIT_CPU")


def get_job_resource_request_memory():
    return get_config("JOB_RESOURCE_REQUEST_MEMORY")


def get_job_resource_limit_memory():
    return get_config("JOB_RESOURCE_LIMIT_MEMORY")


def get_job_container_pull_policy():
    return get_config("JOB_CONTAINER_PULL_POLICY")


def get_sleep_time():
    if os.environ.get("SLEEP_TIME"):
        return int(os.environ.get("SLEEP_TIME"))
    return 10


def get_config(key, config_path=CONFIG_PATH):
    if os.environ.get(key):
        return os.environ.get(key)
    c = consul.Consul()
    index, data = c.kv.get("{}/{}".format(config_path, key))
    return data['Value'].decode("utf-8")


def create_job_object(job_name, input_filename, output_filename, ephemeral_file_size):
    # Configureate Pod template container
    container = client.V1Container(
        name=job_name,
        image="chrisjohnson00/handbrakecli:{}".format(get_container_version()),
        image_pull_policy=get_job_container_pull_policy(),
        command=["python3", "/wrapper.py", "{}".format(input_filename), "{}".format(output_filename)],
        volume_mounts=[
            client.V1VolumeMount(mount_path="/input", name="input"),
            client.V1VolumeMount(mount_path="/output", name="output"),
            client.V1VolumeMount(mount_path='/encode_in', name='encode-in'),
            client.V1VolumeMount(mount_path='/encode_out', name='encode-out')
        ],
        resources=client.V1ResourceRequirements(
            limits={'cpu': get_job_resource_limit_cpu(), 'memory': get_job_resource_limit_memory(),
                    'ephemeral-storage': ephemeral_file_size},
            requests={'cpu': get_job_resource_request_cpu(), 'memory': get_job_resource_request_memory(),
                      'ephemeral-storage': ephemeral_file_size}
        ),
        env=[
            client.V1EnvVar(
                name="JOB_TYPE",
                value=get_job_type()
            ),
            client.V1EnvVar(
                name="CONSUL_HTTP_ADDR",
                value=get_config('CONSUL_HTTP_ADDR')
            ),
            client.V1EnvVar(
                name="SCHEDULED_NODE",
                value_from=client.V1EnvVarSource(field_ref=client.V1ObjectFieldSelector(field_path="spec.nodeName"))
            )
        ]
    )
    watch_volume = client.V1Volume(
        name="input",
        nfs=client.V1NFSVolumeSource(
            path=get_input_path(),
            server=get_nfs_server()
        )
    )
    move_volume = client.V1Volume(
        name="output",
        nfs=client.V1NFSVolumeSource(
            path=get_output_path(),
            server=get_nfs_server()
        )
    )
    emptydir_volume_in = client.V1Volume(name="encode-in", empty_dir=client.V1EmptyDirVolumeSource())
    emptydir_volume_out = client.V1Volume(name="encode-out", empty_dir=client.V1EmptyDirVolumeSource())
    # Create and configurate a spec section
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(
            labels={"app": "handbrake-job", "job-type": get_job_type(), "job-quality": get_quality_level()},
            annotations={"prometheus.io/scrape": "true",
                         "prometheus.io/path": "/metrics",
                         "prometheus.io/port": "8080"}),
        spec=client.V1PodSpec(restart_policy="Never", containers=[container],
                              volumes=[watch_volume, move_volume, emptydir_volume_in, emptydir_volume_out]))
    # Create the specification of deployment
    spec = client.V1JobSpec(
        template=template)
    # Instantiate the job object
    job = client.V1Job(
        api_version="batch/v1",
        kind="Job",
        metadata=client.V1ObjectMeta(name=job_name),
        spec=spec)

    return job


def create_job(api_instance, job, namespace):
    api_instance.create_namespaced_job(
        body=job,
        namespace=namespace)
    print("INFO: {} - Job created.".format(datetime.now().strftime("%b %d %H:%M:%S")), flush=True)


def job_exists(api_instance, name, namespace):
    try:
        api_instance.read_namespaced_job(name, namespace)
    except client.rest.ApiException as e:
        print("ApiException encountered, got an HTTP status of: {}".format(e))
        return False
    return True


if __name__ == '__main__':
    main()
