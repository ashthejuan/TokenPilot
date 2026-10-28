"""Insight, analysis-job and threshold storage (Task 2.0).

The insights JSON shapes are checked with `model_dump(mode="json")`, the exact
form FastAPI returns; Task 2.4 wires the routes that serve them.
"""

import sqlite3
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI, HTTPException
from fastapi.testclient import TestClient

from tokenpilot.config import Settings
from tokenpilot.db.connection import connect, transaction
from tokenpilot.db.database import Database, get_db
from tokenpilot.db.migrate import migrate
from tokenpilot.detectors.base import EvidenceRef, Finding, Scope
from tokenpilot.insights.jobs import JobRepository
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.main import create_app
from tokenpilot.schemas.common import InvalidCursorError, Page, Paged
from tokenpilot.schemas.insights import InsightFilters, InsightOut

PROJECT_ID = "p1"
NOW = "2026-10-28T10:00:00.000Z"


def make_finding(**overrides: Any) -> Finding:
    values: dict[str, Any] = {
        "rule_id": "repeated_request",
        "rule_version": 1,
        "anchor": "s1:fingerprint:task-:e1",
        "severity": "medium",
        "confidence": 0.9,
        "title": "Repeated identical request",
        "summary": "The same request succeeded twice in one minute.",
        "scope": Scope(project_id=PROJECT_ID, session_id="s1", task_id=None),
        "evidence": [EvidenceRef(kind="usage_event", id="e1", measurement={"cost": 0.11})],
        "measurements": {"repeats": 2},
        "estimated_impact": Decimal("0.2200000000"),
        "impact_currency": "USD",
    }
    values.update(overrides)
    return Finding(**values)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A migrated database with one project and two sessions to scope insights."""
    connection = connect(tmp_path / "insights.sqlite3")
    migrate(connection)
    with transaction(connection):
        connection.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, 'demo', ?, ?)",
            (PROJECT_ID, NOW, NOW),
        )
        for session_id in ("s1", "s2"):
            connection.execute(
                "INSERT INTO sessions (id, project_id, source, started_at) "
                "VALUES (?, ?, 'cli', ?)",
                (session_id, PROJECT_ID, NOW),
            )
    yield connection
    connection.close()


def _insert_job(path: Path, *, status: str) -> str:
    job_id = uuid.uuid4().hex
    connection = connect(path)
    try:
        connection.execute(
            "INSERT INTO jobs (id, kind, status, params_json, created_at) "
            "VALUES (?, 'analyze', ?, '{}', ?)",
            (job_id, status, NOW),
        )
    finally:
        connection.close()
    return job_id


def test_upsert_creates_then_updates_same_dedupe_key(conn: sqlite3.Connection) -> None:
    repository = InsightRepository(conn)

    assert repository.upsert(make_finding(), "2026-10-28T10:00:00.000Z") == "created"
    assert (
        repository.upsert(
            make_finding(title="Repeated identical request (3)", severity="high"),
            "2026-10-28T10:05:00.000Z",
        )
        == "updated"
    )

    rows = conn.execute(
        "SELECT id, dedupe_key, created_at, updated_at, last_detected_at, title, severity "
        "FROM insights"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["dedupe_key"] == "repeated_request.v1:s1:fingerprint:task-:e1"
    assert rows[0]["created_at"] == "2026-10-28T10:00:00.000Z"
    assert rows[0]["updated_at"] == "2026-10-28T10:05:00.000Z"
    assert rows[0]["last_detected_at"] == "2026-10-28T10:05:00.000Z"
    assert rows[0]["title"] == "Repeated identical request (3)"
    assert rows[0]["severity"] == "high"


def test_upsert_never_changes_status(conn: sqlite3.Connection) -> None:
    repository = InsightRepository(conn)
    repository.upsert(make_finding(), NOW)
    insight = repository.list(InsightFilters(), Page()).items[0]

    dismissed = repository.set_status(insight.id, "dismissed")
    assert dismissed is not None
    assert dismissed.status == "dismissed"

    assert repository.upsert(make_finding(summary="refreshed"), "2026-10-28T11:00:00.000Z") == (
        "updated"
    )
    again = repository.get(insight.id)
    assert again is not None
    assert again.status == "dismissed"
    assert again.summary == "refreshed"


def test_insight_money_round_trips(conn: sqlite3.Connection) -> None:
    repository = InsightRepository(conn)
    repository.upsert(make_finding(), NOW)
    repository.upsert(
        make_finding(
            anchor="no-cost",
            title="Unknown cost",
            estimated_impact=None,
            impact_currency=None,
        ),
        NOW,
    )

    items = repository.list(InsightFilters(), Page()).items
    priced = next(item for item in items if item.title == "Repeated identical request")
    unknown = next(item for item in items if item.title == "Unknown cost")

    assert isinstance(priced.estimated_impact, Decimal)
    assert priced.estimated_impact == Decimal("0.22")
    payload = priced.model_dump(mode="json")
    assert payload["estimated_impact"] == 0.22
    assert payload["impact_currency"] == "USD"
    assert '"estimated_impact":0.22' in priced.model_dump_json()

    unpriced = unknown.model_dump(mode="json")
    assert unpriced["estimated_impact"] is None
    assert unpriced["impact_currency"] is None


def _list_app(settings: Settings) -> FastAPI:
    """The Task 2.4 list route, mounted here only to pin the 422 contract.

    Task 2.0 ships no insights router; this proves the repository's
    `InvalidCursorError` becomes the project's standard validation error.
    """
    app = create_app(settings)

    @app.get("/api/v1/insights")
    def list_insights(
        db: Annotated[Database, Depends(get_db)], cursor: str | None = None
    ) -> Paged[InsightOut]:
        try:
            with db.read() as conn:
                return InsightRepository(conn).list(InsightFilters(), Page(cursor=cursor))
        except InvalidCursorError as exc:
            raise HTTPException(status_code=422, detail="invalid cursor") from exc

    return app


def test_list_insights_filters_and_paginates(
    conn: sqlite3.Connection, settings: Settings
) -> None:
    repository = InsightRepository(conn)
    for anchor, session_id, title, now in (
        ("a", "s1", "one", "2026-10-28T10:00:00.000Z"),
        ("b", "s1", "two", "2026-10-28T10:01:00.000Z"),
        ("c", "s2", "three", "2026-10-28T10:02:00.000Z"),
    ):
        repository.upsert(
            make_finding(
                anchor=anchor,
                title=title,
                scope=Scope(project_id=PROJECT_ID, session_id=session_id, task_id=None),
            ),
            now,
        )
    ids = {item.title: item.id for item in repository.list(InsightFilters(), Page()).items}

    assert len(repository.list(InsightFilters(session_id="s1"), Page()).items) == 2

    walked: list[str] = []
    cursor: str | None = None
    while True:
        page = repository.list(InsightFilters(), Page(limit=1, cursor=cursor))
        walked.extend(item.id for item in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor
    assert walked == [ids["three"], ids["two"], ids["one"]]

    with pytest.raises(InvalidCursorError):
        repository.list(InsightFilters(), Page(cursor="not-a-cursor"))
    with TestClient(_list_app(settings)) as client:
        response = client.get("/api/v1/insights", params={"cursor": "not-a-cursor"})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"


def test_job_cannot_skip_start(conn: sqlite3.Connection) -> None:
    repository = JobRepository(conn)
    job = repository.create("analyze", {})

    assert repository.succeed(job.id, {"created": 1}) is None
    assert repository.fail(job.id, "boom") is None

    stored = repository.get(job.id)
    assert stored is not None
    assert stored.status == "queued"
    assert stored.started_at is None
    assert stored.result is None
    assert stored.error is None


def test_job_cannot_restart_after_finish(conn: sqlite3.Connection) -> None:
    repository = JobRepository(conn)
    job = repository.create("analyze", {})
    running = repository.start(job.id)
    assert running is not None
    assert repository.succeed(job.id, {}) is not None

    assert repository.start(job.id) is None
    assert repository.fail(job.id, "too late") is None

    stored = repository.get(job.id)
    assert stored is not None
    assert stored.status == "succeeded"


def test_upsert_rejects_unpaired_money(conn: sqlite3.Connection) -> None:
    repository = InsightRepository(conn)

    with pytest.raises(ValueError):
        repository.upsert(make_finding(impact_currency=None), NOW)
    with pytest.raises(ValueError):
        repository.upsert(make_finding(estimated_impact=None), NOW)

    assert conn.execute("SELECT COUNT(*) AS n FROM insights").fetchone()["n"] == 0
    repository.upsert(make_finding(), NOW)
    repository.upsert(
        make_finding(anchor="none", estimated_impact=None, impact_currency=None), NOW
    )
    assert conn.execute("SELECT COUNT(*) AS n FROM insights").fetchone()["n"] == 2


def test_list_insights_tie_breaks_on_id(conn: sqlite3.Connection) -> None:
    repository = InsightRepository(conn)
    same_now = "2026-10-28T10:00:00.000Z"
    for anchor in ("a", "b"):
        repository.upsert(make_finding(anchor=anchor, title=anchor), same_now)
    ids = sorted(
        (item.id for item in repository.list(InsightFilters(), Page()).items), reverse=True
    )

    walked: list[str] = []
    cursor: str | None = None
    while True:
        page = repository.list(InsightFilters(), Page(limit=1, cursor=cursor))
        walked.extend(item.id for item in page.items)
        if page.next_cursor is None:
            break
        cursor = page.next_cursor

    assert walked == ids
    assert len(set(walked)) == 2


def test_job_lifecycle(conn: sqlite3.Connection) -> None:
    repository = JobRepository(conn)

    job = repository.create("analyze", {"session_id": "s1"})
    assert job.status == "queued"
    assert job.params == {"session_id": "s1"}
    assert (job.started_at, job.result, job.error) == (None, None, None)

    running = repository.start(job.id)
    assert running is not None
    assert running.status == "running"
    assert running.started_at is not None

    done = repository.succeed(job.id, {"created": 2, "updated": 1})
    assert done is not None
    assert done.status == "succeeded"
    assert done.result == {"created": 2, "updated": 1}
    assert done.finished_at is not None

    doomed = repository.create("analyze", {})
    assert repository.start(doomed.id) is not None
    repository.fail(doomed.id, "RuntimeError: Bearer sk-abcdefghijklmnopqrstuv")
    failed = repository.get(doomed.id)
    assert failed is not None
    assert failed.status == "failed"
    assert failed.error is not None
    assert "RuntimeError" in failed.error
    assert "sk-abcdefghijklmnopqrstuv" not in failed.error
    assert failed.finished_at is not None


def test_interrupted_jobs_failed_on_startup(settings: Settings) -> None:
    # First start migrates; then a job is left `running` as if the process died.
    with TestClient(create_app(settings)):
        pass
    job_id = _insert_job(settings.db_path, status="running")

    with TestClient(create_app(settings)):
        pass

    connection = connect(settings.db_path)
    try:
        row = connection.execute(
            "SELECT status, error, finished_at FROM jobs WHERE id = ?", (job_id,)
        ).fetchone()
    finally:
        connection.close()
    assert row["status"] == "failed"
    assert row["error"] == "interrupted by restart"
    assert row["finished_at"] is not None


def test_recover_interrupted_only_touches_unfinished_jobs(conn: sqlite3.Connection) -> None:
    repository = JobRepository(conn)
    queued = repository.create("analyze", {})
    running = repository.create("analyze", {})
    repository.start(running.id)
    finished = repository.create("analyze", {})
    assert repository.start(finished.id) is not None
    repository.succeed(finished.id, {})

    assert repository.recover_interrupted() == 2
    for job in (queued, running):
        stored = repository.get(job.id)
        assert stored is not None
        assert stored.status == "failed"
    finished_job = repository.get(finished.id)
    assert finished_job is not None
    assert finished_job.status == "succeeded"
    assert repository.recover_interrupted() == 0
