from functools import lru_cache

from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    app_name: str = Field(default="APITestAgent", validation_alias="APP_NAME")
    environment: str = Field(default="development", validation_alias="APP_ENV")
    log_level: str = Field(default="INFO", validation_alias="LOG_LEVEL")
    llm_api_key: str | None = Field(
        default=None,
        validation_alias=AliasChoices("LLM_API_KEY", "DEEPSEEK_API_KEY"),
    )
    llm_base_url: str = Field(
        default="https://api.deepseek.com",
        validation_alias=AliasChoices("LLM_BASE_URL", "DEEPSEEK_BASE_URL"),
    )
    llm_model: str = Field(
        default="deepseek-chat",
        validation_alias=AliasChoices("LLM_MODEL", "DEEPSEEK_MODEL"),
    )
    llm_timeout_seconds: float = Field(default=20.0, validation_alias="LLM_TIMEOUT_SECONDS")

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
