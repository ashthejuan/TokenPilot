from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tokenpilot.config import Settings
from tokenpilot.main import create_app

LOCAL_TOKEN = "test-local-token"


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        local_token=SecretStr(LOCAL_TOKEN),
        db_path=tmp_path / "tokenpilot.sqlite3",
        data_dir=tmp_path,
        upstream_api_key=None,
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
