"""Unit tests for `summarize`: NULL-aware sums, coverage, percentiles, D11 (Task 1.5)."""

import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

import tokenpilot.pricing.catalog as catalog_module
from tokenpilot.analytics.summary import summarize
from tokenpilot.db.connection import connect, transaction
from tokenpilot.db.migrate import migrate
from tokenpilot.ledger.ingest import ingest_event
from tokenpilot.pricing.catalog import create_version, load_catalog
from tokenpilot.pricing.cost import reprice_all
from tokenpilot.schemas.summary import SummaryFilters
from tokenpilot.schemas.usage import UsageEvent, UsageEventIn

CATALOG_PATH = Path(catalog_module.__file__).parent / "catalog.yaml"
BASE = datetime(2026, 10, 29, 10, 0, 0, tzinfo=UTC)
# fake-small input is "0.25" per 1M tokens (demo-simulated seed).
ONE_DOLLAR = 4_000_000
TWO_DOLLARS = 8_000_000


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "summary.sqlite3")
    migrate(connection)
    with transaction(connection):
        load_catalog(connection, CATALOG_PATH)
    yield connection
    connection.close()


def ingest(conn: sqlite3.Connection, offset_s: float = 0, **overrides: Any) -> UsageEvent:
    fields: dict[str, Any] = {
        "provider": "fake",
        "model_id": "fake-small",
        "started_at": BASE + timedelta(seconds=offset_s),
        "usage_source": "provider",
        "status": "success",
        "input_tokens": ONE_DOLLAR,
        "output_tokens": 0,
    }
    fields.update(overrides)
    with transaction(conn):
        return ingest_event(conn, UsageEventIn(**fields), "api").event


def test_summary_excludes_null_costs_and_counts_them(conn: sqlite3.Connection) -> None:
    ingest(conn, 0, input_tokens=ONE_DOLLAR)
    ingest(conn, 1, input_tokens=TWO_DOLLARS)
    ingest(conn, 2, input_tokens=None, output_tokens=None, usage_source="unavailable")

    summary = summarize(conn, SummaryFilters())

    assert summary.total_estimated_cost == Decimal("3.00")
    assert summary.events_with_unknown_cost == 1
    assert summary.currency == "USD"
    assert summary.request_count == 3
    assert summary.input_tokens == ONE_DOLLAR + TWO_DOLLARS
    assert summary.output_tokens == 0
    assert summary.events_with_unknown_tokens == 1
    assert summary.total_reported_cost is None
    assert summary.cost_basis == "simulated"
    assert summary.coverage.priced_pct == pytest.approx(200 / 3)
    assert summary.coverage.mixed_currency is False


def test_latency_percentiles_null_below_20_samples(conn: sqlite3.Connection) -> None:
    for i in range(19):
        ingest(conn, i, latency_ms=100 + i)
    ingest(conn, 30, latency_ms=None)

    assert summarize(conn, SummaryFilters()).latency_ms is None

    ingest(conn, 40, latency_ms=500)
    latency = summarize(conn, SummaryFilters()).latency_ms
    assert latency is not None
    # 100..118 plus 500: nearest rank puts p95 at sorted[18], not the maximum.
    assert (latency.p50, latency.p95) == (109, 118)


def test_percentiles_nearest_rank(conn: sqlite3.Connection) -> None:
    for value in range(20, 0, -1):
        ingest(conn, value, latency_ms=value)

    latency = summarize(conn, SummaryFilters()).latency_ms

    assert latency is not None
    assert (latency.p50, latency.p95) == (10, 19)
    assert latency.avg == pytest.approx(10.5)


def test_retry_cost_counts_attempts_after_first(conn: sqlite3.Connection) -> None:
    ingest(conn, 0, source_event_id="r1", status="error", input_tokens=ONE_DOLLAR)
    ingest(conn, 5, source_event_id="r2", status="timeout", retry_of="r1",
           input_tokens=TWO_DOLLARS)
    ingest(conn, 10, source_event_id="r3", retry_of="r2", input_tokens=ONE_DOLLAR)
    ingest(conn, 20, source_event_id="other", input_tokens=ONE_DOLLAR)

    summary = summarize(conn, SummaryFilters())

    assert summary.retry_count == 2
    assert summary.retry_cost == Decimal("3.00")
    assert summary.failed_count == 2
    assert summary.total_estimated_cost == Decimal("5.00")


def test_mixed_currency_totals_are_null(conn: sqlite3.Connection) -> None:
    with transaction(conn):
        create_version(
            conn,
            provider="fake",
            model_id="fake-eur",
            currency="EUR",
            input_price_per_million=Decimal("0.25"),
            output_price_per_million=Decimal("1.25"),
            cached_input_price=None,
            pricing_source="demo-simulated",
            valid_from="2026-01-01T00:00:00.000Z",
        )
    ingest(conn, 0, model_id="fake-small", source_event_id="usd")
    ingest(conn, 1, model_id="fake-eur", source_event_id="eur")

    summary = summarize(conn, SummaryFilters())

    assert summary.total_estimated_cost is None
    assert summary.currency is None
    assert summary.coverage.mixed_currency is True
    assert summary.retry_cost is None
    assert summary.cost_by_outcome.unknown is None
    assert summary.cost_concentration_top10_pct is None
    # Each model is single-currency, so its own row keeps an amount and its label.
    models = {m.model_id: m for m in summary.by_model}
    assert (models["fake-small"].estimated_cost, models["fake-small"].currency) == (
        Decimal("1.00"),
        "USD",
    )
    assert models["fake-eur"].currency == "EUR"
    # The day bucket holds both currencies, so it cannot be one number.
    assert summary.timeseries[0].estimated_cost is None
    assert summary.timeseries[0].currency is None


