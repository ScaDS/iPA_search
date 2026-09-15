# Intelligent Patient Record (iPA)

The Intelligent Patient Record is a tool for physicians to search in patient records.
iPA aims to mimick physicians' thinking patterns and enhance them using modern search technology.

At its core, the iPA search system is a backend with a RESTful API that performs query expansion and search in an OpenSearch index.

## Setup

1. Install the virtual environment:
    ```bash
    uv sync --project backend
    ```

2. Create a `.env` file in backend dir containing all needed environment variables.
    For reference, check out [the example file](./backend/.env-example).

    Hint: Manually set environment variables take precedence over those set in the `.env` file.

3. If you do not have a running Opensearch instance, you can launch one using

    ```bash
    docker compose -f backend/docker-compose.yml -f backend/docker-compose-medplum.yml up -d
    ```

4. Add patient records to your OpenSearch index.
    For testing purposes you can index the [GraSCCo](https://zenodo.org/records/6539131) dataset using the `index_files` api endpoint.
    An example for how to use this endpoint can be found in [ipa.http](./examples/api/ipa.http).
    Note that using the `index_files` endpoint requires a running iPA backend (see [Quick Start](./README.md#quick-start)).

## Quick Start

Run the iPA backend server:

```bash
uv run --project backend --env-file backend/.env fastapi dev --entrypoint ipa_backend.main:app
```

This repo comes with a makeshift frontend. Install its dependencies via

```bash
uv sync --project frontend
```

Launch it using

```bash
uv run --project frontend streamlit run frontend/streamlit_app.py --server.address localhost
```

## Approaches

Read more about the search approaches that are implemented [here](./docs/search_approaches.md).

## Development

### Installation

Install all dependencies incl. test dependencies:

```bash
uv sync --project backend --extra test
```

### Tests

Run integration tests via

```bash
uv run --project backend --env-file backend/.env pytest -v
```

### API

You find the iPA API documentation at http://localhost:8000/docs .

Note: The iPA backend server must running in order to show the documentation. (`uv run --project backend fastapi dev --entrypoint ipa_backend.main:app`)


### Contact

For questions you can contact Christian Martin: cmartin@uni-leipzig.de

