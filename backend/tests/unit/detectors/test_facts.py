"""The fact loader: metadata parsing and scope filtering over a real database."""

import itertools
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

import tokenpilot.pricing.catalog as catalog_module
from tokenpilot.db.connection import connect, transaction
from tokenpilot.db.database import Database
from tokenpilot.db.migrate import migrate
from tokenpilot.detectors.facts import (
    AnalysisScope,
    ContextBlockFact,
    load_context,
)
from tokenpilot.detectors.thresholds import Thresholds
from tokenpilot.ledger.ingest import ingest_event
from tokenpilot.pricing.catalog import load_catalog
from tokenpilot.schemas.usage import UsageEvent, UsageEventIn

CATALOG_PATH = Path(catalog_module.__file__).parent / "catalog.yaml"
BASE = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
NOW = datetime(2026, 10, 28, 13, 0, 0, tzinfo=UTC)

_ids = itertools.count(1)


@pytest.fixture
def db(tmp_path: Path) -> Iterator[Database]:
    path = tmp_path / "facts.sqlite3"
    setup = connect(path)
    migrate(setup)
    with transaction(setup):
        load_catalog(setup, CATALOG_PATH)
    setup.close()
    database = Database(path)
    yield database
    database.close()


def _ingest(db: Database, **overrides: Any) -> UsageEvent:
    values: dict[str, Any] = {
        "provider": "fake",
        "model_id": "fake-small",
        "started_at": BASE,
        "usage_source": "provider",
        "status": "success",
        "input_tokens": 1000,
        "output_tokens": 100,
        "source_event_id": f"fact-{next(_ids)}",
    }
    values.update(overrides)
    with db.write() as conn:
        result = ingest_event(conn, UsageEventIn.model_validate(values), "api")
    assert result.created
    return result.event


def test_metadata_parsing_reads_two_keys_and_skips_malformed_blocks(db: Database) -> None:
    _ingest(
        db,
        external_session_id="sess-m",
        metadata={
            "intentional_repeat": True,
            "context_blocks": [
                {"hash": "h1", "chars": 8000, "approx_tokens": 2000},
                {"hash": "bad-chars", "chars": "8k", "approx_tokens": 1},
                {"hash": "missing-counts"},
                {"hash": "", "chars": 1, "approx_tokens": 1},
                {"hash": "negative", "chars": -5, "approx_tokens": 1},
                {"hash": "bool-count", "chars": True, "approx_tokens": 1},
                "not-a-block",
            ],
            "unrelated": "ignored",
        },
    )

    with db.read() as conn:
        context = load_context(conn, AnalysisScope(), Thresholds(), NOW)

    assert len(context.events) == 1
    assert context.events[0].intentional_repeat is True
    assert context.events[0].context_blocks == (
        ContextBlockFact(hash="h1", chars=8000, approx_tokens=2000),
    )


def test_oversized_forged_context_blocks_skipped_at_parse(db: Database) -> None:
    """Non-physical client sizes must not enter DetectionContext (D-2 Important #2)."""
    _ingest(
        db,
        external_session_id="sess-forge",
        metadata={
            "context_blocks": [
                {"hash": "forged-chars", "chars": 10**12, "approx_tokens": 2000},
                {"hash": "forged-tokens", "chars": 8000, "approx_tokens": 10**12},
                {"hash": "ok", "chars": 8000, "approx_tokens": 2000},
                {
                    "hash": "at-cap",
                    "chars": 2_000_000,
                    "approx_tokens": 500_000,
                },
            ],
        },
    )

    with db.read() as conn:
        context = load_context(conn, AnalysisScope(), Thresholds(), NOW)

    assert context.events[0].context_blocks == (
        ContextBlockFact(hash="ok", chars=8000, approx_tokens=2000),
        ContextBlockFact(hash="at-cap", chars=2_000_000, approx_tokens=500_000),
    )


def test_non_list_blocks_and_falsy_repeat_parsed_as_absent(db: Database) -> None:
    _ingest(
        db, external_session_id="sess-m", metadata={"context_blocks": {"hash": "h1"}}
    )

    with db.read() as conn:
        context = load_context(conn, AnalysisScope(), Thresholds(), NOW)

    assert context.events[0].intentional_repeat is False
    assert context.events[0].context_blocks == ()


def test_scope_filters_events_sessions_and_tasks(db: Database) -> None:
    first = _ingest(db, external_session_id="sess-a")
    second = _ingest(db, external_session_id="sess-b")
    assert first.session_id is not None and second.session_id is not None

    with db.read() as conn:
        scoped = load_context(
            conn, AnalysisScope(session_id=first.session_id), Thresholds(), NOW
        )
        unscoped = load_context(conn, AnalysisScope(), Thresholds(), NOW)

    assert [e.id for e in scoped.events] == [first.id]
    assert set(scoped.sessions) == {first.session_id}
    assert {e.id for e in unscoped.events} == {first.id, second.id}
    assert set(unscoped.sessions) == {first.session_id, second.session_id}


def test_loader_attaches_estimated_cost_in_time_order(db: Database) -> None:
    late = _ingest(db, external_session_id="sess-c")
    with db.read() as conn:
        context = load_context(conn, AnalysisScope(), Thresholds(), NOW)

    assert [e.id for e in context.events] == [late.id]
    assert context.events[0].est_cost is not None
    assert context.events[0].currency == "USD"

    unpriced = _ingest(db, external_session_id="sess-c", input_tokens=None)
    with db.read() as conn:
        context = load_context(conn, AnalysisScope(), Thresholds(), NOW)

    costs = {e.id: (e.est_cost, e.currency) for e in context.events}
    assert costs[late.id][0] is not None
    assert costs[unpriced.id] == (None, None)
