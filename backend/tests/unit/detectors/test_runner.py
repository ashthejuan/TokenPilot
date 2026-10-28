"""The runner over a real database, seeded through the Phase 1 ingest pipeline."""

import itertools
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

import tokenpilot.pricing.catalog as catalog_module
from tokenpilot.db.connection import connect, transaction
from tokenpilot.db.database import Database
from tokenpilot.db.migrate import migrate
from tokenpilot.detectors.facts import AnalysisScope
from tokenpilot.detectors.runner import UnknownRuleError, run_detectors
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.ledger.ingest import ingest_event
from tokenpilot.pricing.catalog import load_catalog
from tokenpilot.schemas.common import Page
from tokenpilot.schemas.insights import InsightFilters, InsightOut
from tokenpilot.schemas.usage import UsageEvent, UsageEventIn

CATALOG_PATH = Path(catalog_module.__file__).parent / "catalog.yaml"
BASE = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 28, 13, 0, 0, tzinfo=UTC)

_ids = itertools.count(1)


@pytest.fixture
def live_db(tmp_path: Path) -> Iterator[tuple[Database, sqlite3.Connection]]:
    """A migrated database with prices, plus the runner's separate read connection."""
    path = tmp_path / "runner.sqlite3"
    setup = connect(path)
    migrate(setup)
    with transaction(setup):
        load_catalog(setup, CATALOG_PATH)
    setup.close()
    db = Database(path)
    read_conn = connect(path)
    yield db, read_conn
    read_conn.close()
    db.close()


def _ingest(db: Database, **overrides: Any) -> UsageEvent:
    values: dict[str, Any] = {
        "provider": "fake",
        "model_id": "fake-small",
        "started_at": BASE,
        "usage_source": "provider",
        "status": "success",
        "input_tokens": 1000,
        "output_tokens": 100,
        "source_event_id": f"src-{next(_ids)}",
    }
    values.update(overrides)
    with db.write() as conn:
        result = ingest_event(conn, UsageEventIn.model_validate(values), "api")
    assert result.created
    return result.event


def _seed_pair_and_chain(db: Database, **overrides: Any) -> None:
    """Two identical successes (A fires) plus a 3-attempt retry chain (B fires)."""
    _ingest(
        db,
        external_session_id="sess-a",
        request_fingerprint="fp-a",
        started_at=BASE,
        **overrides,
    )
    _ingest(
        db,
        external_session_id="sess-a",
        request_fingerprint="fp-a",
        started_at=BASE + timedelta(seconds=60),
        **overrides,
    )
    _ingest(
        db,
        external_session_id="sess-b",
        request_fingerprint="fp-b",
        status="error",
        error_category="rate_limited",
        source_event_id="ch-1",
        started_at=BASE,
        **overrides,
    )
    _ingest(
        db,
        external_session_id="sess-b",
        request_fingerprint="fp-b",
        status="error",
        error_category="rate_limited",
        source_event_id="ch-2",
        retry_of="ch-1",
        started_at=BASE + timedelta(seconds=10),
        **overrides,
    )
    _ingest(
        db,
        external_session_id="sess-b",
        request_fingerprint="fp-b",
        source_event_id="ch-3",
        retry_of="ch-2",
        started_at=BASE + timedelta(seconds=20),
        **overrides,
    )


def _list(db: Database) -> list[InsightOut]:
    with db.read() as conn:
        return InsightRepository(conn).list(InsightFilters(), Page(limit=200)).items


def test_rerun_does_not_duplicate_insights(live_db: tuple[Database, sqlite3.Connection]) -> None:
    db, read_conn = live_db
    _seed_pair_and_chain(db)

    first = run_detectors(read_conn, db, AnalysisScope(), None, NOW)
    assert (first.created, first.updated) == (2, 0)
    assert first.by_rule == {"repeated_request": 1, "retry_amplification": 1}
    before = {insight.id for insight in _list(db)}

    second = run_detectors(read_conn, db, AnalysisScope(), None, NOW)
    assert (second.created, second.updated) == (0, 2)
    assert {insight.id for insight in _list(db)} == before


