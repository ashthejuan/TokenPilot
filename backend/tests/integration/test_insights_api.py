"""Insights analyze jobs, list/detail with evidence, and status PATCH (Task 2.4)."""

import threading
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tokenpilot.detectors.base import EvidenceRef, Finding, Scope
from tokenpilot.detectors.runner import REGISTRY
from tokenpilot.insights.jobs import JobRepository
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.schemas.common import Page
from tokenpilot.schemas.insights import InsightFilters
from tokenpilot.timeutil import to_utc_z

EVENTS = "/api/v1/usage/events"
ANALYZE = "/api/v1/insights/analyze"
INSIGHTS = "/api/v1/insights"
JOBS = "/api/v1/jobs"
SESSIONS = "/api/v1/sessions"
BASE = datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)


def _event(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "provider": "fake",
        "model_id": "fake-small",
        "started_at": to_utc_z(BASE),
        "usage_source": "provider",
        "status": "success",
        "input_tokens": 1000,
        "output_tokens": 100,
    }
    body.update(overrides)
    return body


def _post_events(client: TestClient, headers: dict[str, str], *events: dict[str, Any]) -> None:
    response = client.post(EVENTS, json=list(events), headers=headers)
    assert response.status_code == 201, response.text


def _analyze(
    client: TestClient, headers: dict[str, str], body: dict[str, Any] | None = None
) -> str:
    response = client.post(ANALYZE, json=body or {}, headers=headers)
    assert response.status_code == 202, response.text
    return str(response.json()["job_id"])


def _wait_job(client: TestClient, headers: dict[str, str], job_id: str) -> dict[str, Any]:
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline:
        response = client.get(f"{JOBS}/{job_id}", headers=headers)
        assert response.status_code == 200, response.text
        job = response.json()
        if job["status"] in ("succeeded", "failed"):
            return job
        time.sleep(0.05)
    raise AssertionError(f"job {job_id} did not finish")


def _seed_pair_and_chain(client: TestClient, headers: dict[str, str]) -> None:
    """Two identical successes (A) plus a 3-attempt retry chain (B), provider fake."""
    _post_events(
        client,
        headers,
        _event(
            external_session_id="s1",
            request_fingerprint="fp-a",
            source_event_id="a-1",
            started_at=to_utc_z(BASE),
        ),
        _event(
            external_session_id="s1",
            request_fingerprint="fp-a",
            source_event_id="a-2",
            started_at=to_utc_z(BASE + timedelta(seconds=60)),
        ),
        _event(
            external_session_id="s1-retry",
            request_fingerprint="fp-b",
            status="error",
            error_category="rate_limited",
            source_event_id="ch-1",
            started_at=to_utc_z(BASE),
        ),
        _event(
            external_session_id="s1-retry",
            request_fingerprint="fp-b",
            status="error",
            error_category="rate_limited",
            source_event_id="ch-2",
            retry_of="ch-1",
            started_at=to_utc_z(BASE + timedelta(seconds=10)),
        ),
        _event(
            external_session_id="s1-retry",
            request_fingerprint="fp-b",
            source_event_id="ch-3",
            retry_of="ch-2",
            started_at=to_utc_z(BASE + timedelta(seconds=20)),
        ),
    )


