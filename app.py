from kubernetes import client, config
import os
import consul
import time
import shutil

CONFIG_PATH = "handbrake-job-creator"


def main():
    if os.environ.get('USE_K8S_CONFIG_FILE'):
        config.load_kube_config()
    else:
        config.load_incluster_config()

    directory = get_watch_path()
    move_path = get_move_path()
    namespace = get_namespace()
    encoding_profile = get_encoding_profile()
    while True:
        for filename in os.listdir(directory):
            full_path = os.path.join(directory, filename)
            file_size = get_file_size(full_path)
            print("Found '{}' and it's size is {}".format(filename, file_size))
            time.sleep(10)
            # loop until the file size stops growing
            while file_size != get_file_size(full_path):
                file_size = get_file_size(full_path)
                time.sleep(10)
            print("moving '{}' to '{}/{}'".format(full_path, move_path, filename))
            shutil.move(full_path, "{}/{}".format(move_path, filename))
            file, extension = os.path.splitext(filename)
            job_suffix = file.replace(" ", "").lower()
            output_filename = filename
            if "1080p" in filename:
                output_filename = filename.replace('1080p', '720p')
            job = create_job_object(job_suffix, filename, output_filename, encoding_profile)
            batch_v1 = client.BatchV1Api()
            create_job(batch_v1, job, namespace)
        time.sleep(10)


def get_file_size(file):
    return os.stat(file).st_size


def get_container_version():
    return get_config("JOB_CONTAINER_VERSION")


def get_watch_path():
    return get_config("JOB_WATCH_PATH")


def get_move_path():
    return get_config("JOB_MOVE_PATH")


def get_output_path():
    return get_config("JOB_OUTPUT_PATH")


def get_namespace():
    return get_config("JOB_NAMESPACE")  # expected as an env value only


def get_encoding_profile():
    return get_config("JOB_PROFILE")  # expected as an env value only


def get_quality_level():
    quality = get_config("QUALITY")  # expected as an env value only
    if quality not in ['720p', '1080p']:
        raise LookupError("Unexpected quality level value")
    return quality


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
        command=["{}".format(input_filename), "{}".format(output_filename), "{}".format(encoding_profile)],
        volume_mounts=[
            client.V1VolumeMount(
                mount_path="/input",
                name="input"
            ),
            client.V1VolumeMount(
                mount_path="/output",
                name="output"
            )]
    )
    watch_volume = client.V1Volume(
        name="input",
        host_path=client.V1HostPathVolumeSource(
            path=get_move_path()
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
        metadata=client.V1ObjectMeta(labels={"app": "handbrake-job"}),
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
    print("Job created. status='%s'" % str(api_response.status))


if __name__ == '__main__':
    main()
