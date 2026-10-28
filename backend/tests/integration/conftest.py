"""Shared gateway fixtures: fake upstream transport, never the real key."""

from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.fakes.fake_upstream import FakeUpstream
from tokenpilot.config import Settings
from tokenpilot.main import create_app

UPSTREAM_KEY = "fake-upstream-key-for-gateway-tests"


@pytest.fixture
def gateway_settings(settings: Settings) -> Settings:
    return Settings(
        _env_file=None,
        local_token=settings.local_token,
        db_path=settings.db_path,
        data_dir=settings.data_dir,
        upstream_api_key=SecretStr(UPSTREAM_KEY),
        upstream_provider="fake",
    )


@pytest.fixture
def gateway_app(gateway_settings: Settings, fake: FakeUpstream) -> FastAPI:
    return create_app(gateway_settings, upstream_transport=fake.transport())


@pytest.fixture
def gateway_client(gateway_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(gateway_app) as test_client:
        yield test_client
