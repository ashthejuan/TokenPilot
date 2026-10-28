"""Usage summary: SQL aggregates over the latest cost record per event.

The filtered events are joined to their latest cost once, into a temp table,
and every aggregate reads that table. Resolving the latest cost is the
expensive step, so it isn't repeated, and all sections see the same rows.
NULL costs and tokens are skipped by the sums and counted separately. Money
follows `analytics.money`: exact scaled sums, NULL across currencies (D11).
"""

import sqlite3
from decimal import Decimal
from typing import Any

from tokenpilot.analytics.money import (
    COST_CURRENCY,
    GROUP_CURRENCY,
    MIXED_CURRENCY,
    SCALED_ESTIMATE,
    SCALED_REPORTED,
    group_money,
    money_from_scaled,
)
from tokenpilot.pricing.cost import latest_cost_sql
from tokenpilot.schemas.summary import (
    CostByOutcome,
    Coverage,
    LatencyStats,
    ModelCost,
    ProjectCost,
    SessionCost,
    SummaryCostBasis,
    SummaryFilters,
    TimeseriesPoint,
    UsageSummary,
)

__all__ = ["summarize"]

LATENCY_MIN_SAMPLES = 20
TOP_SESSIONS = 10
SIMULATED_SOURCE = "demo-simulated"

# Task outcome wins when the event has a task; otherwise the session outcome.
# `IN (subquery)` probes a small in-memory set, cheaper per event than a join.
_OUTCOME_CLASS = (
    "CASE WHEN u.task_id IS NOT NULL THEN CASE "
    "WHEN u.task_id IN (SELECT id FROM tasks WHERE outcome = 'passed') THEN 'passed' "
    "WHEN u.task_id IN (SELECT id FROM tasks WHERE outcome = 'failed') THEN 'failed' "
    "ELSE 'unknown' END "
    "WHEN u.session_id IN (SELECT id FROM sessions WHERE outcome = 'success') THEN 'passed' "
    "WHEN u.session_id IN (SELECT id FROM sessions WHERE outcome = 'failure') THEN 'failed' "
    "ELSE 'unknown' END"
)
_BUCKET_START = {
    "day": "substr(u.started_at, 1, 10) || 'T00:00:00.000Z'",
    "hour": "substr(u.started_at, 1, 13) || ':00:00.000Z'",
}
_EVENTS = "summary_events"


def _events_select(f: SummaryFilters) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    for column, value in (
        ("u.project_id", f.project_id),
        ("u.provider", f.provider),
        ("u.model_id", f.model_id),
    ):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    if f.started_from is not None:
        clauses.append("u.started_at >= ?")
        params.append(f.started_from)
    if f.started_to is not None:
        clauses.append("u.started_at < ?")
        params.append(f.started_to)
    if f.outcome is not None:
        clauses.append(f"({_OUTCOME_CLASS}) = ?")
        params.append(f.outcome)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    select = (
        f"WITH {latest_cost_sql} "
        "SELECT u.project_id, u.session_id, u.provider, u.model_id, u.input_tokens, "
        "u.output_tokens, u.latency_ms, "
        "u.usage_source = 'provider' AS from_provider, "
        "u.status IN ('error', 'timeout') AS failed, "
        "COALESCE(u.attempt > 1, 0) AS retry, "
        f"{_BUCKET_START[f.bucket]} AS bucket_start, "
        f"{SCALED_ESTIMATE} AS est, {SCALED_REPORTED} AS rep, {COST_CURRENCY} AS cur, "
        "lc.cost_basis, "
        "COALESCE(lc.pricing_version_id IN "
        f"(SELECT id FROM pricing_versions WHERE pricing_source = '{SIMULATED_SOURCE}'), 0) "
        "AS simulated, "
        f"{_OUTCOME_CLASS} AS outcome_class "
        "FROM usage_events u LEFT JOIN latest_costs lc ON lc.usage_event_id = u.id "
        f"{where}"
    )
    return select, params


def _outcome_money(outcome: str) -> str:
    return group_money(f"CASE WHEN outcome_class = '{outcome}' THEN est END")


