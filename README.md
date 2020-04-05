Build the docker

    docker build . -t app


Run in docker

    docker run -d --name app app

Running locally

    USE_K8S_CONFIG_FILE=true python app.py

To use local config values, instead of consul, just export the config, for example `export JOB_WATCH_PATH=/mypath`


@TODO

 - periodically run something like `kubectl delete pod --field-selector=status.phase=Succeeded` to get rid of completed pods from the list
 - make job creation failures and file moves atomic: move the file back if the create_job call fails
 