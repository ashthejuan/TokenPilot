"""Investigation service, API, and recommendation feedback (Task 3.3)."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tests.fakes.fake_upstream import FakeUpstream, error
from tests.integration.test_insights_api import (
    INSIGHTS,
    _analyze,
    _seed_pair_and_chain,
    _wait_job,
)
from tokenpilot.config import Settings
from tokenpilot.insights.jobs import JobRepository
from tokenpilot.investigator.client import MetaClient
from tokenpilot.main import create_app

LOCAL_TOKEN = "test-local-token"
AUTH = {"Authorization": f"Bearer {LOCAL_TOKEN}"}
UPSTREAM_KEY = "fake-model-key-for-investigate-tests"


def _valid_payload(
    *, evidence_ids: list[str], statement: str = "Retries amplified spend"
) -> dict[str, Any]:
    return {
        "title": "Retry waste",
        "summary": "Repeated retries after rate limits wasted tokens",
        "observed_facts": [{"statement": statement, "evidence_ids": evidence_ids}],
        "root_cause_hypothesis": "Client retried without backoff after rate_limited errors",
        "impact_assessment": "Extra attempts increased cost without improving success",
        "recommendation": {
            "action": "Cap retries and add exponential backoff",
            "variable_to_change": "retry_policy",
            "expected_direction": "lower_cost",
            "validation_procedure": "A/B: baseline vs capped retries on same fingerprint",
            "proposed_benchmark": {
                "baseline_change": "keep current retry count",
                "alternative_change": "max 2 retries with backoff",
            },
        },
        "confidence": "medium",
        "limitations": ["Neighbours may be truncated"],
        "verdict": "supported",
    }


def _insufficient_payload(*, evidence_ids: list[str]) -> dict[str, Any]:
    body = _valid_payload(evidence_ids=evidence_ids)
    body["verdict"] = "insufficient_evidence"
    body["root_cause_hypothesis"] = "Cannot determine root cause from metadata alone"
    body["confidence"] = "low"
    return body


@pytest.fixture
def investigate_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        local_token=SecretStr(LOCAL_TOKEN),
        db_path=tmp_path / "investigate.sqlite3",
        data_dir=tmp_path,
        upstream_base_url="https://fake.meta.test/v1",
        upstream_api_key=SecretStr(UPSTREAM_KEY),
        upstream_provider="fake",
        investigator_model="muse-spark-1.3-contributor",
    )


@pytest.fixture
def investigate_app(investigate_settings: Settings, fake: FakeUpstream) -> FastAPI:
    return create_app(investigate_settings, upstream_transport=fake.transport())


@pytest.fixture
def investigate_client(investigate_app: FastAPI) -> TestClient:
    with TestClient(investigate_app) as client:
        yield client


def _retry_insight_id(client: TestClient) -> str:
    _seed_pair_and_chain(client, AUTH)
    job_id = _analyze(client, AUTH)
    job = _wait_job(client, AUTH, job_id)
    assert job["status"] == "succeeded"
    listed = client.get(INSIGHTS, headers=AUTH)
    assert listed.status_code == 200
    items = listed.json()["items"]
    retry = next(i for i in items if i["rule_id"] == "retry_amplification")
    return str(retry["id"])


def _evidence_event_ids(client: TestClient, insight_id: str) -> list[str]:
    detail = client.get(f"{INSIGHTS}/{insight_id}", headers=AUTH)
    assert detail.status_code == 200
    evidence = detail.json()["insight"]["evidence"]
    return [ref["id"] for ref in evidence if ref["kind"] == "usage_event"]


def _investigate(
    client: TestClient, insight_id: str, body: dict[str, Any] | None = None
) -> str:
    response = client.post(
        f"{INSIGHTS}/{insight_id}/investigate",
        json=body or {},
        headers=AUTH,
    )
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def test_valid_output_persisted_with_model_and_prompt_version(
    investigate_client: TestClient, fake: FakeUpstream, investigate_app: FastAPI
) -> None:
    insight_id = _retry_insight_id(investigate_client)
    event_ids = _evidence_event_ids(investigate_client, insight_id)
    assert event_ids
    fake.enqueue_investigation(_valid_payload(evidence_ids=[event_ids[0]]))

    job_id = _investigate(investigate_client, insight_id)
    job = _wait_job(investigate_client, AUTH, job_id)
    assert job["status"] == "succeeded"
    assert "investigation_id" in job["result"]

    listed = investigate_client.get(f"{INSIGHTS}/{insight_id}/investigations", headers=AUTH)
    assert listed.status_code == 200
    items = listed.json()
    assert len(items) == 1
    inv = items[0]
    assert inv["status"] == "completed"
    assert inv["model"] == "muse-spark-1.3-contributor"
    assert inv["prompt_version"] == "investigate_v1"
    assert inv["result"]["verdict"] == "supported"

    detail = investigate_client.get(f"{INSIGHTS}/{insight_id}", headers=AUTH)
    insight = detail.json()["insight"]
    assert insight["root_cause_hypothesis"]
    assert insight["recommendation"] is not None
    assert insight["investigator_model"] == "muse-spark-1.3-contributor"

    with investigate_app.state.db.read() as conn:
        rows = conn.execute(
            "SELECT project_id, session_id FROM usage_events WHERE project_id = ?",
            ("tokenpilot-internal",),
        ).fetchall()
    assert len(rows) >= 1
    assert rows[0]["session_id"] == inv["id"]


def test_invalid_then_valid_retry_succeeds(
    investigate_client: TestClient, fake: FakeUpstream
) -> None:
    insight_id = _retry_insight_id(investigate_client)
    event_ids = _evidence_event_ids(investigate_client, insight_id)
    fake.enqueue_investigation(_valid_payload(evidence_ids=["bogus-not-in-bundle"]))
    fake.enqueue_investigation(_valid_payload(evidence_ids=[event_ids[0]]))

    job_id = _investigate(investigate_client, insight_id)
    job = _wait_job(investigate_client, AUTH, job_id)
    assert job["status"] == "succeeded"
    assert len(fake.requests) >= 2

    listed = investigate_client.get(f"{INSIGHTS}/{insight_id}/investigations", headers=AUTH)
    inv = listed.json()[0]
    assert inv["status"] == "completed"
    detail = investigate_client.get(f"{INSIGHTS}/{insight_id}", headers=AUTH)
    assert detail.json()["insight"]["recommendation"] is not None


def test_twice_invalid_marked_insufficient_evidence(
    investigate_client: TestClient, fake: FakeUpstream
) -> None:
    insight_id = _retry_insight_id(investigate_client)
    fake.enqueue_investigation(_valid_payload(evidence_ids=["bogus-a"]))
    fake.enqueue_investigation(_valid_payload(evidence_ids=["bogus-b"]))

    job_id = _investigate(investigate_client, insight_id)
    job = _wait_job(investigate_client, AUTH, job_id)
    assert job["status"] == "succeeded"
    assert len(fake.requests) >= 2

    listed = investigate_client.get(f"{INSIGHTS}/{insight_id}/investigations", headers=AUTH)
    inv = listed.json()[0]
    assert inv["status"] == "insufficient_evidence"
    assert inv["validation_errors"]
    detail = investigate_client.get(f"{INSIGHTS}/{insight_id}", headers=AUTH)
    assert detail.json()["insight"]["recommendation"] is None


def test_verdict_insufficient_evidence_does_not_write_insight_recommendation(
    investigate_client: TestClient, fake: FakeUpstream
) -> None:
    insight_id = _retry_insight_id(investigate_client)
    event_ids = _evidence_event_ids(investigate_client, insight_id)
    fake.enqueue_investigation(_insufficient_payload(evidence_ids=[event_ids[0]]))

    job_id = _investigate(investigate_client, insight_id)
    job = _wait_job(investigate_client, AUTH, job_id)
    assert job["status"] == "succeeded"

    listed = investigate_client.get(f"{INSIGHTS}/{insight_id}/investigations", headers=AUTH)
    inv = listed.json()[0]
    assert inv["status"] == "insufficient_evidence"
    detail = investigate_client.get(f"{INSIGHTS}/{insight_id}", headers=AUTH)
    insight = detail.json()["insight"]
    assert insight["recommendation"] is None
    assert insight["root_cause_hypothesis"] is None


def test_upstream_500_marks_failed_without_fake_result(
    investigate_client: TestClient, fake: FakeUpstream
) -> None:
    insight_id = _retry_insight_id(investigate_client)
    fake.enqueue(error(500, {"error": {"message": "upstream boom sk-abcdefghijklmnopqrstuv"}}))

    job_id = _investigate(investigate_client, insight_id)
    job = _wait_job(investigate_client, AUTH, job_id)
    assert job["status"] == "succeeded"

    listed = investigate_client.get(f"{INSIGHTS}/{insight_id}/investigations", headers=AUTH)
    inv = listed.json()[0]
    assert inv["status"] == "failed"
    assert inv["result"] is None
    assert inv["validation_errors"]
    assert "sk-abcdefghijklmnopqrstuv" not in json.dumps(inv)

    detail = investigate_client.get(f"{INSIGHTS}/{insight_id}", headers=AUTH)
    assert detail.json()["insight"]["recommendation"] is None


def test_missing_api_key_returns_503(tmp_path: Path, fake: FakeUpstream) -> None:
    settings = Settings(
        _env_file=None,
        local_token=SecretStr(LOCAL_TOKEN),
        db_path=tmp_path / "no-key.sqlite3",
        data_dir=tmp_path,
        upstream_base_url="https://fake.meta.test/v1",
        upstream_api_key=None,
    )
    app = create_app(settings, upstream_transport=fake.transport())
    with TestClient(app) as client:
        _seed_pair_and_chain(client, AUTH)
        job_id = _analyze(client, AUTH)
        _wait_job(client, AUTH, job_id)
        listed = client.get(INSIGHTS, headers=AUTH).json()["items"]
        insight_id = listed[0]["id"]

        response = client.post(
            f"{INSIGHTS}/{insight_id}/investigate",
            json={},
            headers=AUTH,
        )
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "upstream_not_configured"
    assert len(fake.requests) == 0


def test_feedback_recorded(investigate_client: TestClient, fake: FakeUpstream) -> None:
    insight_id = _retry_insight_id(investigate_client)
    event_ids = _evidence_event_ids(investigate_client, insight_id)
    fake.enqueue_investigation(_valid_payload(evidence_ids=[event_ids[0]]))
    job_id = _investigate(investigate_client, insight_id)
    _wait_job(investigate_client, AUTH, job_id)

    response = investigate_client.post(
        f"{INSIGHTS}/{insight_id}/feedback",
        json={"verdict": "useful", "implemented": True, "note": "Helped cut retries"},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["verdict"] == "useful"
    assert body["implemented"] is True
    assert body["note"] == "Helped cut retries"
    assert body["insight_id"] == insight_id


def test_investigate_does_not_hold_shared_lock(
    investigate_client: TestClient,
    investigate_app: FastAPI,
    fake: FakeUpstream,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    insight_id = _retry_insight_id(investigate_client)
    event_ids = _evidence_event_ids(investigate_client, insight_id)
    fake.enqueue_investigation(_valid_payload(evidence_ids=[event_ids[0]]))

    gate = threading.Event()
    entered = threading.Event()
    original = MetaClient.complete_structured

    def blocking(self: MetaClient, **kwargs: Any) -> Any:
        entered.set()
        assert gate.wait(timeout=5.0)
        return original(self, **kwargs)

    monkeypatch.setattr(MetaClient, "complete_structured", blocking)

    with investigate_app.state.db.write() as conn:
        job = JobRepository(conn).create(
            "investigate", {"insight_id": insight_id, "mode": "metadata_only"}
        )

    from tokenpilot.investigator.service import run_investigation_job

    thread = threading.Thread(
        target=run_investigation_job,
        args=(
            investigate_app.state.db,
            investigate_app.state.settings.db_path,
            investigate_app.state.settings,
            job.id,
        ),
        kwargs={"transport": investigate_app.state.upstream_transport},
    )
    thread.start()
    assert entered.wait(timeout=5.0)

    start = time.perf_counter()
    health = investigate_client.get("/api/v1/health", headers=AUTH)
    elapsed = time.perf_counter() - start
    assert health.status_code == 200
    assert elapsed < 1.0

    gate.set()
    thread.join(timeout=10.0)
    assert not thread.is_alive()
    with investigate_app.state.db.read() as conn:
        done = JobRepository(conn).get(job.id)
    assert done is not None
    assert done.status == "succeeded"
