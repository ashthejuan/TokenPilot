"""Aggregate metrics over benchmark runs (PRD §11.3).

Every function returns None when there is nothing honest to say — no eligible
runs, no successes, unknown costs — instead of fabricating a number.
"""

import math
import statistics
from collections.abc import Sequence
from decimal import Decimal
from typing import Any

from tokenpilot.schemas.benchmarks import BenchmarkRunOut

_ELIGIBLE_OUTCOMES = ("passed", "failed", "timed_out")


def _eligible(runs: Sequence[BenchmarkRunOut]) -> list[BenchmarkRunOut]:
    """Completed runs that reached a scored outcome (never cancelled/inconclusive)."""
    return [
        run
        for run in runs
        if run.run_status == "completed" and run.outcome in _ELIGIBLE_OUTCOMES
    ]


def success_rate(runs: Sequence[BenchmarkRunOut]) -> float | None:
    """Share of eligible runs with outcome `passed`; None when none are eligible."""
    eligible = _eligible(runs)
    if not eligible:
        return None
    return sum(1 for run in eligible if run.outcome == "passed") / len(eligible)


def cost_per_success(runs: Sequence[BenchmarkRunOut]) -> Decimal | None:
    """Total cost across eligible runs divided by the number of successes.

    None when there are no successes or any eligible run's cost is unknown.
    """
    eligible = _eligible(runs)
    successes = [run for run in eligible if run.outcome == "passed"]
    if not successes:
        return None
    costs: list[Decimal] = []
    for run in eligible:
        if run.total_cost is None:
            return None
        costs.append(run.total_cost)
    return sum(costs, Decimal(0)) / len(successes)


def retry_amplification(runs: Sequence[BenchmarkRunOut]) -> Decimal | None:
    """Total model requests per first attempt, across eligible runs.

    1.0 means no retries; None when no first attempts exist.
    """
    eligible = _eligible(runs)
    first_attempts = sum(run.request_count - run.retry_count for run in eligible)
    if first_attempts <= 0:
        return None
    total_requests = sum(run.request_count for run in eligible)
    return Decimal(total_requests) / Decimal(first_attempts)


def latency_stats(runs: Sequence[BenchmarkRunOut]) -> dict[str, float] | None:
    """Median and nearest-rank p90 of eligible run durations in milliseconds."""
    durations = sorted(
        float(run.duration_ms)
        for run in _eligible(runs)
        if run.duration_ms is not None
    )
    if not durations:
        return None
    rank = min(len(durations) - 1, math.ceil(0.9 * len(durations)) - 1)
    return {"median": float(statistics.median(durations)), "p90": durations[rank]}


def stdev_cost(runs: Sequence[BenchmarkRunOut]) -> Decimal | None:
    """Sample standard deviation of eligible run costs; None with fewer than two."""
    costs = [
        run.total_cost for run in _eligible(runs) if run.total_cost is not None
    ]
    if len(costs) < 2:
        return None
    return statistics.stdev(costs)


def summarize(runs: Sequence[BenchmarkRunOut]) -> dict[str, Any]:
    """All five metrics in one dict for reports and comparisons."""
    return {
        "success_rate": success_rate(runs),
        "cost_per_success": cost_per_success(runs),
        "retry_amplification": retry_amplification(runs),
        "latency_stats": latency_stats(runs),
        "stdev_cost": stdev_cost(runs),
    }
