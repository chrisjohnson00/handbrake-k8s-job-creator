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
    encoding_profile = get_encoding_profile()
    file_discovered_metrics = Gauge('handbrake_job_creator_files_in_process', 'Job Creator Found A File')
    while True:
        for filename in os.listdir(directory):
            full_path = os.path.join(directory, filename)
            file_size = get_file_size(full_path)
            print(
                "INFO: {} - Found '{}' and it's size is {}".format(datetime.now().strftime("%b %d %H:%M:%S"), filename,
                                                                   file_size),
                flush=True)
            file_discovered_metrics.inc()
            time.sleep(10)
            # loop until the file size stops growing
            while file_size != get_file_size(full_path):
                print(
                    "INFO: {} - File is still growing, waiting".format(datetime.now().strftime("%b %d %H:%M:%S")),
                    flush=True)
                file_size = get_file_size(full_path)
                time.sleep(10)
            print(
                "INFO: {} - Moving '{}' to '{}/{}'".format(datetime.now().strftime("%b %d %H:%M:%S"), full_path,
                                                           move_path,
                                                           filename),
                flush=True)
            shutil.move(full_path, "{}/{}".format(move_path, filename))
            file, extension = os.path.splitext(filename)
            job_suffix = cleanup_job_suffix(file)
            output_filename = filename
            # @TODO make this configurable - if the 1080p job creator runs and i just want to re-encode a 1080p file
            #  (with 1080p in the name), it will rename it to 720p
            if "1080p" in filename:
                output_filename = filename.replace('1080p', '720p')
            # truncate the job suffix to 48 characters to not exceed the 63 character limit
            job = create_job_object(job_suffix[:48], filename, output_filename, encoding_profile)
            batch_v1 = client.BatchV1Api()
            create_job(batch_v1, job, namespace)
            # @TODO move the file back if the create_job call fails
            print("INFO: Done with {}".format(filename), flush=True)
            file_discovered_metrics.dec()
        time.sleep(10)


def get_file_size(file):
    return os.stat(file).st_size


def get_container_version():
    return get_config("JOB_CONTAINER_VERSION")


def get_watch_path():
    return get_config("WATCH_PATH")


def get_move_path():
    return get_config("MOVE_PATH")


def get_output_path():
    return get_config("JOB_OUTPUT_PATH")


def get_input_path():
    return get_config("JOB_INPUT_PATH")


def get_job_type():
    return get_config("JOB_TYPE")


def get_namespace():
    return get_config("JOB_NAMESPACE")  # expected as an env value only


def get_encoding_profile():
    return get_config("JOB_PROFILE")  # expected as an env value only


def get_quality_level():
    quality = get_config("QUALITY")  # expected as an env value only
    if quality not in ['720p', '1080p']:
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


def get_config(key, config_path=CONFIG_PATH):
    if os.environ.get(key):
        return os.environ.get(key)
    c = consul.Consul()
    index, data = c.kv.get("{}/{}".format(config_path, key))
    return data['Value'].decode("utf-8")


def create_job_object(name_suffix, input_filename, output_filename, encoding_profile):
    # Configureate Pod template container
    job_name = "handbrake-job-{}".format(name_suffix)
    container = client.V1Container(
        name=job_name,
        image="chrisjohnson00/handbrakecli:{}".format(get_container_version()),
        image_pull_policy=get_job_container_pull_policy(),
        command=["./wrapper.sh", "{}".format(input_filename), "{}".format(output_filename),
                 "{}".format(encoding_profile)],
        volume_mounts=[
            client.V1VolumeMount(
                mount_path="/input",
                name="input"
            ),
            client.V1VolumeMount(
                mount_path="/output",
                name="output"
            )],
        resources=client.V1ResourceRequirements(
            limits={'cpu': get_job_resource_limit_cpu(), 'memory': get_job_resource_limit_memory()},
            requests={'cpu': get_job_resource_request_cpu(), 'memory': get_job_resource_request_memory()}
        ),
        env=[
            client.V1EnvVar(
                name="JOB_TYPE",
                value=get_job_type()
            )
        ]
    )
    watch_volume = client.V1Volume(
        name="input",
        host_path=client.V1HostPathVolumeSource(
            path=get_input_path()
        )
    )
    move_volume = client.V1Volume(
        name="output",
        host_path=client.V1HostPathVolumeSource(
            path=get_output_path()
        )
    )
    # Create and configurate a spec section
    template = client.V1PodTemplateSpec(
        metadata=client.V1ObjectMeta(labels={"app": "handbrake-job"}, annotations={"prometheus.io/scrape": "true",
                                                                                   "prometheus.io/path": "/metrics",
                                                                                   "prometheus.io/port": "8080"}),
        spec=client.V1PodSpec(restart_policy="Never", containers=[container], volumes=[watch_volume, move_volume]))
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
    api_response = api_instance.create_namespaced_job(
        body=job,
        namespace=namespace)
    print("INFO: {} - Job created. status='{}'".format(datetime.now().strftime("%b %d %H:%M:%S"),
                                                       str(api_response.status)),
          flush=True)


if __name__ == '__main__':
    main()
