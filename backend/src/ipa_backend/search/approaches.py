from ipa_backend.config import LLM_Settings, FHIR_Settings
from pydantic_ai.mcp import MCPServerStreamableHTTP
from ipa_backend.llms.tools import search_wikipedia, get_wikipedia_article
from opensearchpy import OpenSearch
from fastapi import HTTPException, status
from pydantic_ai import ToolCallPart, FunctionToolset
from pydantic_ai.agent import CallToolsNode
from loguru import logger

from ipa_backend.llms.connector import LLM_agent
from ipa_backend.llms import prompts
from ipa_backend.models import SearchResult
from ipa_backend.search.fhir_search import search_resources_fhir


def _search_os(
    search_client: OpenSearch,
    index: str,
    query_body: dict,
    patient_id: str,
) -> SearchResult:
    body = {
        "size": 1000,
        "highlight": {
            "pre_tags": ["<em>"],
            "post_tags": ["</em>"],
            "fields": {
                "content": {
                    "number_of_fragments": 0  # Return entire field
                }
            },
        },
    }

    filtered_query = {
        "query": {
            "bool": {
                "must": query_body["query"],
                "filter": {"term": {"patient_id": patient_id}},
            }
        }
    }
    body.update(filtered_query)

    response = search_client.search(body=body, index=index)

    logger.info(f"Search results: {response}")

    return SearchResult(os_results=response)


def BM25(
    search_client: OpenSearch, index: str, query: str, patient_id: str
) -> SearchResult:
    query_body = {
        "query": {
            "match": {
                "content": query,
            }
        },
    }

    result = _search_os(search_client, index, query_body, patient_id)

    return result


def LuceneDSL(
    search_client: OpenSearch, index: str, query: str, patient_id: str
) -> SearchResult:
    query_body = {
        "query": {
            "query_string": {
                "query": query,
            }
        },
    }

    result = _search_os(search_client, index, query_body, patient_id)

    return result


async def LLM_longprompt(
    query: str,
    search_client: OpenSearch,
    index: str,
    llm_settings: LLM_Settings,
    patient_id: str,
) -> SearchResult:
    prompt_template = prompts.gpt5_optimized
    prompt = prompt_template + query
    logger.info(f'Using the following prompt: "{prompt}"')

    # set up LLM client
    llm_agent = await LLM_agent(
        api_base=llm_settings.api_base_public,
        api_key=llm_settings.api_key_public,
        model=llm_settings.model_public,
        reasoning_effort=llm_settings.reasoning_effort,
    )

    llm_response = await llm_agent.run(prompt)

    augmented_query = llm_response.output
    logger.info(f"LLM augmented query: '{augmented_query}'")

    if augmented_query:
        response = LuceneDSL(
            search_client, index, augmented_query, patient_id
        ).os_results
    else:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Query expansion failed: LLM returned no response.",
        )

    return SearchResult(os_results=response, explanation=augmented_query)


async def agent_doccheck(
    query: str,
    search_client: OpenSearch,
    index: str,
    llm_settings: LLM_Settings,
    patient_id: str,
) -> SearchResult:
    mcp = MCPServerStreamableHTTP("https://flexikon-mcp.doccheck.com/mcp")

    # set up LLM client with tools aka agent
    llm_agent = await LLM_agent(
        api_base=llm_settings.api_base_public,
        api_key=llm_settings.api_key_public,
        model=llm_settings.model_public,
        reasoning_effort=llm_settings.reasoning_effort,
    )

    agent_steps = ""
    step_counter = 1

    async with llm_agent.iter(
        user_prompt=prompts.agent_doccheck_prompt + query, toolsets=[mcp]
    ) as agent_run:
        async for node in agent_run:
            logger.info(node)

            if isinstance(node, CallToolsNode):
                for part in node.model_response.parts:
                    if isinstance(part, ToolCallPart):
                        tool_call = part.tool_name
                        tool_arg = next(iter(part.args_as_dict().values()))
                        if tool_call == "search_medical_knowledge_base":
                            agent_steps += (
                                f'{step_counter}. Search DocCheck for "{tool_arg}"\n'
                            )
                        if tool_call == "get_medical_content":
                            agent_steps += f'{step_counter}. Retrieve DocCheck article "{tool_arg}"\n'
                        step_counter += 1

        if agent_run.result:
            augmented_query = agent_run.result.output
        else:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="DocCheck agent did not respond.",
            )
        logger.info(augmented_query)

        search_results = LuceneDSL(
            search_client, index, augmented_query, patient_id
        ).os_results

        return SearchResult(
            os_results=search_results,
            explanation=f"\n\nAgent Steps:\n\n{agent_steps}\n\n\nSearch Query:\n\n{augmented_query}",
        )


async def agent_wikipedia(
    query: str,
    search_client: OpenSearch,
    index: str,
    llm_settings: LLM_Settings,
    patient_id: str,
) -> SearchResult:
    # set up LLM client with tools aka agent
    llm_agent = await LLM_agent(
        api_base=llm_settings.api_base_public,
        api_key=llm_settings.api_key_public,
        model=llm_settings.model_public,
        reasoning_effort=llm_settings.reasoning_effort,
    )

    tools = [search_wikipedia, get_wikipedia_article]

    agent_steps = ""
    step_counter = 1

    async with llm_agent.iter(
        user_prompt=prompts.agent_wikipedia_prompt + query,
        toolsets=[FunctionToolset(tools)],
    ) as agent_run:
        async for node in agent_run:
            logger.info(node)

            if isinstance(node, CallToolsNode):
                for part in node.model_response.parts:
                    if isinstance(part, ToolCallPart):
                        tool_call = part.tool_name
                        tool_arg = next(iter(part.args_as_dict().values()))
                        if tool_call == "search_wikipedia":
                            agent_steps += (
                                f'{step_counter}. Search Wikipedia for "{tool_arg}"\n'
                            )
                        if tool_call == "get_wikipedia_article":
                            agent_steps += f'{step_counter}. Retrieve Wikipedia article "{tool_arg}"\n'
                        step_counter += 1

        if agent_run.result:
            augmented_query = agent_run.result.output
        else:
            raise HTTPException(
                status_code=status.HTTP_504_GATEWAY_TIMEOUT,
                detail="Wikipedia agent did not respond.",
            )
        logger.info(augmented_query)

        search_results = LuceneDSL(
            search_client, index, augmented_query, patient_id
        ).os_results

        return SearchResult(
            os_results=search_results,
            explanation=f"\n\nAgent Steps:\n\n{agent_steps}\n\n\nSearch Query:\n\n{augmented_query}",
        )


# lexical search for FHIR resources via FHIR API
def search_fhir_lexical(
    fhir_settings: FHIR_Settings, query: str, patient_id: str
) -> SearchResult:
    """
    Search FHIR resources using lexical search via FHIR API.
    Uses the _text parameter to search across all text fields.
    """
    results = search_resources_fhir(fhir_settings, query, patient_id)
    # convert to OpenSearch-like format for compatibility
    os_results = {
        "hits": {
            "total": {"value": len(results)},
            "hits": [{"_source": resource, "_index": "fhir"} for resource in results],
        }
    }

    return SearchResult(os_results=os_results)
