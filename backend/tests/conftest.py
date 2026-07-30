from pydantic_settings import BaseSettings
import os


LLM_CONFIGS = [
    {
        "name": "scads",
        "llm": {
            "api_base_public": "https://llm.scads.ai/v1/",
            "api_key_public": os.environ.get("SCADS_LLM_API_KEY"),
            "model_public": "google/gemma-4-31B-it",
        },
        "usage": ["longprompt", "doccheck", "wikipedia"],
    },
    # {
    #     "name": "openai",
    #     "llm": {
    #         "api_base_public": "https://api.openai.com/v1/",
    #         "api_key_public": os.environ.get("OPENAI_API_KEY"),
    #         "model_public": "gpt-5-mini-2025-08-07",
    #         "reasoning_effort": "minimal",
    #     },
    #     "usage": ["longprompt", "doccheck", "wikipedia"],
    # },
]


class Settings(BaseSettings):
    opensearch_host: str = "localhost"
    opensearch_port: int = 9200
