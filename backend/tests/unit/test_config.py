from pathlib import Path

import pytest
from pydantic import ValidationError

from tokenpilot.config import DEFAULT_DATA_DIR, Settings


def test_blank_env_file_values_fall_back_to_defaults(tmp_path: Path) -> None:
    """A copied `.env.example` has empty values; they must not override the defaults."""
    env_file = tmp_path / ".env"
    env_file.write_text(
        "TOKENPILOT_LOCAL_TOKEN=tok\nTOKENPILOT_DB_PATH=\nTOKENPILOT_UPSTREAM_BASE_URL=\n"
    )

    settings = Settings(_env_file=env_file)

    assert settings.db_path == DEFAULT_DATA_DIR / "tokenpilot.sqlite3"
    assert settings.upstream_base_url == "https://api.meta.ai/v1"
    assert settings.local_token.get_secret_value() == "tok"


def test_blank_env_file_token_still_fails_loudly(tmp_path: Path) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("TOKENPILOT_LOCAL_TOKEN=\n")

    with pytest.raises(ValidationError):
        Settings(_env_file=env_file)