def test_rerun_preserves_status_and_refreshes_evidence(
    live_db: tuple[Database, sqlite3.Connection],
) -> None:
    db, read_conn = live_db
    _ingest(
        db,
        external_session_id="sess-r",
        request_fingerprint="fp-r",
        status="error",
        error_category="rate_limited",
        source_event_id="r-1",
        started_at=BASE,
    )
    _ingest(
        db,
        external_session_id="sess-r",
        request_fingerprint="fp-r",
        status="error",
        error_category="rate_limited",
        source_event_id="r-2",
        retry_of="r-1",
        started_at=BASE + timedelta(seconds=10),
    )

    assert run_detectors(read_conn, db, AnalysisScope(), None, NOW).created == 1
    (insight,) = _list(db)
    with db.write() as conn:
        InsightRepository(conn).set_status(insight.id, "dismissed")

    _ingest(
        db,
        external_session_id="sess-r",
        request_fingerprint="fp-r",
        source_event_id="r-3",
        retry_of="r-2",
        started_at=BASE + timedelta(seconds=20),
    )
    rerun = run_detectors(read_conn, db, AnalysisScope(), None, NOW)

    assert (rerun.created, rerun.updated) == (0, 1)
    with db.read() as conn:
        refreshed = InsightRepository(conn).get(insight.id)
    assert refreshed is not None
    assert refreshed.status == "dismissed"
    assert len(refreshed.evidence) == 3
    assert refreshed.measurements["attempts"] == 3


def test_benchmark_events_ignored_by_all_detectors(
    live_db: tuple[Database, sqlite3.Connection],
) -> None:
    db, read_conn = live_db
    with db.write() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) "
            "VALUES ('p1', 'demo', '2026-10-28T12:00:00.000Z', '2026-10-28T12:00:00.000Z')"
        )
        conn.execute(
            "INSERT INTO benchmarks (id, project_id, name, created_at) "
            "VALUES ('b1', 'p1', 'bench', '2026-10-28T12:00:00.000Z')"
        )
        conn.execute(
            "INSERT INTO benchmark_runs (id, benchmark_id, variant_name, run_status) "
            "VALUES ('br1', 'b1', 'variant', 'completed')"
        )
    _seed_pair_and_chain(db, benchmark_run_id="br1")

    result = run_detectors(read_conn, db, AnalysisScope(), None, NOW)

    assert (result.created, result.updated) == (0, 0)
    assert result.by_rule == {}
    assert _list(db) == []


def test_evidence_capped_with_truncation_count(
    live_db: tuple[Database, sqlite3.Connection],
) -> None:
    db, read_conn = live_db
    first = _ingest(
        db,
        external_session_id="sess-storm",
        request_fingerprint="fp-storm",
        status="error",
        error_category="rate_limited",
        source_event_id="storm-0",
        started_at=BASE,
    )
    previous = "storm-0"
    for i in range(1, 60):
        _ingest(
            db,
            external_session_id="sess-storm",
            request_fingerprint="fp-storm",
            status="error" if i < 59 else "success",
            error_category="rate_limited" if i < 59 else None,
            source_event_id=f"storm-{i}",
            retry_of=previous,
            started_at=BASE + timedelta(seconds=i),
        )
        previous = f"storm-{i}"

    result = run_detectors(read_conn, db, AnalysisScope(), None, NOW)

    assert result.by_rule == {"retry_amplification": 1}
    (insight,) = _list(db)
    assert len(insight.evidence) == 50
    assert insight.evidence[0].id == first.id
    assert insight.evidence_truncated == 10
    assert insight.measurements["attempts"] == 60
    assert insight.measurements["retry_attempts"] == 59
    assert insight.severity == "low"


def test_unknown_rule_id_raises(live_db: tuple[Database, sqlite3.Connection]) -> None:
    db, read_conn = live_db
    _seed_pair_and_chain(db)

    with pytest.raises(UnknownRuleError):
        run_detectors(read_conn, db, AnalysisScope(), ["bogus"], NOW)

    assert _list(db) == []


def test_rule_subset_runs_only_selected(live_db: tuple[Database, sqlite3.Connection]) -> None:
    db, read_conn = live_db
    _seed_pair_and_chain(db)

    result = run_detectors(
        read_conn, db, AnalysisScope(), ["retry_amplification", "retry_amplification"], NOW
    )

    assert (result.created, result.updated) == (1, 0)
    assert result.by_rule == {"retry_amplification": 1}
