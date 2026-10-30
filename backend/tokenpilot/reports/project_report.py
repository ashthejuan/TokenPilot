"""Assemble project and savings reports from summary, insights, and comparisons."""

from __future__ import annotations

import json
import sqlite3
from decimal import Decimal
from typing import Any

from tokenpilot.analytics.summary import summarize
from tokenpilot.savings.classify import Comparison, savings_kind
from tokenpilot.schemas.benchmarks import cost_to_decimal
from tokenpilot.schemas.common import Money
from tokenpilot.schemas.projects import Project
from tokenpilot.schemas.reports import (
    REALIZED_LIMITATION,
    ProjectReport,
    ReportBenchmark,
    ReportPeriod,
    ReportRecommendation,
    SavingsBreakdown,
    SavingsReport,
    UnattributedUsage,
    WasteByRule,
)
from tokenpilot.schemas.summary import (
    CostByOutcome,
    Coverage,
    SessionCost,
    SummaryCostBasis,
    SummaryFilters,
)

_ZERO = Decimal("0")
_TOP_RECOMMENDATIONS = 10


def _money_or_zero(value: Decimal | None) -> Money:
    return _ZERO if value is None else value


def _period_clauses(
    column: str, started_from: str | None, started_to: str | None
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []
    if started_from is not None:
        clauses.append(f"{column} >= ?")
        params.append(started_from)
    if started_to is not None:
        clauses.append(f"{column} < ?")
        params.append(started_to)
    return (" AND ".join(clauses), params)


def _sum_insight_potential(
    conn: sqlite3.Connection,
    *,
    project_id: str | None,
    started_from: str | None,
    started_to: str | None,
) -> Decimal:
    """Sum untested insight `estimated_impact` in scope/period (FR-11 potential).

    Excludes dismissed and tested insights — potential is untested recommendations.
    """
    clauses = [
        "status NOT IN ('dismissed', 'tested')",
        "estimated_impact IS NOT NULL",
    ]
    params: list[Any] = []
    if project_id is not None:
        clauses.append("project_id = ?")
        params.append(project_id)
    period_sql, period_params = _period_clauses("created_at", started_from, started_to)
    if period_sql:
        clauses.append(period_sql)
        params.extend(period_params)
    row = conn.execute(
        f"SELECT COALESCE(SUM(estimated_impact), 0) AS total FROM insights "
        f"WHERE {' AND '.join(clauses)}",
        params,
    ).fetchone()
    return Decimal(str(row["total"]))


def _comparison_savings(
    conn: sqlite3.Connection,
    *,
    project_id: str | None,
    started_from: str | None,
    started_to: str | None,
) -> tuple[Decimal, Decimal]:
    """Sum comparison `cost_delta` into benchmark/verified via `savings_kind`.

    Comparison rows whose kind is `potential` (incomparable/inconclusive) are
    skipped so they do not mix with the insight potential bucket.
    """
    clauses: list[str] = []
    params: list[Any] = []
    if project_id is not None:
        clauses.append("b.project_id = ?")
        params.append(project_id)
    period_sql, period_params = _period_clauses("c.created_at", started_from, started_to)
    if period_sql:
        clauses.append(period_sql)
        params.extend(period_params)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        "SELECT c.comparison_status, c.cost_delta FROM benchmark_comparisons c "
        "JOIN benchmarks b ON b.id = c.benchmark_id "
        f"{where}",
        params,
    ).fetchall()
    benchmark_total = _ZERO
    verified_total = _ZERO
    for row in rows:
        kind = savings_kind(Comparison(comparison_status=row["comparison_status"]))
        delta = cost_to_decimal(row["cost_delta"])
        if delta is None:
            continue
        if kind == "benchmark":
            benchmark_total += delta
        elif kind == "verified":
            verified_total += delta
    return benchmark_total, verified_total


