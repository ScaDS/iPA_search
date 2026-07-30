from openai.types import ReasoningEffort
from pydantic import SecretStr
from pydantic_ai import Agent
from pydantic_ai.providers.openai import OpenAIProvider
from pydantic_ai.models.openai import OpenAIChatModel, OpenAIChatModelSettings
from openai import AsyncOpenAI


async def LLM_agent(
    api_base: str,
    api_key: SecretStr,
    model: str,
    reasoning_effort: ReasoningEffort = None,
) -> Agent:
    client = AsyncOpenAI(base_url=api_base, api_key=api_key.get_secret_value())

    agent_model = OpenAIChatModel(model, provider=OpenAIProvider(openai_client=client))

    if reasoning_effort:
        settings = OpenAIChatModelSettings(openai_reasoning_effort=reasoning_effort)
    else:
        settings = None

    return Agent(agent_model, model_settings=settings)
