"""Evidence bundle assembly and investigation-preview disclosure (Task 3.1)."""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

import tokenpilot.pricing.catalog as catalog_module
from tests.conftest import LOCAL_TOKEN
from tests.integration.test_insights_storage import PROJECT_ID, make_finding
from tokenpilot.config import Settings
from tokenpilot.db.connection import connect, transaction
from tokenpilot.db.migrate import migrate
from tokenpilot.detectors.base import EvidenceRef
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.investigator.evidence import build_bundle
from tokenpilot.main import create_app
from tokenpilot.pricing.catalog import load_catalog
from tokenpilot.schemas.common import Page
from tokenpilot.schemas.insights import InsightFilters
from tokenpilot.security import REDACTED
from tokenpilot.timeutil import to_utc_z

CATALOG_PATH = Path(catalog_module.__file__).parent / "catalog.yaml"
NOW = "2026-10-28T10:00:00.000Z"
BASE = datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)
AUTH = {"Authorization": f"Bearer {LOCAL_TOKEN}"}
CONTRIBUTOR_SENTENCE = (
    "Contributor mode: Meta may use the content you send to train future models."
)
SECRET = "sk-testaaaaaaaaaaaaaaaa"


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "evidence.sqlite3")
    migrate(connection)
    with transaction(connection):
        load_catalog(connection, CATALOG_PATH)
        connection.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, 'demo', ?, ?)",
            (PROJECT_ID, NOW, NOW),
        )
        connection.execute(
            "INSERT INTO sessions (id, project_id, source, started_at) VALUES (?, ?, 'cli', ?)",
            ("s1", PROJECT_ID, NOW),
        )
    yield connection
    connection.close()


def _insert_event(
    conn: sqlite3.Connection,
    event_id: str,
    *,
    started_at: str | None = None,
    error_category: str | None = None,
    metadata: dict[str, Any] | None = None,
    estimated_cost: float | None = 0.01,
) -> None:
    started = started_at or NOW
    conn.execute(
        "INSERT INTO usage_events (id, idempotency_key, project_id, session_id, provider, "
        "model_id, input_tokens, output_tokens, usage_source, status, latency_ms, attempt, "
        "started_at, error_category, metadata_json) "
        "VALUES (?, ?, ?, 's1', 'fake', 'fake-small', 1000, 100, 'provider', 'success', "
        "50, 1, ?, ?, ?)",
        (
            event_id,
            f"key-{event_id}",
            PROJECT_ID,
            started,
            error_category,
            json.dumps(metadata or {}),
        ),
    )
    if estimated_cost is not None:
        version_id = conn.execute(
            "SELECT id FROM pricing_versions WHERE provider = 'fake' AND model_id = 'fake-small' "
            "LIMIT 1"
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO cost_records (id, usage_event_id, pricing_version_id, estimated_cost, "
            "currency, cost_basis, calculated_at) VALUES (?, ?, ?, ?, 'USD', 'estimated', ?)",
            (f"c-{event_id}", event_id, version_id, estimated_cost, started),
        )


def _insight_with_evidence(
    conn: sqlite3.Connection,
    event_ids: list[str],
    *,
    measurements: dict[str, Any] | None = None,
    rule_id: str = "retry_amplification",
) -> str:
    evidence = [
        EvidenceRef(kind="usage_event", id=event_id, measurement={}) for event_id in event_ids
    ]
    finding = make_finding(
        rule_id=rule_id,
        anchor=f"bundle:{event_ids[0]}",
        evidence=evidence[:50],
        measurements=measurements or {"retries": 3},
        title="Retry amplification",
        summary="Retries amplified spend.",
    )
    repo = InsightRepository(conn)
    repo.upsert(finding, NOW)
    insight_id = repo.list(InsightFilters(), Page()).items[0].id
    if len(event_ids) > 50:
        # Insight storage caps evidence at 50; bundle tests need the full ordered list.
        conn.execute(
            "UPDATE insights SET evidence_json = ?, evidence_truncated = 0 WHERE id = ?",
            (
                json.dumps(
                    [{"kind": "usage_event", "id": eid, "measurement": {}} for eid in event_ids],
                    sort_keys=True,
                ),
                insight_id,
            ),
        )
    return insight_id


def _settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "_env_file": None,
        "local_token": SecretStr(LOCAL_TOKEN),
        "db_path": Path("/tmp/unused.sqlite3"),
        "data_dir": Path("/tmp"),
    }
    values.update(overrides)
    return Settings(**values)


