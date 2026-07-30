from enum import Enum
from pydantic import BaseModel, Field
from typing import Annotated, Any


class SearchMethod(str, Enum):
    """The search method (approach) used to search in the EHR. Options available:

    - lexical: BM25 search as implemented by OpenSearch. Accepts also Lucene or OpenSearch DSL.
    - llm_longprompt: Physician's retrieval knowledge is included in the LLM prompt. The LLM is asked to expand the search query using Lucene DSL.
    - llm_agent_doccheck: Like llm_longprompt but the LLM has access to DocCheck Flexikon via the DocCheck MSP server.
    - llm_agent_wikipedia: Like llm_longprompt but the LLM has access to Wikipedia articles.
    """

    lexical = "lexical"
    llm_longprompt = "llm_longprompt"
    llm_agent_doccheck = "llm_agent_doccheck"
    llm_agent_wikipedia = "llm_agent_wikipedia"


class Search(BaseModel):
    method: Annotated[
        SearchMethod,
        Field(
            description="The search method used for retrieval. For explanation of available options, see SearchMethod schema."
        ),
    ] = SearchMethod.lexical
    query: Annotated[str, Field(description="Search query.")]
    patient_id: Annotated[str | None, Field(description="Patient ID in FHIR server. Currently only used in FHIR search.")] = None


class SearchResult(BaseModel):
    os_results: dict[str, Any]
    explanation: str | None = None


class Store(str, Enum):
    """The document store that is searched in. Can be either 'plain' for Opensearch as unstructured data or 'fhir' for structured data from a FHIR server."""
    plain = "plain"
    fhir = "fhir"
