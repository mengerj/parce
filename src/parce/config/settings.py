from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

_PROJECT_ROOT = Path(__file__).resolve().parents[3]


class Settings(BaseSettings):
    """Application settings loaded from environment variables or a .env file."""

    model_config = SettingsConfigDict(
        env_file=str(_PROJECT_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    azure_ai_project_endpoint: str
    azure_ai_model_deployment_name: str = "mistral-large"
    max_retries: int = 3

    # NCBI E-utilities / GEO courtesy parameters (optional). NCBI asks callers to
    # identify themselves; supplying these raises rate limits. Neither is required
    # for GEO fetches to work.
    ncbi_email: str | None = None
    ncbi_api_key: str | None = None