def test_metadata_only_has_no_excerpts(conn: sqlite3.Connection) -> None:
    _insert_event(conn, "e1")
    conn.execute(
        "INSERT INTO content_excerpts (id, usage_event_id, role, sha256, text, created_at) "
        "VALUES ('x1', 'e1', 'user', 'abc', 'prompt text', ?)",
        (NOW,),
    )
    insight_id = _insight_with_evidence(conn, ["e1"])
    settings = _settings(allow_content_transmission=True, store_content=True)

    bundle = build_bundle(conn, insight_id, "metadata_only", settings=settings)

    assert bundle.excerpts == []


def test_excerpts_refused_when_transmission_disabled(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    _insert_event(conn, "e1")
    insight_id = _insight_with_evidence(conn, ["e1"])
    settings = _settings(allow_content_transmission=False, store_content=False)

    with pytest.raises(PermissionError):
        build_bundle(conn, insight_id, "with_excerpts", settings=settings)

    # API surface: 403 with content_transmission_disabled.
    db_path = tmp_path / "preview-refuse.sqlite3"
    api_conn = connect(db_path)
    migrate(api_conn)
    with transaction(api_conn):
        load_catalog(api_conn, CATALOG_PATH)
        api_conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, 'demo', ?, ?)",
            (PROJECT_ID, NOW, NOW),
        )
        api_conn.execute(
            "INSERT INTO sessions (id, project_id, source, started_at) VALUES (?, ?, 'cli', ?)",
            ("s1", PROJECT_ID, NOW),
        )
        _insert_event(api_conn, "e1")
        api_insight = _insight_with_evidence(api_conn, ["e1"])
    api_conn.close()

    app = create_app(
        Settings(
            _env_file=None,
            local_token=SecretStr(LOCAL_TOKEN),
            db_path=db_path,
            data_dir=tmp_path,
            allow_content_transmission=False,
            store_content=False,
        )
    )
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/insights/{api_insight}/investigation-preview",
            params={"mode": "with_excerpts"},
            headers=AUTH,
        )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "content_transmission_disabled"