def _build_savings(
    conn: sqlite3.Connection,
    *,
    project_id: str | None,
    started_from: str | None,
    started_to: str | None,
) -> SavingsBreakdown:
    potential = _sum_insight_potential(
        conn,
        project_id=project_id,
        started_from=started_from,
        started_to=started_to,
    )
    benchmark, verified = _comparison_savings(
        conn,
        project_id=project_id,
        started_from=started_from,
        started_to=started_to,
    )
    return SavingsBreakdown(
        potential=_money_or_zero(potential),
        benchmark=_money_or_zero(benchmark),
        verified=_money_or_zero(verified),
        realized=None,
    )


def _waste_by_rule(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    started_from: str | None,
    started_to: str | None,
) -> list[WasteByRule]:
    clauses = ["project_id = ?", "status != 'dismissed'"]
    params: list[Any] = [project_id]
    period_sql, period_params = _period_clauses("created_at", started_from, started_to)
    if period_sql:
        clauses.append(period_sql)
        params.extend(period_params)
    rows = conn.execute(
        "SELECT rule_id, COUNT(*) AS count, "
        "SUM(estimated_impact) AS impact "
        f"FROM insights WHERE {' AND '.join(clauses)} "
        "GROUP BY rule_id ORDER BY impact IS NULL, impact DESC, rule_id",
        params,
    ).fetchall()
    return [
        WasteByRule(
            rule_id=row["rule_id"],
            estimated_impact=cost_to_decimal(row["impact"]),
            count=int(row["count"]),
        )
        for row in rows
    ]


def _top_recommendations(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    started_from: str | None,
    started_to: str | None,
) -> list[ReportRecommendation]:
    clauses = [
        "project_id = ?",
        "status != 'dismissed'",
        "recommendation_json IS NOT NULL",
    ]
    params: list[Any] = [project_id]
    period_sql, period_params = _period_clauses("created_at", started_from, started_to)
    if period_sql:
        clauses.append(period_sql)
        params.extend(period_params)
    rows = conn.execute(
        "SELECT id, rule_id, title, recommendation_json, estimated_impact, impact_currency "
        f"FROM insights WHERE {' AND '.join(clauses)} "
        "ORDER BY estimated_impact IS NULL, estimated_impact DESC, created_at DESC, id DESC "
        f"LIMIT {_TOP_RECOMMENDATIONS}",
        params,
    ).fetchall()
    return [
        ReportRecommendation(
            insight_id=row["id"],
            rule_id=row["rule_id"],
            title=row["title"],
            recommendation=json.loads(row["recommendation_json"]),
            estimated_impact=cost_to_decimal(row["estimated_impact"]),
            impact_currency=row["impact_currency"],
        )
        for row in rows
    ]


def _benchmarks(
    conn: sqlite3.Connection,
    *,
    project_id: str,
    started_from: str | None,
    started_to: str | None,
) -> list[ReportBenchmark]:
    clauses = ["b.project_id = ?"]
    params: list[Any] = [project_id]
    period_sql, period_params = _period_clauses("c.created_at", started_from, started_to)
    if period_sql:
        clauses.append(period_sql)
        params.extend(period_params)
    rows = conn.execute(
        "SELECT b.name, c.comparison_status, c.cost_delta, c.cost_delta_pct, "
        "c.methodology_json, c.created_at "
        "FROM benchmark_comparisons c "
        "JOIN benchmarks b ON b.id = c.benchmark_id "
        f"WHERE {' AND '.join(clauses)} "
        "ORDER BY c.created_at DESC, c.id DESC",
        params,
    ).fetchall()
    results: list[ReportBenchmark] = []
    for row in rows:
        methodology = json.loads(row["methodology_json"] or "{}")
        results.append(
            ReportBenchmark(
                name=row["name"],
                comparison_status=row["comparison_status"],
                cost_delta=cost_to_decimal(row["cost_delta"]),
                cost_delta_pct=cost_to_decimal(row["cost_delta_pct"]),
                methodology=methodology,
            )
        )
    return results