def test_unlabelled_only_costs_set_mixed_currency(conn: sqlite3.Connection) -> None:
    """Reported cost with no currency → null totals and mixed_currency true (M1)."""
    ingest(
        conn,
        0,
        model_id="unpriced-model",
        input_tokens=None,
        output_tokens=None,
        usage_source="unavailable",
        metadata={"reported_cost": 1.5},
    )

    summary = summarize(conn, SummaryFilters())

    assert summary.request_count == 1
    assert summary.total_estimated_cost is None
    assert summary.total_reported_cost is None
    assert summary.currency is None
    assert summary.cost_basis == "reported"
    assert summary.coverage.mixed_currency is True


def test_summary_uses_latest_cost_record(conn: sqlite3.Connection) -> None:
    ingest(conn, 0, input_tokens=ONE_DOLLAR)
    with transaction(conn):
        create_version(
            conn,
            provider="fake",
            model_id="fake-small",
            currency="USD",
            input_price_per_million=Decimal("0.50"),
            output_price_per_million=Decimal("2.50"),
            cached_input_price=Decimal("0.05"),
            pricing_source="demo-simulated",
            valid_from="2026-10-28T00:00:00.000Z",
        )
        reprice_all(conn, "fake", "fake-small")

    summary = summarize(conn, SummaryFilters())

    assert conn.execute("SELECT COUNT(*) FROM cost_records").fetchone()[0] == 2
    assert summary.total_estimated_cost == Decimal("2.00")


def test_cost_by_outcome_task_beats_session(conn: sqlite3.Connection) -> None:
    task_event = ingest(
        conn, 0, external_session_id="s1", project_id="p1", task_id="t1",
        input_tokens=ONE_DOLLAR,
    )
    session_event = ingest(conn, 1, external_session_id="s1", input_tokens=TWO_DOLLARS)
    ingest(conn, 2, input_tokens=ONE_DOLLAR)
    assert task_event.task_id is not None
    with transaction(conn):
        conn.execute("UPDATE tasks SET outcome = 'failed' WHERE id = ?", (task_event.task_id,))
        conn.execute(
            "UPDATE sessions SET outcome = 'success' WHERE id = ?", (session_event.session_id,)
        )

    summary = summarize(conn, SummaryFilters())

    assert summary.cost_by_outcome.failed == Decimal("1.00")
    assert summary.cost_by_outcome.passed == Decimal("2.00")
    assert summary.cost_by_outcome.unknown == Decimal("1.00")
    failed_only = summarize(conn, SummaryFilters(outcome="failed"))
    assert failed_only.request_count == 1
    assert failed_only.total_estimated_cost == Decimal("1.00")


def test_empty_ledger_summary(conn: sqlite3.Connection) -> None:
    summary = summarize(conn, SummaryFilters())

    counts = (
        summary.request_count,
        summary.failed_count,
        summary.retry_count,
        summary.events_with_unknown_cost,
        summary.events_with_unknown_tokens,
    )
    assert counts == (0, 0, 0, 0, 0)
    money = (
        summary.total_estimated_cost,
        summary.total_reported_cost,
        summary.retry_cost,
        summary.cost_by_outcome.passed,
        summary.cost_by_outcome.failed,
        summary.cost_by_outcome.unknown,
    )
    assert money == (None,) * 6
    assert summary.currency is None
    assert summary.cost_basis == "unavailable"
    assert summary.input_tokens is None
    assert summary.output_tokens is None
    assert summary.latency_ms is None
    assert summary.cost_concentration_top10_pct is None
    coverage = summary.coverage
    assert (
        coverage.attributed_pct,
        coverage.priced_pct,
        coverage.provider_usage_pct,
        coverage.mixed_currency,
    ) == (None, None, None, None)
    assert (summary.by_project, summary.by_model, summary.timeseries, summary.top_sessions) == (
        [],
        [],
        [],
        [],
    )


def test_by_project_names_unattributed_and_coverage(conn: sqlite3.Connection) -> None:
    ingest(conn, 0, project_id="alpha", input_tokens=TWO_DOLLARS)
    ingest(conn, 1, input_tokens=ONE_DOLLAR, usage_source="gateway_estimate")

    summary = summarize(conn, SummaryFilters())

    rows = [(p.name, p.estimated_cost, p.currency, p.request_count) for p in summary.by_project]
    assert rows == [
        ("alpha", Decimal("2.00"), "USD", 1),
        ("Unattributed", Decimal("1.00"), "USD", 1),
    ]
    assert summary.by_project[1].project_id is None
    assert summary.coverage.attributed_pct == pytest.approx(50.0)
    assert summary.coverage.provider_usage_pct == pytest.approx(50.0)
    assert summary.coverage.priced_pct == pytest.approx(100.0)