def _seed_rules_a_through_f(client: TestClient, headers: dict[str, str]) -> None:
    """Seed scenarios that fire A, B, C, D, E, and F via the usage API."""
    _seed_pair_and_chain(client, headers)

    block = {"hash": "abc123", "chars": 8000, "approx_tokens": 2000}
    _post_events(
        client,
        headers,
        *[
            _event(
                external_session_id="sess-c",
                source_event_id=f"c-{i}",
                started_at=to_utc_z(BASE + timedelta(seconds=i)),
                metadata={"context_blocks": [block]},
            )
            for i in range(3)
        ],
    )

    # D: expensive abandoned session (fake-large tokens → > $0.50).
    _post_events(
        client,
        headers,
        _event(
            external_session_id="sess-d",
            model_id="fake-large",
            source_event_id="d-1",
            input_tokens=200_000,
            output_tokens=1_000,
            started_at=to_utc_z(BASE),
        ),
        _event(
            external_session_id="sess-d",
            model_id="fake-large",
            source_event_id="d-2",
            input_tokens=200_000,
            output_tokens=1_000,
            started_at=to_utc_z(BASE + timedelta(seconds=30)),
        ),
    )
    sessions = client.get(SESSIONS, headers=headers).json()["items"]
    sess_d = next(s for s in sessions if s["external_session_id"] == "sess-d")
    patched = client.patch(
        f"{SESSIONS}/{sess_d['id']}", json={"outcome": "abandoned"}, headers=headers
    )
    assert patched.status_code == 200, patched.text

    # E: high input/output ratio.
    _post_events(
        client,
        headers,
        _event(
            external_session_id="sess-e",
            source_event_id="e-1",
            input_tokens=30_000,
            output_tokens=100,
            started_at=to_utc_z(BASE),
        ),
    )

    # F: 41 requests, activity well past the open-session grace window.
    past = BASE - timedelta(hours=3)
    _post_events(
        client,
        headers,
        *[
            _event(
                external_session_id="sess-f",
                source_event_id=f"f-{i}",
                started_at=to_utc_z(past + timedelta(minutes=i)),
            )
            for i in range(41)
        ],
    )


