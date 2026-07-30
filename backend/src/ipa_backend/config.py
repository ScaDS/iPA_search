import requests
from openai.types.shared.reasoning_effort import ReasoningEffort
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import SecretStr


class LLM_Settings(BaseSettings):
    api_base_public: str
    api_key_public: SecretStr
    model_public: str
    reasoning_effort: ReasoningEffort | None = None

    model_config = SettingsConfigDict(extra="allow")

class Common_Settings(BaseSettings):
    opensearch_host: str = "localhost"
    opensearch_port: int = 9200

    model_config = SettingsConfigDict(env_file=".env", extra="allow")

class FHIR_Settings(BaseSettings): 
    MEDPLUM_BASE_URL: str 
    MEDPLUM_ACCESS_TOKEN: SecretStr | None = None
    MEDPLUM_CLIENT_ID: str | None
    MEDPLUM_CLIENT_SECRET: SecretStr | None
    MEDPLUM_TOKEN_URL: str
    MEDPLUM_VERIFY_SSL: bool = True
    MEDPLUM_CAPABILITY_PATH: str = "/metadata"
    
    def get_access_token(self) -> SecretStr:
        """
        Get Medplum access token.

        Priority:
        1. Use static token if provided (MEDPLUM_ACCESS_TOKEN)
        2. Otherwise fetch via OAuth client credentials
        """

        if self.MEDPLUM_ACCESS_TOKEN:
            return self.MEDPLUM_ACCESS_TOKEN

        if not self.MEDPLUM_CLIENT_ID or not self.MEDPLUM_CLIENT_SECRET:
            raise ValueError(
                "No MEDPLUM_ACCESS_TOKEN and no valid client credentials provided."
            )

        if not self.MEDPLUM_TOKEN_URL:
            raise ValueError("MEDPLUM_TOKEN_URL is not configured.")

        resp = requests.post(
            self.MEDPLUM_TOKEN_URL,
            data={"grant_type": "client_credentials"},
            auth=(
                self.MEDPLUM_CLIENT_ID,
                self.MEDPLUM_CLIENT_SECRET.get_secret_value(),
            ),
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=20,
        )

        resp.raise_for_status()

        token_data = resp.json()

        if "access_token" not in token_data:
            raise ValueError(f"Token response invalid: {token_data}")

        return SecretStr(token_data["access_token"])
