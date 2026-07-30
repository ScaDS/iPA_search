from pathlib import Path as PathlibPath
from fastapi import FastAPI, Query, Path, Request, HTTPException, status
from fastapi.exception_handlers import (
    http_exception_handler as default_http_exception_handler,
)
from fastapi.openapi.utils import get_openapi
from typing_extensions import Annotated
from opensearchpy import OpenSearch
from contextvars import ContextVar
import os
import uuid
from loguru import logger
import sys
import yaml

from ipa_backend.config import Common_Settings, LLM_Settings, FHIR_Settings
import ipa_backend.models
import ipa_backend.search.opensearch
import ipa_backend.search.approaches
import ipa_backend.search.fhir_search


settings = Common_Settings()


# use ContextVar for request_id → makes sure request_id is consistant during request (=context)
request_id_ctx_var: ContextVar[str] = ContextVar("request_id", default="-")

# format with request_id
LOG_FORMAT = (
    "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
    "<level>{level: <8}</level> | "
    "RID={extra[request_id]} | "
    "<level>{message}</level>"
)

# setup logger
os.makedirs("logs", exist_ok=True)
logger.remove()  # remove default stderr
logger.add(sys.stdout, format=LOG_FORMAT, level="WARNING")
logger.add("logs/ipa.log", format=LOG_FORMAT, level="INFO")

app = FastAPI()


# log exceptions
@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    request_id = request_id_ctx_var.get()
    with logger.contextualize(request_id=request_id):
        logger.error(f"HTTPException {exc.status_code}: {exc.detail}")
        # let default exception handler handle exceptions
        return await default_http_exception_handler(request, exc)


# log all api calls
@app.middleware("http")
async def add_request_id_logger(request: Request, call_next):
    request_id = str(uuid.uuid4())
    request_id_ctx_var.set(request_id)

    # bind request_id to logger
    with logger.contextualize(request_id=request_id):
        # before request is processed
        logger.info("Request started")

        logger.info("Request: {} {}", request.method, request.url)
        logger.info("Headers: {}", dict(request.headers))

        try:
            response = await call_next(request)
        # after request is processed
        except Exception as e:
            logger.exception("Unhandled exception")
            raise e
        else:
            logger.info("Response status: {}", response.status_code)

    return response


# set up OpenSearch Client
os_host = settings.opensearch_host
os_port = settings.opensearch_port
# create OpenSearch client with SSL/TLS and hostname verification disabled.
# for local use only!
opensearch_client = OpenSearch(
    hosts=[{"host": os_host, "port": os_port}],
    http_compress=True,  # enables gzip compression for request bodies
    use_ssl=False,
    verify_certs=False,
    ssl_assert_hostname=False,
    ssl_show_warn=False,
)


@app.get("/{store}/checkhealth")
def get_opensearch_health():
    """Check Opensearch health status."""

    return ipa_backend.search.opensearch.get_health(opensearch_client)


@app.put("/{store}/index_files/{index}")
def index_files(
    path: Annotated[
        PathlibPath,
        Query(
            description="Path on local disk to folder containing files to be indexed."
        ),
    ],
    index: Annotated[str, Path(description="OpenSearch index name.")],
    store: ipa_backend.models.Store,
    patient_id: Annotated[
        str | None, Query(description="Patient ID. Required for plain store.")
    ] = None,
):
    """Index files from a local folder in OpenSearch.
    This is a dev stub. In prod another component will index docs in OpenSearch.
    This setup only works when request is sent from the same machine the API server is running on."""

    if store == "plain":
        if not patient_id:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="patient_id is required for plain store indexing.",
            )
        return ipa_backend.search.opensearch.index_files(
            opensearch_client, path=path, index=index, patient_id=patient_id
        )
    elif store == "fhir":
        fhir_settings = FHIR_Settings()

        ipa_backend.search.fhir_search.test_fhir_connection(fhir_settings)
        bundles = ipa_backend.search.fhir_search.load_fhir_bundles(path)

        if not bundles:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No FHIR bundles found in folder.",
            )

        return ipa_backend.search.fhir_search.upload_bundles_to_fhir(
            bundles=bundles,
            fhir_settings=fhir_settings,
        )


@app.get("/{store}/search")
def get_search_methods(
    store: ipa_backend.models.Store,
) -> list[str]:
    return ipa_backend.models.SearchMethod._member_names_


@app.post("/{store}/search/{index}/{patient_id}")
async def search_ehr(
    index: Annotated[str, Path(description="OpenSearch index name.")],
    patient_id: Annotated[str, Path(description="FHIR Patient ID.")],
    search: ipa_backend.models.Search,
    store: ipa_backend.models.Store,
    llm: LLM_Settings | None = None,
) -> ipa_backend.models.SearchResult:
    """Search all indexed documents."""

    if store == "fhir" and not patient_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="FHIR search requires a patient_id.",
        )

    if search.method == "lexical":
        if store == "plain":
            results = ipa_backend.search.approaches.BM25(
                search_client=opensearch_client,
                index=index,
                query=search.query,
                patient_id=patient_id,
            )
        elif store == "fhir":
            results = ipa_backend.search.approaches.search_fhir_lexical(
                fhir_settings=FHIR_Settings(), query=search.query, patient_id=patient_id
            )

    elif "llm" in search.method:
        if (
            not llm
        ):  # if LLM settings are not included in request, load them from env file
            llm = LLM_Settings()  # type: ignore
        logger.info("LLM settings: {}", llm.model_dump_json())

        if store == "plain":
            if search.method == "llm_longprompt":
                results = await ipa_backend.search.approaches.LLM_longprompt(
                    query=search.query,
                    search_client=opensearch_client,
                    index=index,
                    llm_settings=llm,
                    patient_id=patient_id,
                )

            elif search.method == "llm_agent_doccheck":
                results = await ipa_backend.search.approaches.agent_doccheck(
                    query=search.query,
                    search_client=opensearch_client,
                    index=index,
                    llm_settings=llm,
                    patient_id=patient_id,
                )

            elif search.method == "llm_agent_wikipedia":
                results = await ipa_backend.search.approaches.agent_wikipedia(
                    query=search.query,
                    search_client=opensearch_client,
                    index=index,
                    llm_settings=llm,
                    patient_id=patient_id,
                )

            else:
                raise NotImplementedError

        elif store == "fhir":
            # Get FHIR settings from environment and fetch access token
            fhir_settings = FHIR_Settings()

            # Compile FHIR Search
            results = ipa_backend.search.approaches.search_fhir_lexical(
                fhir_settings=fhir_settings, query=search.query, patient_id=patient_id
            )

        else:
            raise NotImplementedError

    else:
        raise NotImplementedError

    return results


# save openapi specification in build dir

oa = get_openapi(
    title="iPA Search Core API",
    version="0.0.1",
    description="This is the API specification for the iPA search core.",
    routes=app.routes,
)

os.makedirs("build", exist_ok=True)

with open("build/openapi.yaml", "w") as f:
    yaml.dump(oa, f, sort_keys=False)
