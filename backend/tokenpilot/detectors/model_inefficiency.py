"""Detector G: a benchmark variant that costs more without succeeding more.

Cost differences across unrelated tasks prove nothing, so this rule only
reads `benchmark_comparisons`. One row fires at most one finding: the status
must be `measured`-or-better, the row must name a costlier side (nonzero
`cost_delta`), and that side's success rate must be at or below the cheaper
side's. Rates come from `methodology_json.success_rates`.

Severity follows the shared cost bands over the per-run delta, capped at
`medium` (comparison evidence alone never goes higher) and downgraded to
`informational` on low samples. Impact stays `None`: comparison rows record
no currency, and impact must pair with one. All reads are defensive — a
missing table or legacy columns yield `[]`, never an error.
"""

import json
import sqlite3
from decimal import Decimal
from typing import Any

from tokenpilot.detectors.base import (
    SEVERITY_RANK,
    EvidenceRef,
    Finding,
    Scope,
    Severity,
)
from tokenpilot.detectors.facts import DetectionContext
from tokenpilot.detectors.severity import cost_severity, format_money

RULE_ID = "model_inefficiency"
RULE_VERSION = 1

_FIRING_STATUSES = frozenset({"measured", "correctness_preserving", "verified"})
_CONFIDENCE = {"verified": 0.80, "correctness_preserving": 0.70, "measured": 0.60}


class ModelInefficiencyDetector:
    """Flags the costlier variant of a comparison when it succeeds no more often."""

    rule_id = RULE_ID
    rule_version = RULE_VERSION
    guidance = (
        "One model spent notably more than another on comparable work. "
        "Compare their success rates on the same benchmark before switching."
    )

    def detect(self, ctx: DetectionContext) -> list[Finding]:
        """One finding per costlier-not-better comparison, sorted by anchor."""
        try:
            rows = ctx.conn.execute(
                "SELECT id, benchmark_id, baseline_run_id, alternative_run_id, "
                "cost_delta, comparison_status, methodology_json "
                "FROM benchmark_comparisons ORDER BY id"
            ).fetchall()
        except sqlite3.OperationalError:
            return []
        findings = []
        for row in rows:
            finding = _finding_for_row(ctx, row)
            if finding is not None:
                findings.append(finding)
        findings.sort(key=lambda f: f.anchor)
        return findings


def _rates(methodology_json: Any) -> dict[str, float] | None:
    """The per-variant success rates, or None when absent or malformed."""
    if not isinstance(methodology_json, str):
        return None
    try:
        methodology = json.loads(methodology_json)
    except ValueError:
        return None
    if not isinstance(methodology, dict):
        return None
    rates = methodology.get("success_rates")
    if not isinstance(rates, dict):
        return None
    parsed: dict[str, float] = {}
    for variant in ("baseline", "alternative"):
        rate = rates.get(variant)
        if isinstance(rate, bool) or not isinstance(rate, (int, float)):
            return None
        parsed[variant] = float(rate)
    return parsed


def _low_sample(methodology_json: Any) -> bool:
    if not isinstance(methodology_json, str):
        return False
    try:
        methodology = json.loads(methodology_json)
    except ValueError:
        return False
    return isinstance(methodology, dict) and methodology.get("low_sample") is True


def _project_id(ctx: DetectionContext, benchmark_id: str) -> str | None:
    try:
        row = ctx.conn.execute(
            "SELECT project_id FROM benchmarks WHERE id = ?", (benchmark_id,)
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return None if row is None else row["project_id"]


def _finding_for_row(ctx: DetectionContext, row: sqlite3.Row) -> Finding | None:
    status = row["comparison_status"]
    if status not in _FIRING_STATUSES:
        return None
    raw_delta = row["cost_delta"]
    if raw_delta is None:
        return None
    delta = Decimal(str(raw_delta))
    if delta == 0:
        return None
    rates = _rates(row["methodology_json"])
    if rates is None:
        return None
    costlier = "baseline" if delta > 0 else "alternative"
    cheaper = "alternative" if delta > 0 else "baseline"
    if rates[costlier] > rates[cheaper]:
        return None
    severity: Severity = cost_severity(abs(delta), ctx.thresholds)
    if SEVERITY_RANK[severity] > SEVERITY_RANK["medium"]:
        severity = "medium"
    if _low_sample(row["methodology_json"]):
        severity = "informational"
    return Finding(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        anchor=f"comparison:{row['id']}",
        severity=severity,
        confidence=_CONFIDENCE[status],
        title=f"Costlier {costlier} variant matched by cheaper {cheaper}",
        summary=(
            f"The {costlier} variant cost ${format_money(abs(delta))} more per run "
            f"but succeeded no more often ({rates[costlier]:.0%} vs "
            f"{rates[cheaper]:.0%} for {cheaper}; comparison {status})."
        ),
        scope=Scope(project_id=_project_id(ctx, row["benchmark_id"])),
        evidence=[
            EvidenceRef(
                kind="benchmark_run",
                id=row["baseline_run_id"],
                measurement={
                    "variant": "baseline",
                    "costlier": costlier == "baseline",
                    "success_rate": rates["baseline"],
                },
            ),
            EvidenceRef(
                kind="benchmark_run",
                id=row["alternative_run_id"],
                measurement={
                    "variant": "alternative",
                    "costlier": costlier == "alternative",
                    "success_rate": rates["alternative"],
                },
            ),
        ],
        measurements={
            "comparison_id": row["id"],
            "comparison_status": status,
            "cost_delta": float(delta),
            "costlier_variant": costlier,
            "cheaper_variant": cheaper,
            "costlier_success_rate": rates[costlier],
            "cheaper_success_rate": rates[cheaper],
            "low_sample": _low_sample(row["methodology_json"]),
        },
        estimated_impact=None,
        impact_currency=None,
    )
