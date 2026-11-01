"""Benchmark run metrics: cost-eligible vs scored-eligible (phase 9)."""

from decimal import Decimal

from tokenpilot.benchmarks.metrics import stdev_cost, success_rate
from tokenpilot.schemas.benchmarks import BenchmarkRunOut

CREATED_AT = "2026-10-28T00:00:00Z"
_CONFIG = {
    "model_id": "fake-large",
    "context_strategy": "full_repo",
    "max_steps": 12,
    "retry_policy": {"max_retries": 2},
    "temperature": None,
    "prompt_template": "fix_v1",
    "context_files": [],
}


def _run(outcome: str, cost: Decimal) -> BenchmarkRunOut:
    return BenchmarkRunOut(
        id="run-1",
        benchmark_id="bench-1",
        variant_name="baseline",
        model_id="fake-large",
        config=dict(_CONFIG),
        run_status="completed",
        outcome=outcome,  # type: ignore[arg-type]
        total_cost=cost,
        currency="USD",
        unknown_cost_events=0,
        total_tokens=1000,
        request_count=5,
        retry_count=0,
        duration_ms=1000,
        test_exit_code=None,
        test_results=None,
        patch_path=None,
        worktree_path=None,
        started_at=CREATED_AT,
        completed_at=CREATED_AT,
        repeat_index=0,
        error=None,
        eligible=True,
    )


def test_stdev_cost_includes_observational_runs() -> None:
    runs = [
        _run("observational", Decimal("0.10")),
        _run("observational", Decimal("0.20")),
    ]
    assert stdev_cost(runs) is not None


def test_success_rate_none_when_all_observational() -> None:
    runs = [
        _run("observational", Decimal("0.10")),
        _run("observational", Decimal("0.12")),
    ]
    assert success_rate(runs) is None


def test_success_rate_ignores_observational_in_denominator() -> None:
    passed = _run("passed", Decimal("0.10"))
    passed.id = "run-pass"
    observational = _run("observational", Decimal("0.12"))
    observational.id = "run-obs"
    assert success_rate([passed, observational]) == 1.0