def test_missing_insight_prefers_404_over_excerpt_permission(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    """Unknown insight + with_excerpts + transmission off → LookupError / 404, not 403."""
    settings = _settings(allow_content_transmission=False, store_content=False)
    with pytest.raises(LookupError):
        build_bundle(conn, "missing-insight", "with_excerpts", settings=settings)

    db_path = tmp_path / "preview-missing.sqlite3"
    api_conn = connect(db_path)
    migrate(api_conn)
    with transaction(api_conn):
        load_catalog(api_conn, CATALOG_PATH)
    api_conn.close()

    app = create_app(
        Settings(
            _env_file=None,
            local_token=SecretStr(LOCAL_TOKEN),
            db_path=db_path,
            data_dir=tmp_path,
            allow_content_transmission=False,
            store_content=False,
        )
    )
    with TestClient(app) as client:
        response = client.get(
            "/api/v1/insights/missing-insight/investigation-preview",
            params={"mode": "with_excerpts"},
            headers=AUTH,
        )
    assert response.status_code == 404


def test_bundle_capped_at_50_events(conn: sqlite3.Connection) -> None:
    event_ids = [f"e{i}" for i in range(60)]
    for i, event_id in enumerate(event_ids):
        _insert_event(conn, event_id, started_at=to_utc_z(BASE + timedelta(seconds=i)))
    insight_id = _insight_with_evidence(conn, event_ids)
    settings = _settings()

    bundle = build_bundle(conn, insight_id, "metadata_only", settings=settings)

    assert len(bundle.events) == 50
    assert bundle.coverage["events_truncated"] == 10
    assert [row["id"] for row in bundle.events] == event_ids[:50]


def test_bundle_contains_no_secrets(conn: sqlite3.Connection) -> None:
    _insert_event(
        conn,
        "e1",
        error_category=f"upstream said {SECRET}",
        metadata={"note": SECRET},
    )
    insight_id = _insight_with_evidence(conn, ["e1"])
    settings = _settings()

    bundle = build_bundle(conn, insight_id, "metadata_only", settings=settings)
    serialized = json.dumps(bundle.to_dict(), default=str)

    assert SECRET not in serialized
    assert REDACTED in serialized or "sk-test" not in serialized


def test_excerpts_are_redacted_when_transmission_allowed(conn: sqlite3.Connection) -> None:
    _insert_event(conn, "e1")
    conn.execute(
        "INSERT INTO content_excerpts (id, usage_event_id, role, sha256, text, created_at) "
        "VALUES ('x1', 'e1', 'user', 'abc', ?, ?)",
        (f"Please use {SECRET} in the call", NOW),
    )
    insight_id = _insight_with_evidence(conn, ["e1"])
    settings = _settings(allow_content_transmission=True, store_content=True)

    bundle = build_bundle(conn, insight_id, "with_excerpts", settings=settings)

    assert len(bundle.excerpts) == 1
    assert SECRET not in bundle.excerpts[0]["text"]
    assert REDACTED in bundle.excerpts[0]["text"]


def test_preview_includes_contributor_disclosure(tmp_path: Path) -> None:
    db_path = tmp_path / "preview.sqlite3"
    connection = connect(db_path)
    migrate(connection)
    with transaction(connection):
        load_catalog(connection, CATALOG_PATH)
        connection.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, 'demo', ?, ?)",
            (PROJECT_ID, NOW, NOW),
        )
        connection.execute(
            "INSERT INTO sessions (id, project_id, source, started_at) VALUES (?, ?, 'cli', ?)",
            ("s1", PROJECT_ID, NOW),
        )
        _insert_event(connection, "e1")
        insight_id = _insight_with_evidence(connection, ["e1"])
    connection.close()

    app = create_app(
        Settings(
            _env_file=None,
            local_token=SecretStr(LOCAL_TOKEN),
            db_path=db_path,
            data_dir=tmp_path,
            # Default investigator_model contains "contributor".
        )
    )
    with TestClient(app) as client:
        response = client.get(
            f"/api/v1/insights/{insight_id}/investigation-preview",
            params={"mode": "metadata_only"},
            headers=AUTH,
        )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["contributor_training"] is True
    assert CONTRIBUTOR_SENTENCE in body["disclosure_lines"]
    assert body["contains_content"] is False
    assert body["model"]
    assert body["destination"]
    assert "bundle" in body
    assert body["bundle"]["investigation_id"]


def test_allowed_numbers_include_measurement_values(conn: sqlite3.Connection) -> None:
    _insert_event(conn, "e1", estimated_cost=0.22)
    insight_id = _insight_with_evidence(
        conn,
        ["e1"],
        measurements={"retry_cost": 0.22, "retries": 3},
    )
    settings = _settings()

    bundle = build_bundle(conn, insight_id, "metadata_only", settings=settings)

    assert 0.22 in bundle.allowed_numbers


def test_pricing_rows_batch_dedupes_same_model(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Many same-model events resolve pricing in one batched catalogue call."""
    import tokenpilot.investigator.evidence as evidence_mod
    from tokenpilot.pricing.catalog import select_pricing_many

    event_ids = [f"e{i}" for i in range(12)]
    for i, event_id in enumerate(event_ids):
        _insert_event(
            conn,
            event_id,
            started_at=to_utc_z(BASE + timedelta(seconds=i)),
            estimated_cost=0.01,
        )
    insight_id = _insight_with_evidence(conn, event_ids)
    settings = _settings()

    calls: list[list[tuple[str, str, str]]] = []

    def tracking_select(
        c: sqlite3.Connection, keys: list[tuple[str, str, str]]
    ) -> object:
        calls.append(list(keys))
        return select_pricing_many(c, keys)

    monkeypatch.setattr(evidence_mod, "select_pricing_many", tracking_select)

    bundle = build_bundle(conn, insight_id, "metadata_only", settings=settings)

    assert len(calls) == 1
    assert len(calls[0]) == 1
    assert calls[0][0][:2] == ("fake", "fake-small")
    assert len(bundle.pricing) == 1
    assert bundle.pricing[0]["model_id"] == "fake-small"
