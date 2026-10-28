import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tokenpilot.db.connection import connect, transaction
from tokenpilot.db.migrate import migrate

PRD_TABLES = {
    "projects",
    "sessions",
    "tasks",
    "usage_events",
    "pricing_versions",
    "cost_records",
    "insights",
    "benchmarks",
    "benchmark_runs",
    "benchmark_comparisons",
    "attribution_changes",
    "content_excerpts",
    "investigations",
    "recommendation_feedback",
    "schema_migrations",
}


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "tokenpilot.sqlite3")
    yield connection
    connection.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_migrate_is_idempotent(conn: sqlite3.Connection) -> None:
    first = migrate(conn)
    second = migrate(conn)

    assert first == second == 1
    versions = [row["version"] for row in conn.execute("SELECT version FROM schema_migrations")]
    assert versions == [1]


def test_foreign_keys_enforced(conn: sqlite3.Connection) -> None:
    migrate(conn)

    with pytest.raises(sqlite3.IntegrityError), transaction(conn):
        conn.execute(
            "INSERT INTO cost_records "
            "(id, usage_event_id, currency, cost_basis, calculated_at) "
            "VALUES ('cr1', 'does-not-exist', 'USD', 'estimated', '2026-10-28T00:00:00Z')"
        )


def test_idempotency_key_unique(conn: sqlite3.Connection) -> None:
    migrate(conn)
    insert = (
        "INSERT INTO usage_events "
        "(id, idempotency_key, provider, model_id, usage_source, status, started_at) "
        "VALUES (?, 'dup-key', 'meta', 'muse-spark-1.3', 'provider', 'success', "
        "'2026-10-28T00:00:00Z')"
    )

    conn.execute(insert, ("event-1",))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("event-2",))


def test_transaction_rolls_back_on_error(conn: sqlite3.Connection) -> None:
    migrate(conn)

    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute(
            "INSERT INTO projects (id, name, default_currency, created_at, updated_at) "
            "VALUES ('p1', 'rolled-back', 'USD', '2026-10-28T00:00:00Z', "
            "'2026-10-28T00:00:00Z')"
        )
        raise RuntimeError("boom")

    assert conn.execute("SELECT COUNT(*) AS n FROM projects").fetchone()["n"] == 0


def test_all_tables_and_phase_additions_exist(conn: sqlite3.Connection) -> None:
    migrate(conn)
    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }

    assert tables >= PRD_TABLES
    assert {
        "retry_source",
        "attempt",
        "error_category",
        "benchmark_run_id",
        "raw_event_json",
    } <= _columns(conn, "usage_events")
    assert {
        "description",
        "task_spec_json",
        "alternative_configs_json",
        "repeat_count",
        "timeout_s",
        "insight_id",
    } <= _columns(conn, "benchmarks")
    assert {"repeat_index", "error", "eligible"} <= _columns(conn, "benchmark_runs")


def test_key_indexes_exist(conn: sqlite3.Connection) -> None:
    migrate(conn)
    indexes = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'index'")
    }

    assert {
        "idx_usage_events_idempotency_key",
        "idx_usage_events_project_started",
        "idx_usage_events_session_started",
        "idx_usage_events_model",
        "idx_usage_events_retry_group",
        "idx_usage_events_fingerprint",
        "idx_cost_records_event_calculated",
    } <= indexes
