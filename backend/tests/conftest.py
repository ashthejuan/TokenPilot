import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tokenpilot.config import Settings
from tokenpilot.main import create_app

LOCAL_TOKEN = "test-local-token"


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """The developer's shell may export these; tests must not depend on them."""
    for name in list(os.environ):
        if name.startswith("TOKENPILOT_") or name == "MODEL_API_KEY":
            monkeypatch.delenv(name)


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    # _env_file=None: tests never read the repo's real .env.
    return Settings(
        _env_file=None,
        local_token=SecretStr(LOCAL_TOKEN),
        db_path=tmp_path / "tokenpilot.sqlite3",
        data_dir=tmp_path,
    )


@pytest.fixture
def app(settings: Settings) -> FastAPI:
    return create_app(settings)


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": f"Bearer {LOCAL_TOKEN}"}