_TOTALS = (
    "SELECT COUNT(*) AS request_count, "
    f"{group_money('est')} AS total_estimated, "
    f"{group_money('rep')} AS total_reported, "
    f"{GROUP_CURRENCY} AS currency, "
    f"CASE WHEN COUNT(*) > 0 THEN {MIXED_CURRENCY} END AS mixed_currency, "
    "COALESCE(SUM(est IS NULL), 0) AS unknown_cost, "
    "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
    "COALESCE(SUM(input_tokens IS NULL OR output_tokens IS NULL), 0) AS unknown_tokens, "
    "COALESCE(SUM(failed), 0) AS failed_count, "
    "COALESCE(SUM(retry), 0) AS retry_count, "
    f"{group_money('CASE WHEN retry THEN est END')} AS retry_cost, "
    f"{_outcome_money('passed')} AS passed_cost, "
    f"{_outcome_money('failed')} AS failed_cost, "
    f"{_outcome_money('unknown')} AS unknown_outcome_cost, "
    "COUNT(cur) AS costed, "
    "COALESCE(SUM(cur IS NOT NULL AND simulated), 0) AS simulated, "
    "COALESCE(SUM(cur IS NOT NULL AND cost_basis = 'estimated'), 0) AS basis_estimated, "
    "COALESCE(SUM(cur IS NOT NULL AND cost_basis = 'reported'), 0) AS basis_reported, "
    "100.0 * SUM(project_id IS NOT NULL) / COUNT(*) AS attributed_pct, "
    "100.0 * SUM(est IS NOT NULL) / COUNT(*) AS priced_pct, "
    "100.0 * SUM(from_provider) / COUNT(*) AS provider_usage_pct, "
    "COUNT(latency_ms) AS latency_samples, AVG(latency_ms) AS latency_avg "
    f"FROM {_EVENTS}"
)
# Nearest rank: the smallest latency whose cumulative count reaches rank k.
_LATENCY_RANKS = (
    "SELECT MIN(CASE WHEN seen >= ? THEN latency_ms END) AS p50, "
    "MIN(CASE WHEN seen >= ? THEN latency_ms END) AS p95 "
    "FROM (SELECT latency_ms, SUM(COUNT(*)) OVER (ORDER BY latency_ms) AS seen "
    f"FROM {_EVENTS} WHERE latency_ms IS NOT NULL GROUP BY latency_ms)"
)
_BY_PROJECT = (
    "SELECT e.project_id, p.name, e.request_count, e.cost, e.currency FROM ("
    f"SELECT project_id, COUNT(*) AS request_count, {group_money('est')} AS cost, "
    f"{GROUP_CURRENCY} AS currency FROM {_EVENTS} GROUP BY project_id) e "
    "LEFT JOIN projects p ON p.id = e.project_id "
    "ORDER BY e.cost IS NULL, e.cost DESC, e.request_count DESC, "
    "e.project_id IS NULL, e.project_id"
)
_BY_MODEL = (
    "SELECT provider, model_id, COUNT(*) AS request_count, "
    f"{group_money('est')} AS cost, {GROUP_CURRENCY} AS currency, "
    "SUM(input_tokens) AS input_tokens, SUM(output_tokens) AS output_tokens, "
    "SUM(input_tokens IS NULL OR output_tokens IS NULL) AS unknown_tokens "
    f"FROM {_EVENTS} GROUP BY provider, model_id "
    "ORDER BY cost IS NULL, cost DESC, request_count DESC, provider, model_id"
)
_TIMESERIES = (
    "SELECT bucket_start, COUNT(*) AS request_count, "
    f"{group_money('est')} AS cost, {GROUP_CURRENCY} AS currency "
    f"FROM {_EVENTS} GROUP BY bucket_start ORDER BY bucket_start"
)
_TOP_SESSIONS = (
    "SELECT e.session_id, s.project_id, s.outcome, e.request_count, e.cost, e.currency FROM ("
    f"SELECT session_id, COUNT(*) AS request_count, {group_money('est')} AS cost, "
    f"{GROUP_CURRENCY} AS currency FROM {_EVENTS} WHERE session_id IS NOT NULL "
    "GROUP BY session_id ORDER BY cost IS NULL, cost DESC, request_count DESC, session_id "
    "LIMIT ?) e JOIN sessions s ON s.id = e.session_id "
    "ORDER BY e.cost IS NULL, e.cost DESC, e.request_count DESC, e.session_id"
)


def _cost_basis(row: sqlite3.Row) -> SummaryCostBasis:
    costed = row["costed"]
    if costed == 0:
        return "unavailable"
    if row["simulated"] == costed:
        return "simulated"
    if row["basis_estimated"] == costed:
        return "estimated"
    if row["basis_reported"] == costed:
        return "reported"
    return "mixed"


