# Fennec

![Logo](docs/imgs/logo-small.png)

This project aims to develop a house energy management system.

For more information about the services, please refer to the documentation [here](./src/sel_ev_sdk/README.md).

![Test coverage](docs/imgs/coverage.svg)


# Using the package in your project

(SWARTIFACTS_APP_EMCPENERGYMANAGEMENTCLOUDPLATFORM_READER FS is required)

## Local installation using pip

### Specifying the extra-index-url as an argument in pip

Run the following command:

```bash
pip install fennec==0.1.0a.dev0
```

## Package organization

The Fennec package contains several different components.

The components and their organization are described below.

```
src/
├── fennec/ : this is the main package folder
│   ├── __init__.py : a client
│   └── fennec.py : to be defined
└───requirements.txt
```


## Preparing local environment

1. Install python 3.11

2. Install poetry

```bash
python -m pip install poetry==1.8.2
poetry self add poetry-dotenv-plugin
poetry self add poetry-plugin-export
```

3. Install a virtual environment manager using poetry

In the folder sel-pev-sdk, where the pyproject.toml file is, run:

```bash
poetry env use <path_to_python_3.12>
```

Example:

```bash
poetry env use C:\Python\Python312\python.exe
```

4. Activate the virtual environment

```bash
poetry shell
```

5. Adding new dependencies

Edit file pyproject.toml and insert the new dependency in the section "[tool.poetry.dependencies]".

Updating dependencies
```bash
poetry lock
```

6. Install the dependencies

Update the requirements.txt
```bash
poetry export --output src/requirements.txt
```

Installing the dependencies
```bash
poetry install
```

## Get the package ready

### Run All Tests

```bash
poetry run pytest
```

### Run Unit Tests

```bash
poetry run pytest tests/unit
```

### Reformat code

```bash
poetry run black src tests
```

### To update the coverage analysis

```bash
poetry run coverage run -m pytest tests/unit
poetry run python build_coverage.py
```

## Building and publishing the package

1. Build the package

```bash
poetry build
```

2. Connect to EDP Pypi private repository

(SWARTIFACTS_APP_EMCPENERGYMANAGEMENTCLOUDPLATFORM_PUBLISHER FS is required)

```bash
poetry config http-basic.private <username> <password>
```

where username is equal to the EDP E number and password is the EDM IAM password.

3. Change the version of the package

Open pyproject.toml and change the "version" field.

Update the file CHANGELOG.md.

4. Publish the package

```bash
poetry publish --repository private
```


## Building and publishing the layers

1. Update poetry.lock and requirements.txt

```bash
poetry lock
poetry export --output src/requirements.txt  --without-hashes --only main
```

2. Build the layer files for different python versions and architectures

```bash
python build_layers.py
```

3. Publish the layer files

```bash
python publish_layers.py --environment <environment_name> --profile_name <aws_profile_name> --region <aws_region>
```

em dev:

python publish_layers.py --environment dev --profile_name dev --region eu-west-1


