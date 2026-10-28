import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from tokenpilot.db.database import Database

_INSERT_EVENT = (
    "INSERT INTO usage_events "
    "(id, idempotency_key, provider, model_id, usage_source, status, started_at, "
    "raw_event_json) "
    "VALUES ('e1', 'k1', 'meta', 'muse-spark-1.3', 'provider', 'success', "
    "'2026-10-28T00:00:00Z', '{\"a\":1}')"
)


def test_health_uses_shared_database(
    client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> sqlite3.Connection:
        raise AssertionError("a per-request connection was opened")

    # After startup nothing may open a new connection: the handle is shared.
    monkeypatch.setattr("tokenpilot.db.connection.sqlite3.connect", refuse)

    response = client.get("/api/v1/health", headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["schema_version"] == 2


def test_shared_database_concurrent_reads(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    def call(_: int) -> int:
        return client.get("/api/v1/health", headers=auth_headers).status_code

    with ThreadPoolExecutor(max_workers=50) as pool:
        statuses = list(pool.map(call, range(50)))

    assert statuses == [200] * 50


def test_write_commits_and_rolls_back(client: TestClient, app: FastAPI) -> None:
    db: Database = app.state.db

    with db.write() as conn:
        conn.execute(_INSERT_EVENT)
    with pytest.raises(RuntimeError), db.write() as conn:
        conn.execute("UPDATE usage_events SET status = 'error'")
        raise RuntimeError("boom")

    with db.read() as conn:
        row = conn.execute("SELECT status FROM usage_events WHERE id = 'e1'").fetchone()
    assert row["status"] == "success"


def test_close_is_idempotent_and_blocks_use(client: TestClient, app: FastAPI) -> None:
    db: Database = app.state.db
    db.close()
    db.close()

    with pytest.raises(sqlite3.ProgrammingError), db.read() as conn:
        conn.execute("SELECT 1")


def test_raw_event_json_immutable(client: TestClient, app: FastAPI) -> None:
    db: Database = app.state.db
    with db.write() as conn:
        conn.execute(_INSERT_EVENT)

    with pytest.raises(sqlite3.IntegrityError), db.write() as conn:
        conn.execute("UPDATE usage_events SET raw_event_json = '{}' WHERE id = 'e1'")

    with db.read() as conn:
        raw = conn.execute("SELECT raw_event_json FROM usage_events").fetchone()[0]
    assert raw == '{"a":1}'


@pytest.mark.parametrize(
    ("status", "code"), [(502, "upstream_error"), (504, "upstream_timeout")]
)
def test_upstream_error_codes_mapped(
    app: FastAPI, auth_headers: dict[str, str], status: int, code: str
) -> None:
    @app.get("/api/v1/_upstream")
    def upstream() -> None:
        raise HTTPException(status_code=status, detail="upstream failed")

    with TestClient(app) as client:
        response = client.get("/api/v1/_upstream", headers=auth_headers)

    assert response.status_code == status
    assert response.json()["error"]["code"] == code
