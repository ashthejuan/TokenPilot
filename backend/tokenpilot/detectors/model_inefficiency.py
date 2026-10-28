"""Detector G stub: model inefficiency needs comparable benchmark runs.

Cost differences across unrelated tasks prove nothing, so this rule only
reads `benchmark_comparisons` and returns `[]` while it has no rows. Task
4.4 completes it to fire when the costlier variant's success rate is at or
below the cheaper one's in a `measured`-or-better comparison.
"""

import sqlite3

from tokenpilot.detectors.base import Finding
from tokenpilot.detectors.facts import DetectionContext

RULE_ID = "model_inefficiency"
RULE_VERSION = 1


class ModelInefficiencyDetector:
    """Stub: fires on benchmark comparisons once Task 4.4 completes it."""

    rule_id = RULE_ID
    rule_version = RULE_VERSION
    guidance = (
        "One model spent notably more than another on comparable work. "
        "Compare their success rates on the same benchmark before switching."
    )

    def detect(self, ctx: DetectionContext) -> list[Finding]:
        """No comparable runs, no finding; Task 4.4 adds the firing logic."""
        try:
            row = ctx.conn.execute(
                "SELECT 1 FROM benchmark_comparisons LIMIT 1"
            ).fetchone()
        except sqlite3.OperationalError:
            return []
        if row is None:
            return []
        return []
