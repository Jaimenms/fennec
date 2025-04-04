# Fennec

![Logo](docs/imgs/logo-small.png)

This project aims to develop an optimizer that allows the best usage stationary storage and electrical vehicles
in a single house, a business fleet or distributed assets.

For more information about the services, please refer to the documentation [here](./src/sel_ev_sdk/README.md).

![Test coverage](docs/imgs/coverage.svg)


# Using the package in your project

## Local installation using pip

### Specifying the extra-index-url as an argument in pip

Run the following command:

```bash
pip install fennec==0.1.0a.dev0
```

## Package organization

The Fennec package contains several different components organized according to the following tree:

```
├──docs/ : docs folder
├──notebooks/ : Jupyter notebooks studies
├──src/
│   ├── fennec/ : this is the main package folder
│   │   ├── blocks : blocks package
│   │   ├── examples : examples package
│   │   ├── models : models package
│   │   ├── tariffs : utils package
│   │   ├── utils : utils package
│   │   ├── __init__.py : a client
│   │   ├── fennec.py : main package
│   │   ├── README.md : package readme
│   │   └── (...)
│   └───requirements.txt
├──tests/
│   ├── integration/ : integration tests
│   └── unit/ : unit tests
├── .coveragerc : converage tests configuration
├── .gitignore : gitignore
├── poetry.lock
├── poetry.toml
├── pyproject.toml
└── README.md : repo readme
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

### Running jupyter notebook

```bash
poetry run jupyter notebook
```

## Building and publishing the package

1. Build the package

```bash
poetry build
```

2. Change the version of the package

Open pyproject.toml and change the "version" field.

Update the file CHANGELOG.md.

3. Publish the package

```bash
poetry publish
```