def _limitations(summary_coverage: Coverage, unknown_cost_events: int) -> list[str]:
    lines: list[str] = []
    if unknown_cost_events > 0:
        noun = "event has" if unknown_cost_events == 1 else "events have"
        lines.append(f"{unknown_cost_events} {noun} no pricing")
    attributed = summary_coverage.attributed_pct
    if attributed is not None and attributed < 100.0:
        lines.append(f"Only {attributed:.1f}% of events are project-attributed")
    priced = summary_coverage.priced_pct
    if priced is not None and priced < 100.0 and unknown_cost_events == 0:
        lines.append(f"Only {priced:.1f}% of events have priced costs")
    if summary_coverage.mixed_currency:
        lines.append("Mixed currencies prevent a single total")
    lines.append(REALIZED_LIMITATION)
    return lines


def _unattributed(
    conn: sqlite3.Connection, started_from: str | None, started_to: str | None
) -> UnattributedUsage:
    """Window-wide unattributed usage (no project_id), for FR-12 disclosure."""
    filters = SummaryFilters(
        started_from=started_from,
        started_to=started_to,
        project_id=None,
    )
    summary = summarize(conn, filters)
    for row in summary.by_project:
        if row.project_id is None:
            return UnattributedUsage(
                events=row.request_count, estimated_cost=row.estimated_cost
            )
    return UnattributedUsage(events=0, estimated_cost=_ZERO)


def _empty_coverage() -> Coverage:
    return Coverage(
        attributed_pct=None,
        priced_pct=None,
        provider_usage_pct=None,
        mixed_currency=False,
    )


def build_project_report(
    conn: sqlite3.Connection,
    project: Project,
    *,
    started_from: str | None = None,
    started_to: str | None = None,
) -> ProjectReport:
    """Build the project report for `project` over the optional window."""
    filters = SummaryFilters(
        started_from=started_from,
        started_to=started_to,
        project_id=project.id,
    )
    summary = summarize(conn, filters)
    coverage: Coverage
    unknown: int
    spend: Money
    currency: str | None
    cost_basis: SummaryCostBasis
    top_sessions: list[SessionCost]
    cost_by_outcome: CostByOutcome
    if summary.request_count == 0:
        coverage = _empty_coverage()
        unknown = 0
        spend = _ZERO
        currency = project.default_currency
        cost_basis = "unavailable"
        top_sessions = []
        cost_by_outcome = CostByOutcome(passed=_ZERO, failed=_ZERO, unknown=_ZERO)
    else:
        coverage = summary.coverage
        unknown = summary.events_with_unknown_cost
        spend = (
            summary.total_estimated_cost
            if summary.total_estimated_cost is not None
            else _ZERO
        )
        currency = summary.currency
        cost_basis = summary.cost_basis
        top_sessions = summary.top_sessions
        cost_by_outcome = summary.cost_by_outcome

    savings = _build_savings(
        conn,
        project_id=project.id,
        started_from=started_from,
        started_to=started_to,
    )
    return ProjectReport(
        project_id=project.id,
        project_name=project.name,
        period=ReportPeriod(from_=started_from, to=started_to),
        cost_basis=cost_basis,
        currency=currency,
        coverage=coverage,
        spend_total=spend,
        unknown_cost_events=unknown,
        top_sessions=top_sessions,
        cost_by_outcome=cost_by_outcome,
        waste_by_rule=_waste_by_rule(
            conn,
            project_id=project.id,
            started_from=started_from,
            started_to=started_to,
        ),
        top_recommendations=_top_recommendations(
            conn,
            project_id=project.id,
            started_from=started_from,
            started_to=started_to,
        ),
        benchmarks=_benchmarks(
            conn,
            project_id=project.id,
            started_from=started_from,
            started_to=started_to,
        ),
        savings=savings,
        limitations=_limitations(coverage, unknown),
        unattributed=_unattributed(conn, started_from, started_to),
    )


def build_savings_report(
    conn: sqlite3.Connection,
    *,
    project_id: str | None = None,
    started_from: str | None = None,
    started_to: str | None = None,
) -> SavingsReport:
    """Aggregate the four savings kinds separately; never sum them."""
    breakdown = _build_savings(
        conn,
        project_id=project_id,
        started_from=started_from,
        started_to=started_to,
    )
    return SavingsReport(
        potential=breakdown.potential,
        benchmark=breakdown.benchmark,
        verified=breakdown.verified,
        realized=None,
    )


