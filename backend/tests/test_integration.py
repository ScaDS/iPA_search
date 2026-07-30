from fastapi.testclient import TestClient
import pytest
from opensearchpy import OpenSearch

from ipa_backend.main import app
from conftest import Settings, LLM_CONFIGS


settings = Settings()
client = TestClient(app)  # Global variable

patient_id = "b41c7104-03f2-4ca8-31c7-173eb0e23188"


@pytest.fixture(scope="session", params=["plain"], ids=["plain"])
# one day when fhir store is implemented:
# @pytest.fixture(scope="session", params=["plain", "fhir"], ids=["plain", "fhir"])
def api_prefix(request):
    return request.param


@pytest.fixture(scope="session")
def os_client():
    """OpenSearch client for cleanup-only. Index creation goes through the API."""
    client = OpenSearch(
        hosts=[{"host": settings.opensearch_host, "port": settings.opensearch_port}],
        http_compress=True,
        use_ssl=False,
        verify_certs=False,
        ssl_assert_hostname=False,
        ssl_show_warn=False,
    )
    client.indices.delete(index="test-index", ignore=[404])
    yield client
    client.indices.delete(index="test-index", ignore=[404])
    client.close()


@pytest.fixture(scope="session")
def add_test_data(os_client, api_prefix):
    response = client.put(
        f"/{api_prefix}/index_files/test-index?path=backend/tests/test_data/documents/&patient_id={patient_id}"
    )
    # necessary to be able to search documents immediately
    os_client.indices.refresh(index="test-index")
    return response


def test_health_check(api_prefix):
    response = client.get(f"/{api_prefix}/checkhealth")
    assert response.status_code == 200, "Cannot connect to OpenSearch instance"
    assert response.json()["status"] == "green", (
        "OpenSearch cluster status is not green"
    )


def test_get_search_methods(api_prefix):
    response = client.get(f"/{api_prefix}/search")
    assert response.status_code == 200
    assert "lexical" in response.json()


def test_index_files(os_client, add_test_data):
    assert add_test_data.status_code == 200

    # search for all documents with "Albers" in filename
    search_body = {"query": {"wildcard": {"filename.keyword": {"value": "*Albers*"}}}}
    search_results = os_client.search(index="test-index", body=search_body)

    # there should be exactly one Albers file: Albers2 is a duplicate
    assert search_results["hits"]["total"]["value"] == 1


def test_lexical_search(add_test_data, api_prefix):
    response = client.post(
        f"/{api_prefix}/search/test-index/{patient_id}",
        json={"search": {"method": "lexical", "query": "diabetes"}},
    )

    assert response.status_code == 200
    # there is one patient with diabetes in the test data
    assert response.json()["os_results"]["hits"]["total"]["value"] == 1


def test_lexical_search_cross_patient(add_test_data, api_prefix):
    """Ensure documents are isolated per patient_id."""
    response = client.post(
        f"/{api_prefix}/search/test-index/other-patient-id",
        json={"search": {"method": "lexical", "query": "diabetes"}},
    )

    assert response.status_code == 200
    # no results for a different patient
    assert response.json()["os_results"]["hits"]["total"]["value"] == 0


@pytest.mark.parametrize(
    "llm_config",
    [cfg["llm"] for cfg in LLM_CONFIGS if "longprompt" in cfg["usage"]],
    ids=[cfg["name"] for cfg in LLM_CONFIGS if "longprompt" in cfg["usage"]],
)
def test_llm_longprompt_search(llm_config, add_test_data, api_prefix):
    response = client.post(
        f"/{api_prefix}/search/test-index/{patient_id}",
        json={
            "search": {"method": "llm_longprompt", "query": "diabetes"},
            "llm": llm_config,
        },
    )

    assert response.status_code == 200
    assert response.json()["os_results"]["hits"]["total"]["value"] > 0


@pytest.mark.parametrize(
    "llm_config",
    [cfg["llm"] for cfg in LLM_CONFIGS if "doccheck" in cfg["usage"]],
    ids=[cfg["name"] for cfg in LLM_CONFIGS if "doccheck" in cfg["usage"]],
)
def test_llm_agent_doccheck_search(llm_config, add_test_data, api_prefix):
    response = client.post(
        f"/{api_prefix}/search/test-index/{patient_id}",
        json={
            "search": {"method": "llm_agent_doccheck", "query": "Tumor"},
            "llm": llm_config,
        },
    )

    assert response.status_code == 200
    assert response.json()["os_results"]["hits"]["total"]["value"] > 0


@pytest.mark.parametrize(
    "llm_config",
    [cfg["llm"] for cfg in LLM_CONFIGS if "wikipedia" in cfg["usage"]],
    ids=[cfg["name"] for cfg in LLM_CONFIGS if "wikipedia" in cfg["usage"]],
)
def test_llm_agent_wikipedia_search(llm_config, add_test_data, api_prefix):
    response = client.post(
        f"/{api_prefix}/search/test-index/{patient_id}",
        json={
            "search": {"method": "llm_agent_wikipedia", "query": "Tumor"},
            "llm": llm_config,
        },
    )

    assert response.status_code == 200
    assert response.json()["os_results"]["hits"]["total"]["value"] > 0
