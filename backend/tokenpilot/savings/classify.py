"""Comparison engine and savings classification (Task 4.4, PRD FR-11).

`compare` classifies one baseline-vs-alternative pair over the runs of a
single benchmark. Rules apply in order; the first match decides:

1. Any run from another benchmark → `incomparable` (different revision /
   acceptance / task, which are all pinned at the benchmark level).
2. Fewer than 1 eligible run per variant, or any eligible run with unknown
   cost → `inconclusive`.
3. Otherwise `S = Cb - Ca` over mean eligible-run costs, `S% = S/Cb*100`
   (`None` when `Cb == 0`).
4. `correctness_preserved = rate(alt) ≥ rate(base) and rate(alt) ≥ min_rate`.
5. `verified` iff correctness holds, `S > 0`, and either the cost ranges
   separate (`max(alt) < min(base)`) or (n ≥ 3 eligible per variant with the
   alternative's mean and median both lower).
6. Correctness holds but rule 5 fails → `correctness_preserving`.
7. Otherwise → `measured`: the cost was recorded but correctness was not
   preserved. Never called an optimization.

Rates and cost spread come from `benchmarks.metrics`; this module never
reimplements them. All money math is `Decimal`; the `methodology` dict is
kept JSON-safe (floats, never Decimals) so it can persist verbatim.
"""

from __future__ import annotations

import statistics
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tokenpilot.benchmarks.metrics import stdev_cost, success_rate
from tokenpilot.schemas.benchmarks import BenchmarkOut, BenchmarkRunOut
from tokenpilot.schemas.common import Money

ComparisonStatus = Literal[
    "incomparable", "measured", "correctness_preserving", "verified", "inconclusive"
]
SavingsKind = Literal["potential", "benchmark", "verified", "realized"]

INCOMPARABLE_REASON = "different starting revision / acceptance criteria"

_ELIGIBLE_OUTCOMES = ("passed", "failed", "timed_out")

_MISSING = object()


class Comparison(BaseModel):
    """One classified variant pair: the deltas plus how they were derived."""

    model_config = ConfigDict(extra="forbid")

    cost_delta: Money | None = Field(default=None)
    cost_delta_pct: Decimal | None = Field(default=None)
    correctness_preserved: bool | None = Field(default=None)
    comparison_status: ComparisonStatus
    methodology: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


def _eligible_runs(runs: list[BenchmarkRunOut]) -> list[BenchmarkRunOut]:
    """Completed runs with a scored outcome. Same rule as `metrics._eligible`:
    cancelled/inconclusive runs never enter means, rates, or spread."""
    return [
        run
        for run in runs
        if run.run_status == "completed" and run.outcome in _ELIGIBLE_OUTCOMES
    ]


def _merged_config(runs: list[BenchmarkRunOut]) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for run in runs:
        merged.update(run.config or {})
    return merged


def _variables_changed(
    baseline: list[BenchmarkRunOut], alternative: list[BenchmarkRunOut]
) -> list[str]:
    """Sorted config keys whose merged baseline-vs-alternative values differ."""
    base = _merged_config(baseline)
    alt = _merged_config(alternative)
    return sorted(
        key
        for key in set(base) | set(alt)
        if base.get(key, _MISSING) != alt.get(key, _MISSING)
    )


def _stdev_float(runs: list[BenchmarkRunOut]) -> float | None:
    stdev = stdev_cost(runs)
    return None if stdev is None else float(stdev)


def _methodology(
    baseline: list[BenchmarkRunOut], alternative: list[BenchmarkRunOut]
) -> dict[str, Any]:
    eligible_base = _eligible_runs(baseline)
    eligible_alt = _eligible_runs(alternative)
    return {
        "run_ids": {
            "baseline": [run.id for run in baseline],
            "alternative": [run.id for run in alternative],
        },
        "repeat_counts": {"baseline": len(baseline), "alternative": len(alternative)},
        "eligible_counts": {
            "baseline": len(eligible_base),
            "alternative": len(eligible_alt),
        },
        "success_rates": {
            "baseline": success_rate(baseline),
            "alternative": success_rate(alternative),
        },
        "cost_stdev": {
            "baseline": _stdev_float(baseline),
            "alternative": _stdev_float(alternative),
        },
        "low_sample": len(eligible_base) < 3 or len(eligible_alt) < 3,
        "variables_changed": _variables_changed(baseline, alternative),
        "interleaved": True,
    }


def _mean(costs: list[Decimal]) -> Decimal:
    return sum(costs, Decimal(0)) / len(costs)


