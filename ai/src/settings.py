"""Agent 실행에 필요한 환경 설정을 불러오고 검증한다."""

from pathlib import Path

from pydantic import Field, HttpUrl, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="SETTINGS_",
        env_file=".env",
        extra="ignore",
        hide_input_in_errors=True,
    )

    model: str = "gpt-6-sol"
    api_key: SecretStr | None = None
    base_url: HttpUrl = HttpUrl("https://api.openai.com/v1")
    max_steps: int = Field(default=50, ge=1)
    max_tool_calls: int = Field(default=30, ge=1)
    max_agent_calls: int = Field(default=10, ge=0)
    max_tool_retries: int = Field(default=2, ge=0)
    runtime_timeout: float = Field(default=300, gt=0)
    llm_timeout: float = Field(default=30, gt=0)
    database_url: SecretStr | None = None
    backend_url: HttpUrl | None = None
    backend_token: SecretStr | None = None
    notification_timeout: float = Field(default=1, gt=0)
    report_concurrency: int = Field(default=2, ge=1)
    database_timeout: int = Field(default=10, ge=1)
    output_dir: Path = Path("outputs/api")
    version: str = "ai-api-v1"

    langfuse_enabled: bool = Field(default=False, validation_alias="LANGFUSE_ENABLED")
    langfuse_public_key: str = Field(default="", validation_alias="LANGFUSE_PUBLIC_KEY")
    langfuse_secret_key: SecretStr = Field(
        default=SecretStr(""), validation_alias="LANGFUSE_SECRET_KEY"
    )
    langfuse_base_url: HttpUrl = Field(
        default=HttpUrl("https://cloud.langfuse.com"),
        validation_alias="LANGFUSE_BASE_URL",
    )
    langfuse_environment: str = Field(
        default="development",
        pattern=r"^[a-z0-9][a-z0-9_-]*$",
        validation_alias="LANGFUSE_TRACING_ENVIRONMENT",
    )
    langfuse_sample_rate: float = Field(
        default=1.0, ge=0, le=1, validation_alias="LANGFUSE_SAMPLE_RATE"
    )

    @model_validator(mode="after")
    def require_langfuse_credentials(self):
        if self.langfuse_enabled and not (
            self.langfuse_public_key.strip()
            and self.langfuse_secret_key.get_secret_value().strip()
        ):
            raise ValueError("LANGFUSE_ENABLED requires public and secret keys")
        return self