def test_analyze_returns_202_and_job_succeeds(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _seed_pair_and_chain(client, auth_headers)

    job_id = _analyze(client, auth_headers)
    job = _wait_job(client, auth_headers, job_id)

    assert job["status"] == "succeeded"
    assert job["result"]["by_rule"]["retry_amplification"] == 1
    assert job["result"]["by_rule"]["repeated_request"] == 1


def test_every_finding_evidence_resolves(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _seed_rules_a_through_f(client, auth_headers)
    job = _wait_job(client, auth_headers, _analyze(client, auth_headers))
    assert job["status"] == "succeeded"

    by_rule = job["result"]["by_rule"]
    for rule_id in (
        "repeated_request",
        "retry_amplification",
        "repeated_context",
        "unsuccessful_task",
        "context_ratio",
        "runaway_session",
    ):
        assert by_rule.get(rule_id, 0) >= 1, f"{rule_id} did not fire: {by_rule}"

    insights = client.get(INSIGHTS, params={"limit": 200}, headers=auth_headers).json()["items"]
    assert insights
    for insight in insights:
        detail = client.get(f"{INSIGHTS}/{insight['id']}", headers=auth_headers)
        assert detail.status_code == 200, detail.text
        body = detail.json()
        rows = body["evidence_rows"]
        assert len(rows) == len(body["insight"]["evidence"]) >= 1
        for row in rows:
            assert row["resolved"] is True
            if row["ref"]["kind"] == "usage_event":
                assert row["event"]["id"] == row["ref"]["id"]


def test_unresolvable_evidence_marked_not_resolved(
    client: TestClient, app: FastAPI, auth_headers: dict[str, str]
) -> None:
    now = to_utc_z(BASE)
    finding = Finding(
        rule_id="repeated_request",
        rule_version=1,
        anchor="missing",
        severity="low",
        confidence=0.5,
        title="orphan",
        summary="missing event evidence",
        scope=Scope(),
        evidence=[EvidenceRef(kind="usage_event", id="does-not-exist", measurement={})],
        measurements={},
        estimated_impact=None,
        impact_currency=None,
    )
    with app.state.db.write() as conn:
        repository = InsightRepository(conn)
        repository.upsert(finding, now)
        insight_id = repository.list(InsightFilters(), Page(limit=1)).items[0].id

    response = client.get(f"{INSIGHTS}/{insight_id}", headers=auth_headers)
    assert response.status_code == 200
    rows = response.json()["evidence_rows"]
    assert len(rows) == 1
    assert rows[0]["resolved"] is False
    assert rows[0]["event"] is None


def test_analyze_scoped_to_session(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _seed_pair_and_chain(client, auth_headers)
    sessions = {
        item["external_session_id"]: item["id"]
        for item in client.get(SESSIONS, headers=auth_headers).json()["items"]
    }
    session_id = sessions["s1"]

    job = _wait_job(
        client, auth_headers, _analyze(client, auth_headers, {"session_id": session_id})
    )
    assert job["status"] == "succeeded"
    assert job["result"]["by_rule"].get("repeated_request") == 1
    assert "retry_amplification" not in job["result"]["by_rule"]

    insights = client.get(
        INSIGHTS, params={"session_id": session_id}, headers=auth_headers
    ).json()["items"]
    assert insights
    assert all(item["session_id"] == session_id for item in insights)


def test_analyze_unknown_rule_422(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        ANALYZE, json={"rule_ids": ["not_a_real_rule"]}, headers=auth_headers
    )
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_patch_status_and_tested_not_settable(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _seed_pair_and_chain(client, auth_headers)
    _wait_job(client, auth_headers, _analyze(client, auth_headers))
    insight_id = client.get(INSIGHTS, headers=auth_headers).json()["items"][0]["id"]

    reviewed = client.patch(
        f"{INSIGHTS}/{insight_id}", json={"status": "reviewed"}, headers=auth_headers
    )
    assert reviewed.status_code == 200
    assert reviewed.json()["status"] == "reviewed"

    tested = client.patch(
        f"{INSIGHTS}/{insight_id}", json={"status": "tested"}, headers=auth_headers
    )
    assert tested.status_code == 422
    assert tested.json()["error"]["code"] == "status_not_settable"

    missing = client.patch(
        f"{INSIGHTS}/does-not-exist", json={"status": "reviewed"}, headers=auth_headers
    )
    assert missing.status_code == 404


def test_failed_job_records_redacted_error(
    client: TestClient,
    app: FastAPI,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = REGISTRY["repeated_request"]

    class Boom:
        rule_id = original.rule_id
        rule_version = original.rule_version
        guidance = original.guidance

        def detect(self, ctx: Any) -> list[Any]:
            raise RuntimeError("Bearer sk-abcdefghijklmnopqrstuv")

    monkeypatch.setitem(REGISTRY, "repeated_request", Boom())
    _seed_pair_and_chain(client, auth_headers)

    job = _wait_job(client, auth_headers, _analyze(client, auth_headers))
    assert job["status"] == "failed"
    assert job["error"] is not None
    assert "RuntimeError" in job["error"]
    assert "sk-abcdefghijklmnopqrstuv" not in job["error"]


def test_analysis_does_not_hold_shared_lock(
    client: TestClient,
    app: FastAPI,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gate = threading.Event()
    entered = threading.Event()
    original = REGISTRY["repeated_request"]

    class Blocking:
        rule_id = original.rule_id
        rule_version = original.rule_version
        guidance = original.guidance

        def detect(self, ctx: Any) -> list[Any]:
            entered.set()
            assert gate.wait(timeout=5.0)
            return original.detect(ctx)

    from tokenpilot.insights.jobs import run_analysis_job
    from tokenpilot.schemas.insights import AnalyzeRequest

    monkeypatch.setitem(REGISTRY, "repeated_request", Blocking())
    _seed_pair_and_chain(client, auth_headers)

    with app.state.db.write() as conn:
        job = JobRepository(conn).create("analyze", {})
    req = AnalyzeRequest()
    thread = threading.Thread(
        target=run_analysis_job,
        args=(app.state.db, app.state.settings.db_path, job.id, req),
    )
    thread.start()
    assert entered.wait(timeout=5.0)

    start = time.perf_counter()
    health = client.get("/api/v1/health", headers=auth_headers)
    elapsed = time.perf_counter() - start
    assert health.status_code == 200
    assert elapsed < 1.0

    gate.set()
    thread.join(timeout=10.0)
    assert not thread.is_alive()
    with app.state.db.read() as conn:
        done = JobRepository(conn).get(job.id)
    assert done is not None
    assert done.status == "succeeded"
