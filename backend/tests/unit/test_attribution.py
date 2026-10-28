import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from tokenpilot.db.connection import connect
from tokenpilot.db.migrate import migrate
from tokenpilot.ledger.attribution import GatewayDefaults, resolve_attribution
from tokenpilot.ledger.ingest import ingest_event
from tokenpilot.ledger.normalize import normalize
from tokenpilot.ledger.refs import (
    ProjectRefError,
    get_or_create_session,
    resolve_project_ref,
    resolve_task_ref,
)
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.usage import UsageEvent, UsageEventIn


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "attribution.sqlite3")
    migrate(connection)
    yield connection
    connection.close()


def event_in(**overrides: Any) -> UsageEventIn:
    fields: dict[str, Any] = {
        "provider": "meta",
        "model_id": "muse-spark-1.3",
        "started_at": datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC),
        "usage_source": "provider",
        "status": "success",
    }
    fields.update(overrides)
    return UsageEventIn(**fields)


def ingest(
    conn: sqlite3.Connection,
    source: str = "api",
    defaults: GatewayDefaults | None = None,
    **overrides: Any,
) -> UsageEvent:
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = ingest_event(conn, event_in(**overrides), source, defaults)
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return result.event


def add_task(conn: sqlite3.Connection, project_id: str, task_id: str) -> None:
    conn.execute(
        "INSERT INTO tasks (id, project_id, title, created_at) VALUES (?, ?, ?, ?)",
        (task_id, project_id, task_id, "2026-10-28T00:00:00.000Z"),
    )


