from pathlib import Path

import pytest
from pydantic import SecretStr

from tokenpilot.config import Settings
from tokenpilot.main import create_app
from tokenpilot.security import REDACTED, redact_headers, redact_text


def test_redact_headers_strips_auth() -> None:
    headers = {
        "Authorization": "Bearer sk-abc",
        "X-Api-Key": "k",
        "Content-Type": "application/json",
    }

    redacted = redact_headers(headers)

    assert redacted["Authorization"] == REDACTED
    assert redacted["X-Api-Key"] == REDACTED
    assert redacted["Content-Type"] == "application/json"
    assert REDACTED == "[REDACTED]"


def test_redact_text_masks_key_patterns(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MODEL_API_KEY", "meta-secret-key-123456")
    text = (
        "key sk-abcdefghijklmnop1234 "
        "header Bearer tok_abc.def "
        "literal meta-secret-key-123456"
    )

    redacted = redact_text(text)

    assert "sk-abcdefghijklmnop1234" not in redacted
    assert "tok_abc.def" not in redacted
    assert "meta-secret-key-123456" not in redacted
    assert redacted.count(REDACTED) == 3


def test_app_refuses_empty_local_token() -> None:
    with pytest.raises(ValueError):
        create_app(Settings(_env_file=None, local_token=""))


def test_factory_refuses_token_that_bypassed_validation(tmp_path: Path) -> None:
    unvalidated = Settings.model_construct(
        local_token=SecretStr(""),
        db_path=tmp_path / "tokenpilot.sqlite3",
        data_dir=tmp_path,
        upstream_api_key=None,
    )

    with pytest.raises(ValueError, match="TOKENPILOT_LOCAL_TOKEN"):
        create_app(unvalidated)


def test_settings_read_env_and_model_key_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKENPILOT_LOCAL_TOKEN", "env-token")
    monkeypatch.setenv("MODEL_API_KEY", "env-model-key")

    settings = Settings(_env_file=None)

    assert settings.local_token.get_secret_value() == "env-token"
    assert isinstance(settings.upstream_api_key, SecretStr)
    assert settings.upstream_api_key.get_secret_value() == "env-model-key"
    assert settings.db_path.name == "tokenpilot.sqlite3"


def test_settings_reads_env_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text("MODEL_API_KEY=sk-fromfileAAAAAAAAAAAA\n", encoding="utf-8")

    from_file = Settings(_env_file=env_file, local_token=SecretStr("t"))
    assert from_file.upstream_api_key is not None
    assert from_file.upstream_api_key.get_secret_value() == "sk-fromfileAAAAAAAAAAAA"

    monkeypatch.setenv("MODEL_API_KEY", "override")
    overridden = Settings(_env_file=env_file, local_token=SecretStr("t"))
    assert overridden.upstream_api_key is not None
    assert overridden.upstream_api_key.get_secret_value() == "override"


def test_fixture_settings_ignore_repo_env_file(settings: Settings) -> None:
    assert settings.upstream_api_key is None
    assert settings.investigator_model == "muse-spark-1.3-contributor"
    assert settings.upstream_provider == "meta"


def test_default_env_file_is_repo_root() -> None:
    # Path comparison only: this test never opens the file.
    repo_root = Path(__file__).resolve().parents[3]
    assert Path(str(Settings.model_config["env_file"])) == repo_root / ".env"
