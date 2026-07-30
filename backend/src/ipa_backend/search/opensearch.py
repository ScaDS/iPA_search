from opensearchpy import OpenSearch
from opensearchpy import ConflictError, ConnectionError
import pathlib
import time
import hashlib
from loguru import logger
from fastapi import HTTPException, status


def raise_os_connection_error(client):
    try:
        os_host = client.transport.hosts[0]["os_host"]
        os_port = client.transport.hosts[0]["os_port"]
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Cannot connect to Opensearch instance at http://{os_host}:{os_port}\u200b. "
            "Did you start the Opensearch instance using docker-compose up?",
        )
    except KeyError:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Cannot connect to Opensearch instance. "
            "Did you start the Opensearch instance using docker-compose up?",
        )


def get_health(client: OpenSearch):
    try:
        health = client.cluster.health()
        return health
    except ConnectionError:
        raise_os_connection_error(client)


def create_index(client: OpenSearch, index_name: str):
    index_body = {
        "settings": {"index": {"number_of_shards": 1, "number_of_replicas": 0}},
        "mappings": {"properties": {"patient_id": {"type": "keyword"}}},
    }

    try:
        if not client.indices.exists(index=index_name):
            client.indices.create(index=index_name, body=index_body)
            logger.debug(f'Created index "{index_name}".')
        else:
            logger.debug(f'Index "{index_name}" is an existing index.')

    except ConnectionError:
        raise_os_connection_error(client)


def index_files(
    client: OpenSearch, path: pathlib.Path, index: str, patient_id: str
) -> dict:
    """Index .txt and .md files from a local folder (incl. subfolders)."""
    if not path.is_dir():
        raise ValueError(f"{path} is not a valid directory")

    # find all md and txt files in folder + subfolders
    file_types = [".txt", ".md"]
    file_paths = []
    for file_type in file_types:
        file_paths.extend(path.glob("**/*" + file_type))

    # remove README.md files from list
    file_paths = [file for file in file_paths if file.name != "README.md"]

    logger.info(
        f"Indexing {len(file_paths)} files from folder {path.resolve()} for patient_id={patient_id}"
    )

    create_index(client, index)

    indexed = []
    exists = []
    empty = []

    for txt_file in file_paths:
        # read files from disk
        try:
            with open(txt_file, "r", encoding="utf-8") as f:
                content = f.read()
                if content == "":
                    empty.append(txt_file.name)
                    logger.info(f"File {txt_file.name} is empty.")
                    continue

                sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()

            body = {
                "filename": txt_file.name,
                "content": content,
                "path": str(txt_file.resolve()),
                "timestamp": time.time(),
                "patient_id": patient_id,
            }
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Error processing {txt_file}: {str(e)}",
            )

        # index files in opensearch
        try:
            client.create(index=index, id=sha256, body=body)
            indexed.append(txt_file.name)
        except ConflictError:
            exists.append(txt_file.name)
        except ConnectionError:
            raise_os_connection_error(client)

    logger.info(
        f"Indexed {len(indexed)} files. {len(exists)} files existed already. {len(empty)} files are empty and therefore skipped"
    )
    result = {"indexed": len(indexed), "exist": len(exists), "empty": len(empty)}
    return result
