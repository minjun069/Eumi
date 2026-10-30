"""Model credentials are external; local experiment limits are explicit settings."""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SETTINGS_", env_file=".env", extra="ignore"
    )

    model: str = "gpt-6-sol"
    api_key: SecretStr | None = None
    max_steps: int = Field(default=20, ge=1)
    max_tool_calls: int = Field(default=10, ge=1)
    max_agent_calls: int = Field(default=10, ge=0)
    max_tool_retries: int = Field(default=2, ge=0)
    runtime_timeout: float = Field(default=60, gt=0)
    llm_timeout: float = Field(default=30, gt=0)

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls,
        init_settings,
        env_settings,
        dotenv_settings,
        file_secret_settings,
    ):
        def credentials(source):
            return {k: v for k, v in source().items() if k in {"model", "api_key"}}

        return (
            init_settings,
            lambda: credentials(env_settings),
            lambda: credentials(dotenv_settings),
        )
