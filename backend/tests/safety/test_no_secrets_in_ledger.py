"""No secret may land in the ledger or the logs through the gateway."""

import logging
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.fakes.fake_upstream import FakeUpstream
from tokenpilot.config import Settings
from tokenpilot.db.database import Database
from tokenpilot.main import create_app

UPSTREAM_SECRET = "sk-fake-upstream-secret-7f3a9c2e"
LOCAL_SECRET = "local-token-secret-9d4b1e8f"
MESSAGE_SECRET = "ping-secret-content"

CHAT = "/gateway/v1/chat/completions"


@pytest.fixture
def secret_app(settings: Settings, fake: FakeUpstream) -> FastAPI:
    resolved = Settings(
        _env_file=None,
        local_token=SecretStr(LOCAL_SECRET),
        db_path=settings.db_path,
        data_dir=settings.data_dir,
        upstream_api_key=SecretStr(UPSTREAM_SECRET),
        upstream_provider="fake",
    )
    return create_app(resolved, upstream_transport=fake.transport())


@pytest.fixture
def secret_client(secret_app: FastAPI) -> Iterator[TestClient]:
    with TestClient(secret_app) as test_client:
        yield test_client


def test_no_secrets_in_ledger(
    secret_app: FastAPI,
    secret_client: TestClient,
    caplog: pytest.LogCaptureFixture,
) -> None:
    body: dict[str, Any] = {
        "model": "fake-large",
        "messages": [{"role": "user", "content": MESSAGE_SECRET}],
    }
    headers = {
        "Authorization": f"Bearer {LOCAL_SECRET}",
        "X-TokenPilot-Project": "alpha",
        "X-TokenPilot-Session": "sess-1",
    }
    with caplog.at_level(logging.DEBUG, logger="tokenpilot"):
        response = secret_client.post(CHAT, json=body, headers=headers)
    assert response.status_code == 200

    forbidden = (UPSTREAM_SECRET, LOCAL_SECRET, MESSAGE_SECRET, "Bearer")
    db: Database = secret_app.state.db
    with db.read() as conn:
        for row in conn.execute("SELECT * FROM usage_events").fetchall():
            blob = " ".join(str(value) for value in tuple(row))
            for secret in forbidden:
                assert secret not in blob, f"{secret[:8]}… leaked into usage_events"
        for row in conn.execute("SELECT * FROM cost_records").fetchall():
            blob = " ".join(str(value) for value in tuple(row))
            for secret in forbidden:
                assert secret not in blob, f"{secret[:8]}… leaked into cost_records"
    for secret in forbidden:
        assert secret not in caplog.text