def compare(
    benchmark: BenchmarkOut,
    baseline: list[BenchmarkRunOut],
    alternative: list[BenchmarkRunOut],
) -> Comparison:
    """Classify one variant pair. The methodology is always populated, even
    when the pair cannot be compared, so callers can show why."""
    methodology = _methodology(baseline, alternative)

    # Rule 1: every run must belong to this benchmark's revision/acceptance/task.
    foreign = [
        run
        for run in (*baseline, *alternative)
        if run.benchmark_id != benchmark.id
    ]
    if foreign:
        return Comparison(
            comparison_status="incomparable",
            methodology=methodology,
            reasons=[
                INCOMPARABLE_REASON,
                f"{len(foreign)} run(s) belong to another benchmark",
            ],
        )

    # Rule 2: need scored runs with known costs on both sides.
    eligible_base = _eligible_runs(baseline)
    eligible_alt = _eligible_runs(alternative)
    if not eligible_base or not eligible_alt:
        return Comparison(
            comparison_status="inconclusive",
            methodology=methodology,
            reasons=[
                "fewer than 1 eligible run per variant "
                f"(baseline {len(eligible_base)}, "
                f"alternative {len(eligible_alt)})"
            ],
        )
    unknown = sum(
        1
        for run in (*eligible_base, *eligible_alt)
        if run.total_cost is None
    )
    if unknown:
        return Comparison(
            comparison_status="inconclusive",
            methodology=methodology,
            reasons=[f"{unknown} eligible run(s) with unknown cost"],
        )

    # Rule 3: FR-11 means over eligible runs only.
    base_costs = [
        cost for run in eligible_base if (cost := run.total_cost) is not None
    ]
    alt_costs = [
        cost for run in eligible_alt if (cost := run.total_cost) is not None
    ]
    assert len(base_costs) == len(eligible_base)
    assert len(alt_costs) == len(eligible_alt)
    mean_base = _mean(base_costs)
    mean_alt = _mean(alt_costs)
    delta = mean_base - mean_alt
    delta_pct = None if mean_base == 0 else delta / mean_base * 100

    # Rule 4: the correctness gate.
    rates = methodology["success_rates"]
    rate_base = rates["baseline"]
    rate_alt = rates["alternative"]
    minimum = benchmark.acceptance.min_success_rate
    assert rate_base is not None and rate_alt is not None  # eligible runs exist
    correctness = rate_alt >= rate_base and rate_alt >= minimum

    reasons = [
        f"mean cost baseline {mean_base}, alternative {mean_alt}",
        f"success rate baseline {rate_base:.3f}, alternative {rate_alt:.3f}, "
        f"minimum {minimum:.3f}",
    ]

    # Rule 5: verified needs separation (or n ≥ 3 with lower mean and median).
    if correctness and delta > 0:
        separated = max(alt_costs) < min(base_costs)
        large_sample = (
            len(eligible_base) >= 3
            and len(eligible_alt) >= 3
            and mean_alt < mean_base
            and statistics.median(alt_costs) < statistics.median(base_costs)
        )
        if separated or large_sample:
            reasons.append(
                "alternative costs strictly below baseline costs"
                if separated
                else "n >= 3 per variant with lower alternative mean and median"
            )
            return Comparison(
                cost_delta=delta,
                cost_delta_pct=delta_pct,
                correctness_preserved=True,
                comparison_status="verified",
                methodology=methodology,
                reasons=reasons,
            )
        # Rule 6: correct but not separated enough to verify.
        reasons.append(
            "correctness preserved but cost ranges overlap "
            "(and n < 3 per variant or medians not both lower)"
        )
        return Comparison(
            cost_delta=delta,
            cost_delta_pct=delta_pct,
            correctness_preserved=True,
            comparison_status="correctness_preserving",
            methodology=methodology,
            reasons=reasons,
        )
    if correctness:
        # Rule 6: correct but the alternative is not cheaper (S <= 0).
        reasons.append("correctness preserved but no positive savings (S <= 0)")
        return Comparison(
            cost_delta=delta,
            cost_delta_pct=delta_pct,
            correctness_preserved=True,
            comparison_status="correctness_preserving",
            methodology=methodology,
            reasons=reasons,
        )
    # Rule 7: cheaper-or-not, correctness failed — measured, never an optimization.
    if rate_alt < rate_base:
        reasons.append(
            f"correctness not preserved: alternative {rate_alt:.3f} "
            f"below baseline {rate_base:.3f}"
        )
    else:
        reasons.append(
            f"correctness not preserved: alternative {rate_alt:.3f} "
            f"below acceptance minimum {minimum:.3f}"
        )
    return Comparison(
        cost_delta=delta,
        cost_delta_pct=delta_pct,
        correctness_preserved=False,
        comparison_status="measured",
        methodology=methodology,
        reasons=reasons,
    )


def savings_kind(item: object) -> SavingsKind:
    """FR-11 savings ladder. Insights are untested (`potential`); comparisons
    map by status; `realized` is never produced in the MVP."""
    if isinstance(item, Comparison):
        if item.comparison_status == "verified":
            return "verified"
        if item.comparison_status in ("measured", "correctness_preserving"):
            return "benchmark"
        return "potential"
    return "potential"
