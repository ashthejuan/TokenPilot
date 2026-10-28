import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from tokenpilot.db.connection import connect
from tokenpilot.db.migrate import migrate
from tokenpilot.ledger.ingest import ingest_event
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.usage import UsageEvent, UsageEventIn

BASE = datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "retry.sqlite3")
    migrate(connection)
    yield connection
    connection.close()


def ingest(conn: sqlite3.Connection, offset_s: float = 0, **overrides: Any) -> UsageEvent:
    fields: dict[str, Any] = {
        "provider": "meta",
        "model_id": "muse-spark-1.3",
        "started_at": BASE + timedelta(seconds=offset_s),
        "usage_source": "provider",
        "status": "success",
    }
    fields.update(overrides)
    conn.execute("BEGIN IMMEDIATE")
    try:
        result = ingest_event(conn, UsageEventIn(**fields), "api")
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")
    return reload(conn, result.event.id)


def reload(conn: sqlite3.Connection, event_id: str) -> UsageEvent:
    event = LedgerRepository(conn).get_event(event_id)
    assert event is not None
    return event


def test_explicit_retry_of_groups_events(conn: sqlite3.Connection) -> None:
    first = ingest(conn, 0, source_event_id="r1", status="error")
    second = ingest(conn, 5, source_event_id="r2", status="error", retry_of="r1")
    third = ingest(conn, 10, source_event_id="r3", retry_of=second.id)

    first, second, third = (reload(conn, e.id) for e in (first, second, third))

    assert first.retry_group_id is not None
    assert first.retry_group_id == second.retry_group_id == third.retry_group_id
    assert [first.attempt, second.attempt, third.attempt] == [1, 2, 3]
    assert {first.retry_source, second.retry_source, third.retry_source} == {"explicit"}


def test_unknown_retry_of_leaves_event_ungrouped(conn: sqlite3.Connection) -> None:
    event = ingest(conn, 0, retry_of="does-not-exist")

    assert (event.retry_group_id, event.retry_source, event.attempt) == (None, None, None)


@pytest.mark.parametrize(
    ("first_status", "gap_s", "expect_group"),
    [
        ("success", 60, False),
        ("error", 60, True),
        ("timeout", 120, True),
        ("error", 121, False),
    ],
)
def test_inferred_retry_requires_prior_failure(
    conn: sqlite3.Connection, first_status: str, gap_s: int, expect_group: bool
) -> None:
    first = ingest(
        conn, 0, status=first_status, external_session_id="s1", request_fingerprint="fp"
    )
    second = ingest(conn, gap_s, external_session_id="s1", request_fingerprint="fp")

    first, second = reload(conn, first.id), reload(conn, second.id)

    if expect_group:
        assert second.retry_source == "inferred"
        assert first.retry_group_id == second.retry_group_id is not None
        assert (first.attempt, second.attempt) == (1, 2)
        assert first.retry_source == "inferred"
    else:
        assert (first.retry_group_id, second.retry_group_id) == (None, None)
        assert second.retry_source is None


def test_inference_needs_session_and_matching_fingerprint(conn: sqlite3.Connection) -> None:
    no_session = [ingest(conn, i, status="error", request_fingerprint="fp") for i in (0, 10)]
    other_fp = [
        ingest(conn, 0, status="error", external_session_id="s2", request_fingerprint="a"),
        ingest(conn, 10, external_session_id="s2", request_fingerprint="b"),
    ]
    no_fp = [
        ingest(conn, 0, status="error", external_session_id="s3"),
        ingest(conn, 10, external_session_id="s3"),
    ]

    for e in (*no_session, *other_fp, *no_fp):
        assert reload(conn, e.id).retry_group_id is None


def test_inferred_chain_extends_one_group(conn: sqlite3.Connection) -> None:
    kwargs: dict[str, Any] = {"external_session_id": "s1", "request_fingerprint": "fp"}
    a = ingest(conn, 0, status="error", **kwargs)
    b = ingest(conn, 30, status="timeout", **kwargs)
    c = ingest(conn, 60, **kwargs)

    a, b, c = (reload(conn, e.id) for e in (a, b, c))

    assert a.retry_group_id == b.retry_group_id == c.retry_group_id is not None
    assert [a.attempt, b.attempt, c.attempt] == [1, 2, 3]
