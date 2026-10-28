"""Analysis latency over a 100k-event ledger (Task 2.4). Run with `pytest -m perf`."""

import platform
import sqlite3
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import tokenpilot.pricing.catalog as catalog_module
from tokenpilot.db.connection import connect, transaction
from tokenpilot.db.database import Database
from tokenpilot.db.migrate import migrate
from tokenpilot.detectors.facts import AnalysisScope
from tokenpilot.detectors.runner import run_detectors
from tokenpilot.pricing.catalog import load_catalog
from tokenpilot.timeutil import to_utc_z

CATALOG_PATH = Path(catalog_module.__file__).parent / "catalog.yaml"
EVENTS = 100_000
SESSIONS = 500
BASE = datetime(2026, 10, 1, tzinfo=UTC)
NOW = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)


@pytest.fixture
def seeded(tmp_path: Path) -> Iterator[tuple[Database, sqlite3.Connection, Path]]:
    path = tmp_path / "insights-perf.sqlite3"
    conn = connect(path)
    migrate(conn)
    with transaction(conn):
        load_catalog(conn, CATALOG_PATH)
        version_id = conn.execute(
            "SELECT id FROM pricing_versions WHERE provider = 'fake' AND model_id = 'fake-small'"
        ).fetchone()[0]
        now = to_utc_z(datetime.now(UTC))
        conn.execute(
            "INSERT INTO projects (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
            ("p0", "perf", "perf", now, now),
        )
        conn.executemany(
            "INSERT INTO sessions (id, project_id, source, started_at) VALUES (?, ?, 'api', ?)",
            [(f"s{i}", "p0", to_utc_z(BASE)) for i in range(SESSIONS)],
        )
        events = []
        costs = []
        for i in range(EVENTS):
            started = to_utc_z(BASE + timedelta(seconds=i))
            events.append(
                (
                    f"e{i}",
                    f"k{i}",
                    "p0",
                    f"s{i % SESSIONS}",
                    "fake",
                    "fake-small",
                    1_000,
                    200,
                    "provider",
                    "success",
                    50,
                    1,
                    started,
                )
            )
            costs.append((f"c{i}", f"e{i}", version_id, 0.0005, "USD", "estimated", started))
        conn.executemany(
            "INSERT INTO usage_events (id, idempotency_key, project_id, session_id, provider, "
            "model_id, input_tokens, output_tokens, usage_source, status, latency_ms, attempt, "
            "started_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            events,
        )
        conn.executemany(
            "INSERT INTO cost_records (id, usage_event_id, pricing_version_id, estimated_cost, "
            "currency, cost_basis, calculated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            costs,
        )
    conn.execute("ANALYZE")
    conn.close()
    db = Database(path)
    read_conn = connect(path)
    yield db, read_conn, path
    read_conn.close()
    db.close()


@pytest.mark.perf
def test_analyze_100k_events_perf(
    seeded: tuple[Database, sqlite3.Connection, Path],
) -> None:
    """Analysis of all rules over 100k events / 500 sessions finishes in < 10 s."""
    db, read_conn, _path = seeded
    run_detectors(read_conn, db, AnalysisScope(), None, NOW)  # warm caches
    start = time.perf_counter()
    result = run_detectors(read_conn, db, AnalysisScope(), None, NOW)
    elapsed = time.perf_counter() - start
    machine = f"{platform.system()} {platform.machine()} / {platform.processor()}"
    print(
        f"analyze 100k events / {SESSIONS} sessions: {elapsed:.3f}s "
        f"(created={result.created} updated={result.updated}) on {machine}"
    )
    assert elapsed < 10.0
