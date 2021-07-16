Build the docker

    docker build . -t app


Run in docker

    docker run -d --name app app

Running locally

    USE_K8S_CONFIG_FILE=true python app.py

To use local config values, instead of consul, just export the config, for example `export JOB_WATCH_PATH=/mypath`

## Run tests

    python -m pytest

## Dependencies

    pip install --upgrade pip
    pip install --upgrade pygogo python-consul kubernetes prometheus-client
    pip freeze > requirements.txt
    sed -i '/pkg_resources/d' requirements.txt
