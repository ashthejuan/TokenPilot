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
        create_app(Settings(local_token=""))


def test_settings_read_env_and_model_key_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TOKENPILOT_LOCAL_TOKEN", "env-token")
    monkeypatch.setenv("MODEL_API_KEY", "env-model-key")

    settings = Settings()

    assert settings.local_token.get_secret_value() == "env-token"
    assert isinstance(settings.upstream_api_key, SecretStr)
    assert settings.upstream_api_key.get_secret_value() == "env-model-key"
    assert settings.db_path.name == "tokenpilot.sqlite3"