def count(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def test_explicit_task_beats_session_and_default(conn: sqlite3.Connection) -> None:
    task_project = resolve_project_ref(conn, "task-project")
    session_project = resolve_project_ref(conn, "session-project")
    resolve_project_ref(conn, "default-project")
    add_task(conn, task_project, "task-1")
    get_or_create_session(conn, "s1", "gateway", session_project)

    attribution = resolve_attribution(
        conn,
        normalize(event_in(task_id="task-1", external_session_id="s1"), "gateway"),
        "gateway",
        GatewayDefaults(project_ref="default-project"),
    )

    assert attribution.project_id == task_project
    assert attribution.task_id == "task-1"
    assert attribution.basis == "explicit_task"


@pytest.mark.parametrize(
    ("overrides", "defaults", "expected_basis", "expected_project"),
    [
        (
            {"project_id": "explicit", "external_session_id": "s1"},
            "dflt",
            "explicit_project",
            "explicit",
        ),
        ({"external_session_id": "s1"}, "dflt", "session", "sess"),
        ({}, "dflt", "gateway_default", "dflt"),
        ({}, None, "unattributed", None),
    ],
)
def test_precedence_order(
    conn: sqlite3.Connection,
    overrides: dict[str, Any],
    defaults: str | None,
    expected_basis: str,
    expected_project: str | None,
) -> None:
    ids = {name: resolve_project_ref(conn, name) for name in ("explicit", "sess", "dflt")}
    get_or_create_session(conn, "s1", "gateway", ids["sess"])

    attribution = resolve_attribution(
        conn,
        normalize(event_in(**overrides), "gateway"),
        "gateway",
        GatewayDefaults(project_ref=defaults) if defaults else None,
    )

    assert attribution.basis == expected_basis
    assert attribution.project_id == (ids[expected_project] if expected_project else None)


def test_no_metadata_stays_unattributed(conn: sqlite3.Connection) -> None:
    event = ingest(conn)

    assert (event.project_id, event.session_id, event.task_id) == (None, None, None)
    assert event.metadata["attribution_basis"] == "unattributed"
    assert count(conn, "projects") == 0


def test_prompt_text_never_used_for_project(conn: sqlite3.Connection) -> None:
    resolve_project_ref(conn, "alpha")

    event = ingest(
        conn,
        metadata={"note": "please work on project alpha", "project": "alpha", "title": "alpha"},
    )

    assert event.project_id is None
    assert event.metadata["attribution_basis"] == "unattributed"


def test_session_project_inherited(conn: sqlite3.Connection) -> None:
    first = ingest(conn, external_session_id="s1", project_id="p", source_event_id="a")
    second = ingest(conn, external_session_id="s1", source_event_id="b")

    assert second.project_id == first.project_id is not None
    assert second.session_id == first.session_id is not None
    assert second.metadata["attribution_basis"] == "session"
    assert count(conn, "sessions") == 1


def test_session_adopts_project_once_known(conn: sqlite3.Connection) -> None:
    first = ingest(conn, external_session_id="s1", source_event_id="a")
    second = ingest(conn, external_session_id="s1", project_id="p", source_event_id="b")
    third = ingest(conn, external_session_id="s1", source_event_id="c")

    assert first.project_id is None
    assert third.project_id == second.project_id is not None
    assert third.session_id == first.session_id


def test_sessions_are_keyed_on_source_and_external_id(conn: sqlite3.Connection) -> None:
    api = get_or_create_session(conn, "s1", "api", None)
    gateway = get_or_create_session(conn, "s1", "gateway", None)

    assert api != gateway
    assert get_or_create_session(conn, "s1", "api", None) == api


def test_session_started_at_is_earliest_event_and_fixed_ms(conn: sqlite3.Connection) -> None:
    session: dict[str, Any] = {"external_session_id": "s1"}
    ingest(conn, source_event_id="late", started_at="2026-10-27T10:05:00Z", **session)
    ingest(conn, source_event_id="early", started_at="2026-10-27T10:00:00Z", **session)

    row = conn.execute("SELECT started_at FROM sessions").fetchone()
    assert row["started_at"] == "2026-10-27T10:00:00.000Z"


def test_unknown_task_without_project_kept_in_metadata(conn: sqlite3.Connection) -> None:
    event = ingest(conn, task_id="T-9")

    assert event.task_id is None
    assert event.metadata["unresolved_task_ref"] == "T-9"
    assert count(conn, "tasks") == 0


def test_unknown_task_with_project_is_created_once(conn: sqlite3.Connection) -> None:
    first = ingest(conn, task_id="T-9", project_id="p", source_event_id="a")
    second = ingest(conn, task_id="T-9", project_id="p", source_event_id="b")

    assert first.task_id == second.task_id is not None
    assert first.metadata["attribution_basis"] == "explicit_task"
    row = conn.execute("SELECT title, external_task_id, project_id FROM tasks").fetchone()
    assert (row["title"], row["external_task_id"]) == ("T-9", "T-9")
    assert row["project_id"] == first.project_id
    assert count(conn, "tasks") == 1


def test_resolve_task_ref_by_internal_id_ignores_project(conn: sqlite3.Connection) -> None:
    project = resolve_project_ref(conn, "p")
    other = resolve_project_ref(conn, "q")
    add_task(conn, project, "task-1")

    assert resolve_task_ref(conn, "task-1", other) == "task-1"
    assert resolve_task_ref(conn, "missing", None) is None


def test_duplicate_event_has_no_side_effects(conn: sqlite3.Connection) -> None:
    kwargs: dict[str, Any] = {
        "source_event_id": "dup",
        "project_id": "p",
        "task_id": "T-1",
        "external_session_id": "s1",
    }
    first = ingest(conn, **kwargs)
    before = {t: count(conn, t) for t in ("projects", "tasks", "sessions", "usage_events")}

    # Same event again, but with a different project ref: nothing may be created.
    second = ingest(conn, **{**kwargs, "project_id": "another", "task_id": "T-2"})

    assert second.id == first.id
    assert {t: count(conn, t) for t in before} == before


def test_gateway_default_project_used_and_created(conn: sqlite3.Connection) -> None:
    event = ingest(conn, source="gateway", defaults=GatewayDefaults(project_ref="smoke"))

    assert event.metadata["attribution_basis"] == "gateway_default"
    project = LedgerRepository(conn).get_project(event.project_id or "")
    assert project is not None and project.slug == "smoke"


def test_gateway_invalid_default_ref_records_unattributed(conn: sqlite3.Connection) -> None:
    event = ingest(conn, source="gateway", defaults=GatewayDefaults(project_ref="Bad Ref!"))

    assert event.project_id is None
    assert event.metadata["attribution_basis"] == "unattributed"
    assert event.metadata["unresolved_project_ref"] == "Bad Ref!"


def test_api_invalid_project_ref_still_rejected(conn: sqlite3.Connection) -> None:
    with pytest.raises(ProjectRefError):
        ingest(conn, project_id="Bad Ref!")