def test_by_model_reports_unknown_tokens(conn: sqlite3.Connection) -> None:
    ingest(conn, 0, input_tokens=ONE_DOLLAR, output_tokens=10)
    ingest(conn, 1, input_tokens=None, output_tokens=5)
    ingest(conn, 2, model_id="fake-large", input_tokens=None, output_tokens=None)

    models = {m.model_id: m for m in summarize(conn, SummaryFilters()).by_model}

    small = models["fake-small"]
    assert (small.provider, small.request_count) == ("fake", 2)
    assert (small.input_tokens, small.output_tokens) == (ONE_DOLLAR, 15)
    assert small.events_with_unknown_tokens == 1
    large = models["fake-large"]
    assert (large.input_tokens, large.output_tokens) == (None, None)
    assert large.events_with_unknown_tokens == 1
    assert (large.estimated_cost, large.currency) == (None, None)


def test_top_sessions_and_concentration(conn: sqlite3.Connection) -> None:
    for i in range(12):
        ingest(conn, i, external_session_id=f"s{i:02d}", input_tokens=ONE_DOLLAR * (i + 1))
    ingest(conn, 100, input_tokens=ONE_DOLLAR)

    summary = summarize(conn, SummaryFilters())

    # Sessions cost 1..12 plus a $1 sessionless event: total 79, top ten 12..3 = 75.
    assert summary.total_estimated_cost == Decimal("79.00")
    assert len(summary.top_sessions) == 10
    assert [s.estimated_cost for s in summary.top_sessions][:2] == [Decimal("12"), Decimal("11")]
    assert summary.top_sessions[0].outcome == "unknown"
    assert summary.top_sessions[0].currency == "USD"
    assert summary.cost_concentration_top10_pct == pytest.approx(75 / 79 * 100)


def test_timeseries_buckets_by_day_and_hour(conn: sqlite3.Connection) -> None:
    ingest(conn, 0)
    ingest(conn, 3600)
    ingest(conn, 86400)

    by_day = summarize(conn, SummaryFilters()).timeseries
    by_hour = summarize(conn, SummaryFilters(bucket="hour")).timeseries

    assert [(p.bucket_start, p.request_count, p.estimated_cost) for p in by_day] == [
        ("2026-10-29T00:00:00.000Z", 2, Decimal("2.00")),
        ("2026-10-30T00:00:00.000Z", 1, Decimal("1.00")),
    ]
    assert [p.bucket_start for p in by_hour] == [
        "2026-10-29T10:00:00.000Z",
        "2026-10-29T11:00:00.000Z",
        "2026-10-30T10:00:00.000Z",
    ]


def test_summary_filters(conn: sqlite3.Connection) -> None:
    ingest(conn, 0, project_id="alpha")
    ingest(conn, 3600, model_id="fake-large", input_tokens=1_000_000)
    ingest(conn, 7200, provider="meta", model_id="muse-spark-1.3")

    window = summarize(
        conn,
        SummaryFilters(
            started_from="2026-10-29T10:30:00.000Z", started_to="2026-10-29T12:00:00.000Z"
        ),
    )
    by_provider = summarize(conn, SummaryFilters(provider="meta"))
    by_model = summarize(conn, SummaryFilters(model_id="fake-large"))
    projects = {p.name: p.project_id for p in summarize(conn, SummaryFilters()).by_project}
    by_project = summarize(conn, SummaryFilters(project_id=projects["alpha"]))

    assert projects["alpha"] is not None
    assert window.request_count == 1
    assert window.total_estimated_cost == Decimal("3.00")
    assert by_provider.request_count == 1
    assert by_model.by_model[0].model_id == "fake-large"
    assert by_project.request_count == 1
    assert by_project.by_project[0].name == "alpha"


def test_cost_basis_estimated_for_real_pricing(conn: sqlite3.Connection) -> None:
    ingest(conn, 0, provider="meta", model_id="muse-spark-1.3", input_tokens=1_000_000)
    ingest(conn, 1, input_tokens=ONE_DOLLAR)

    summary = summarize(conn, SummaryFilters())

    assert summary.cost_basis == "estimated"
    assert summary.total_estimated_cost == Decimal("2.25")


def test_cost_basis_mixed_and_reported(conn: sqlite3.Connection) -> None:
    ingest(conn, 0, provider="meta", model_id="muse-spark-1.3", input_tokens=1_000_000,
           metadata={"reported_cost": 1.5, "reported_currency": "USD"})

    assert summarize(conn, SummaryFilters()).cost_basis == "reported"
    reported = summarize(conn, SummaryFilters()).total_reported_cost
    assert reported == Decimal("1.5")

    ingest(conn, 1, provider="meta", model_id="muse-spark-1.3", input_tokens=1_000_000)
    assert summarize(conn, SummaryFilters()).cost_basis == "mixed"