def _value_label(cost_basis: str) -> str:
    if cost_basis in ("reported",):
        return "actual (reported)"
    if cost_basis == "simulated":
        return "estimated (simulated pricing)"
    if cost_basis == "unavailable":
        return "unavailable"
    if cost_basis == "mixed":
        return "mixed estimated/actual"
    return "estimated"


def _fmt_money(value: Money | None) -> str:
    return "n/a" if value is None else str(value)


def render_markdown(report: ProjectReport) -> str:
    """Render FR-12 header first, then the body sections including methodology."""
    period = report.period
    from_label = period.from_ or "start"
    to_label = period.to or "now"
    coverage = report.coverage
    attributed = (
        "n/a" if coverage.attributed_pct is None else f"{coverage.attributed_pct:.1f}%"
    )
    priced = "n/a" if coverage.priced_pct is None else f"{coverage.priced_pct:.1f}%"
    provider = (
        "n/a"
        if coverage.provider_usage_pct is None
        else f"{coverage.provider_usage_pct:.1f}%"
    )
    lines = [
        f"# Project report: {report.project_name}",
        "",
        f"Period: {from_label} - {to_label}",
        f"Cost basis: {report.cost_basis}",
        (
            f"Data coverage: attributed {attributed}, priced {priced}, "
            f"provider usage {provider}"
        ),
        f"Values: {_value_label(report.cost_basis)}",
        "",
        "## Spend",
        f"- Spend total: {report.spend_total} {report.currency or ''}".rstrip(),
        f"- Unknown cost events: {report.unknown_cost_events}",
        "",
        "## Savings (kinds are separate; not summed)",
        f"- Potential: {report.savings.potential}",
        f"- Benchmark: {report.savings.benchmark}",
        f"- Verified: {report.savings.verified}",
        "- Realized: not measured",
        "",
        "## Limitations",
    ]
    for item in report.limitations:
        lines.append(f"- {item}")

    lines.extend(["", "## Top sessions"])
    if not report.top_sessions:
        lines.append("- (none)")
    else:
        for session in report.top_sessions:
            lines.append(
                f"- {session.session_id}: {_fmt_money(session.estimated_cost)} "
                f"{session.currency or ''} "
                f"({session.outcome}, {session.request_count} requests)".rstrip()
            )

    lines.extend(["", "## Waste by rule"])
    if not report.waste_by_rule:
        lines.append("- (none)")
    else:
        for row in report.waste_by_rule:
            lines.append(
                f"- {row.rule_id}: count={row.count}, "
                f"impact={_fmt_money(row.estimated_impact)}"
            )

    lines.extend(["", "## Top recommendations"])
    if not report.top_recommendations:
        lines.append("- (none)")
    else:
        for rec in report.top_recommendations:
            lines.append(
                f"- {rec.title} ({rec.rule_id}): "
                f"{_fmt_money(rec.estimated_impact)} {rec.impact_currency or ''}".rstrip()
            )
            lines.append(f"  recommendation: {json.dumps(rec.recommendation, sort_keys=True)}")

    lines.extend(["", "## Benchmarks"])
    if not report.benchmarks:
        lines.append("- (none)")
    else:
        for bench in report.benchmarks:
            pct = (
                "n/a"
                if bench.cost_delta_pct is None
                else f"{bench.cost_delta_pct}%"
            )
            lines.append(
                f"- {bench.name}: status={bench.comparison_status}, "
                f"cost_delta={_fmt_money(bench.cost_delta)}, "
                f"cost_delta_pct={pct}"
            )

    lines.extend(["", "## Methodology"])
    if not report.benchmarks:
        lines.append("- (none)")
    else:
        for bench in report.benchmarks:
            lines.append(f"### {bench.name}")
            lines.append("```json")
            lines.append(json.dumps(bench.methodology, sort_keys=True, indent=2))
            lines.append("```")

    unattr = report.unattributed
    lines.extend(
        [
            "",
            "## Unattributed",
            f"- Events: {unattr.events}",
            f"- Estimated cost: {_fmt_money(unattr.estimated_cost)}",
        ]
    )
    return "\n".join(lines) + "\n"