def _nearest_rank(percent: int, n: int) -> int:
    """1-based nearest rank, `ceil(percent / 100 * n)`, in integers to avoid float error."""
    return (percent * n + 99) // 100


def _latency(conn: sqlite3.Connection, totals: sqlite3.Row) -> LatencyStats | None:
    samples = totals["latency_samples"]
    if samples < LATENCY_MIN_SAMPLES:
        return None
    row = conn.execute(
        _LATENCY_RANKS, (_nearest_rank(50, samples), _nearest_rank(95, samples))
    ).fetchone()
    return LatencyStats(avg=float(totals["latency_avg"]), p50=row["p50"], p95=row["p95"])


def _concentration(total: Decimal | None, top: list[SessionCost]) -> float | None:
    if total is None or total == 0:
        return None
    top_cost = sum((s.estimated_cost for s in top if s.estimated_cost is not None), Decimal(0))
    return float(top_cost / total * 100)


def summarize(conn: sqlite3.Connection, f: SummaryFilters) -> UsageSummary:
    """Aggregate the ledger under `f`. The caller holds the connection (`Database.read()`)."""
    select, params = _events_select(f)
    conn.execute(f"DROP TABLE IF EXISTS temp.{_EVENTS}")
    conn.execute(f"CREATE TEMP TABLE {_EVENTS} AS {select}", params)
    try:
        return _summarize_events(conn)
    finally:
        conn.execute(f"DROP TABLE temp.{_EVENTS}")


def _summarize_events(conn: sqlite3.Connection) -> UsageSummary:
    totals = conn.execute(_TOTALS).fetchone()
    by_project = [
        ProjectCost(
            project_id=row["project_id"],
            name="Unattributed" if row["project_id"] is None else row["name"],
            estimated_cost=money_from_scaled(row["cost"]),
            currency=row["currency"],
            request_count=row["request_count"],
        )
        for row in conn.execute(_BY_PROJECT)
    ]
    by_model = [
        ModelCost(
            provider=row["provider"],
            model_id=row["model_id"],
            estimated_cost=money_from_scaled(row["cost"]),
            currency=row["currency"],
            request_count=row["request_count"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            events_with_unknown_tokens=row["unknown_tokens"],
        )
        for row in conn.execute(_BY_MODEL)
    ]
    timeseries = [
        TimeseriesPoint(
            bucket_start=row["bucket_start"],
            estimated_cost=money_from_scaled(row["cost"]),
            currency=row["currency"],
            request_count=row["request_count"],
        )
        for row in conn.execute(_TIMESERIES)
    ]
    top_sessions = [
        SessionCost(
            session_id=row["session_id"],
            project_id=row["project_id"],
            estimated_cost=money_from_scaled(row["cost"]),
            currency=row["currency"],
            request_count=row["request_count"],
            outcome=row["outcome"],
        )
        for row in conn.execute(_TOP_SESSIONS, (TOP_SESSIONS,))
    ]
    total_estimated = money_from_scaled(totals["total_estimated"])
    mixed = totals["mixed_currency"]
    return UsageSummary(
        total_estimated_cost=total_estimated,
        total_reported_cost=money_from_scaled(totals["total_reported"]),
        currency=totals["currency"],
        cost_basis=_cost_basis(totals),
        events_with_unknown_cost=totals["unknown_cost"],
        input_tokens=totals["input_tokens"],
        output_tokens=totals["output_tokens"],
        events_with_unknown_tokens=totals["unknown_tokens"],
        request_count=totals["request_count"],
        failed_count=totals["failed_count"],
        retry_count=totals["retry_count"],
        retry_cost=money_from_scaled(totals["retry_cost"]),
        latency_ms=_latency(conn, totals),
        by_project=by_project,
        by_model=by_model,
        timeseries=timeseries,
        top_sessions=top_sessions,
        cost_by_outcome=CostByOutcome(
            passed=money_from_scaled(totals["passed_cost"]),
            failed=money_from_scaled(totals["failed_cost"]),
            unknown=money_from_scaled(totals["unknown_outcome_cost"]),
        ),
        cost_concentration_top10_pct=_concentration(total_estimated, top_sessions),
        coverage=Coverage(
            attributed_pct=totals["attributed_pct"],
            priced_pct=totals["priced_pct"],
            provider_usage_pct=totals["provider_usage_pct"],
            mixed_currency=None if mixed is None else bool(mixed),
        ),
    )
