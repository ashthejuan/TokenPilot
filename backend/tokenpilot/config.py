"""Application settings, sourced from `TOKENPILOT_*` env vars plus `MODEL_API_KEY`."""

from pathlib import Path

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DATA_DIR = Path.home() / ".tokenpilot"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="TOKENPILOT_",
        env_file=REPO_ROOT / ".env",
        env_file_encoding="utf-8",
        # A copied `.env.example` has empty values. Without this, `TOKENPILOT_DB_PATH=`
        # becomes `Path("")` -> `Path(".")` and the app cannot open its database.
        env_ignore_empty=True,
        extra="ignore",
        populate_by_name=True,
    )

    local_token: SecretStr = SecretStr("")
    db_path: Path = DEFAULT_DATA_DIR / "tokenpilot.sqlite3"
    data_dir: Path = DEFAULT_DATA_DIR
    upstream_base_url: str = "https://api.meta.ai/v1"
    upstream_provider: str = "meta"
    upstream_api_key: SecretStr | None = Field(default=None, validation_alias="MODEL_API_KEY")
    investigator_model: str = "muse-spark-1.3-contributor"
    store_content: bool = False
    allow_content_transmission: bool = False

    @field_validator("local_token")
    @classmethod
    def token_must_not_be_empty(cls, value: SecretStr) -> SecretStr:
        if not value.get_secret_value().strip():
            raise ValueError("TOKENPILOT_LOCAL_TOKEN must be set and non-empty")
        return value
