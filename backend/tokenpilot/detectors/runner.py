"""Run detectors over one loaded context, then upsert every finding at once.

The context is built on the caller's read connection (P5: analysis never holds
the shared `Database` lock); only the final upsert takes `db.write()`, once.
"""

import sqlite3
from dataclasses import dataclass
from datetime import datetime

from tokenpilot.db.database import Database
from tokenpilot.detectors.base import Detector
from tokenpilot.detectors.facts import AnalysisScope, load_context
from tokenpilot.detectors.repeated_request import RepeatedRequestDetector
from tokenpilot.detectors.retry_amplification import RetryAmplificationDetector
from tokenpilot.detectors.thresholds import load_thresholds
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.timeutil import to_utc_z


class UnknownRuleError(ValueError):
    """A requested `rule_id` is not in the registry."""


# Filled as rules land; Task 2.3 completes all 7 `RULE_IDS`.
REGISTRY: dict[str, Detector] = {
    "repeated_request": RepeatedRequestDetector(),
    "retry_amplification": RetryAmplificationDetector(),
}


@dataclass(frozen=True)
class AnalysisResult:
    """What one run stored: row counts plus findings per rule."""

    created: int
    updated: int
    by_rule: dict[str, int]


def run_detectors(
    read_conn: sqlite3.Connection,
    db: Database,
    scope: AnalysisScope,
    rule_ids: list[str] | None,
    now: datetime,
) -> AnalysisResult:
    """Run `rule_ids` (or every registered rule) and upsert the findings."""
    if rule_ids is None:
        selected = list(REGISTRY)
    else:
        unknown = sorted(rule_id for rule_id in rule_ids if rule_id not in REGISTRY)
        if unknown:
            raise UnknownRuleError(f"unknown rule_id(s): {', '.join(unknown)}")
        selected = list(dict.fromkeys(rule_ids))
    ctx = load_context(read_conn, scope, load_thresholds(read_conn), now)
    findings = []
    for rule_id in selected:
        findings.extend(REGISTRY[rule_id].detect(ctx))
    now_z = to_utc_z(now)
    created = 0
    updated = 0
    by_rule: dict[str, int] = {}
    with db.write() as conn:
        repository = InsightRepository(conn)
        for finding in findings:
            if repository.upsert(finding, now_z) == "created":
                created += 1
            else:
                updated += 1
            by_rule[finding.rule_id] = by_rule.get(finding.rule_id, 0) + 1
    return AnalysisResult(created=created, updated=updated, by_rule=by_rule)
