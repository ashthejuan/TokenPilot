import shutil
import sqlite3
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path

import pytest

from tokenpilot.db.connection import connect, transaction
from tokenpilot.db.migrate import migrate
from tokenpilot.insights.repository import InsightRepository

MIGRATIONS_DIR = Path(__file__).resolve().parents[2] / "tokenpilot" / "db" / "migrations"

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

    assert first == second == 3
    versions = [row["version"] for row in conn.execute("SELECT version FROM schema_migrations")]
    assert versions == [1, 2, 3]


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


def test_migration_0002_adds_phase1_columns(conn: sqlite3.Connection) -> None:
    assert migrate(conn) == 3

    assert "slug" in _columns(conn, "projects")
    assert "external_task_id" in _columns(conn, "tasks")
    assert "reason" in _columns(conn, "cost_records")
    assert "http_status" in _columns(conn, "usage_events")
    indexes = {
        row["name"]: row["sql"]
        for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'index'")
    }
    for name in (
        "idx_projects_slug",
        "idx_tasks_project_external",
        "idx_sessions_source_external",
        "idx_pricing_versions_unique",
    ):
        assert name in indexes
        assert indexes[name].startswith("CREATE UNIQUE INDEX")


def test_migration_0003_adds_insight_columns_and_tables(conn: sqlite3.Connection) -> None:
    assert migrate(conn) == 3

    assert {
        "rule_id",
        "rule_version",
        "dedupe_key",
        "measurements_json",
        "impact_currency",
        "evidence_truncated",
        "updated_at",
        "last_detected_at",
    } <= _columns(conn, "insights")
    assert _columns(conn, "jobs") == {
        "id",
        "kind",
        "status",
        "params_json",
        "result_json",
        "error",
        "created_at",
        "started_at",
        "finished_at",
    }
    assert _columns(conn, "app_settings") == {"key", "value_json", "updated_at"}

    indexes = {
        row["name"]: row["sql"]
        for row in conn.execute("SELECT name, sql FROM sqlite_master WHERE type = 'index'")
    }
    assert indexes["idx_insights_dedupe"].startswith("CREATE UNIQUE INDEX")
    assert {"idx_insights_session", "idx_insights_created"} <= set(indexes)

    # The dedupe key is unique, but any number of legacy NULL keys stay allowed.
    insert = (
        "INSERT INTO insights (id, detector_type, severity, title, summary, created_at, "
        "dedupe_key) VALUES (?, 'repeated_request', 'low', 't', 's', "
        "'2026-10-28T00:00:00.000Z', ?)"
    )
    conn.execute(insert, ("i1", "repeated_request.v1:s1:fp:-:e1"))
    conn.execute(insert, ("i2", None))
    conn.execute(insert, ("i3", None))
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(insert, ("i4", "repeated_request.v1:s1:fp:-:e1"))


def test_migration_0003_upgrades_legacy_insight_rows(
    conn: sqlite3.Connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Phase 1 row written before 0003 must stay readable, not raise on `get()`."""
    staged = tmp_path / "migrations"
    staged.mkdir()
    for name in ("0001_init.sql", "0002_phase1_ledger.sql"):
        shutil.copy(MIGRATIONS_DIR / name, staged / name)
    monkeypatch.setattr("tokenpilot.db.migrate.MIGRATIONS_DIR", staged)

    assert migrate(conn) == 2
    created_at = "2026-10-28T00:00:00.000Z"
    conn.execute(
        "INSERT INTO insights (id, detector_type, severity, title, summary, confidence, "
        "estimated_impact, evidence_json, created_at) "
        "VALUES ('legacy', 'retry_amplification', 'medium', 'Legacy', 'old row', NULL, 0.5, "
        "'[]', ?)",
        (created_at,),
    )

    shutil.copy(MIGRATIONS_DIR / "0003_phase2_insights.sql", staged / "0003_phase2_insights.sql")
    assert migrate(conn) == 3

    row = conn.execute(
        "SELECT rule_id, rule_version, updated_at, last_detected_at, measurements_json, "
        "evidence_truncated FROM insights WHERE id = 'legacy'"
    ).fetchone()
    assert row["rule_id"] == "retry_amplification"
    assert row["rule_version"] == 0
    assert row["updated_at"] == created_at
    assert row["last_detected_at"] == created_at
    assert row["measurements_json"] == "{}"
    assert row["evidence_truncated"] == 0

    insight = InsightRepository(conn).get("legacy")
    assert insight is not None
    assert insight.rule_id == "retry_amplification"
    assert insight.rule_version == 0
    assert insight.confidence is None
    assert insight.status == "new"
    assert insight.estimated_impact == Decimal("0.5")


def test_migration_0002_unique_constraints_enforced(conn: sqlite3.Connection) -> None:
    migrate(conn)
    now = "'2026-10-28T00:00:00Z'"
    conn.execute(
        "INSERT INTO projects (id, name, slug, created_at, updated_at) "
        f"VALUES ('p1', 'a', 'smoke', {now}, {now})"
    )
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO projects (id, name, slug, created_at, updated_at) "
            f"VALUES ('p2', 'b', 'smoke', {now}, {now})"
        )
    # Projects without a slug (NULL) must not collide with each other.
    for pid in ("p3", "p4"):
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) "
            f"VALUES ('{pid}', 'x', {now}, {now})"
        )
