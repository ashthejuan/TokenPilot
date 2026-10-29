"""Task 4.4 verbatim cases: comparison engine, savings classification, Detector G."""

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from tokenpilot.benchmarks.runner import BenchmarkStore
from tokenpilot.db.connection import connect
from tokenpilot.db.migrate import migrate
from tokenpilot.detectors.facts import DetectionContext
from tokenpilot.detectors.model_inefficiency import ModelInefficiencyDetector
from tokenpilot.detectors.thresholds import Thresholds
from tokenpilot.savings.classify import compare, savings_kind
from tokenpilot.schemas.benchmarks import (
    AcceptanceConfig,
    BenchmarkOut,
    BenchmarkRunOut,
    RunConfig,
)

BENCHMARK_ID = "bench-1"
CREATED_AT = "2026-10-28T00:00:00Z"

_baseline_config = {
    "model_id": "fake-large",
    "context_strategy": "full_repo",
    "max_steps": 12,
    "retry_policy": {"max_retries": 2},
    "temperature": None,
    "prompt_template": "fix_v1",
    "context_files": [],
}
_alternative_config = {**_baseline_config, "context_strategy": "targeted"}


def make_benchmark(
    benchmark_id: str = BENCHMARK_ID, min_success_rate: float = 1.0
) -> BenchmarkOut:
    return BenchmarkOut(
        id=benchmark_id,
        project_id="p1",
        task_id="t1",
        name="discount bug",
        description=None,
        initial_git_sha="abc123",
        acceptance=AcceptanceConfig(
            command=["python", "-m", "pytest", "-q"],
            required_pass=["tests/test_discounts.py::test_discount_applied_before_tax"],
            min_success_rate=min_success_rate,
        ),
        baseline=RunConfig.model_validate(_baseline_config),
        alternatives=[],
        task_prompt="fix the discount bug",
        initial_ref="main",
        repeat_count=3,
        timeout_s=300,
        created_at=CREATED_AT,
    )


_run_seq = 0


def make_run(
    benchmark_id: str,
    variant: str,
    cost: Decimal | None,
    outcome: str,
    config: dict | None = None,
) -> BenchmarkRunOut:
    global _run_seq
    _run_seq += 1
    return BenchmarkRunOut(
        id=f"run-{_run_seq:04d}",
        benchmark_id=benchmark_id,
        variant_name=variant,
        model_id="fake-large",
        config=dict(config) if config is not None else dict(_baseline_config),
        run_status="completed",
        outcome=outcome,  # type: ignore[arg-type]
        total_cost=cost,
        currency="USD" if cost is not None else None,
        unknown_cost_events=0,
        total_tokens=1000,
        request_count=5,
        retry_count=0,
        duration_ms=1000,
        test_exit_code=0 if outcome == "passed" else 1,
        test_results=None,
        patch_path=None,
        worktree_path=None,
        started_at=CREATED_AT,
        completed_at=CREATED_AT,
        repeat_index=0,
        error=None,
        eligible=True,
    )


def variant(
    costs: list[Decimal | None],
    outcomes: list[str],
    variant_name: str,
    benchmark_id: str = BENCHMARK_ID,
    config: dict | None = None,
) -> list[BenchmarkRunOut]:
    assert len(costs) == len(outcomes)
    return [
        make_run(benchmark_id, variant_name, cost, outcome, config)
        for cost, outcome in zip(costs, outcomes, strict=True)
    ]


def test_failed_alternative_never_verified() -> None:
    benchmark = make_benchmark()
    baseline = variant(
        [Decimal("0.30"), Decimal("0.32"), Decimal("0.31")],
        ["passed", "passed", "passed"],
        "baseline",
    )
    alternative = variant(
        [Decimal("0.12"), Decimal("0.11"), Decimal("0.13")],
        ["failed", "failed", "failed"],
        "targeted-context",
        config=_alternative_config,
    )

    result = compare(benchmark, baseline, alternative)

    assert result.comparison_status == "measured"
    assert result.correctness_preserved is False
    assert result.cost_delta is not None and result.cost_delta > 0
    assert savings_kind(result) == "benchmark"
    assert result.reasons


def test_cheaper_and_passing_is_verified() -> None:
    benchmark = make_benchmark()
    baseline = variant(
        [Decimal("0.30"), Decimal("0.32"), Decimal("0.31")],
        ["passed", "passed", "passed"],
        "baseline",
    )
    alternative = variant(
        [Decimal("0.12"), Decimal("0.11"), Decimal("0.13")],
        ["passed", "passed", "passed"],
        "targeted-context",
        config=_alternative_config,
    )

    result = compare(benchmark, baseline, alternative)

    assert result.comparison_status == "verified"
    assert result.correctness_preserved is True
    assert result.cost_delta == Decimal("0.19")
    assert result.cost_delta_pct is not None
    assert float(result.cost_delta_pct) == pytest.approx(61.29, abs=0.01)
    assert savings_kind(result) == "verified"
    assert result.methodology["variables_changed"] == ["context_strategy"]
    assert result.methodology["interleaved"] is True


def test_different_sha_incomparable() -> None:
    benchmark = make_benchmark()
    baseline = variant([Decimal("0.30")], ["passed"], "baseline")
    foreign = variant(
        [Decimal("0.12")], ["passed"], "targeted-context", benchmark_id="bench-2"
    )

    result = compare(benchmark, baseline, foreign)

    assert result.comparison_status == "incomparable"
    assert result.correctness_preserved is None
    assert result.cost_delta is None
    assert "different starting revision / acceptance criteria" in result.reasons
    assert savings_kind(result) == "potential"


def test_zero_baseline_cost_pct_undefined() -> None:
    benchmark = make_benchmark()
    baseline = variant(
        [Decimal("0"), Decimal("0")], ["passed", "passed"], "baseline"
    )
    alternative = variant([Decimal("0.10")], ["passed"], "targeted-context")

    result = compare(benchmark, baseline, alternative)

    assert result.cost_delta == Decimal("-0.10")
    assert result.cost_delta_pct is None
    assert result.reasons


def test_single_run_each_verified_but_low_sample() -> None:
    benchmark = make_benchmark()
    baseline = variant([Decimal("0.30")], ["passed"], "baseline")
    alternative = variant([Decimal("0.12")], ["passed"], "targeted-context")

    result = compare(benchmark, baseline, alternative)

    assert result.comparison_status == "verified"
    assert result.methodology["low_sample"] is True
    assert result.methodology["eligible_counts"] == {"baseline": 1, "alternative": 1}


def test_overlapping_costs_n2_not_verified() -> None:
    benchmark = make_benchmark()
    baseline = variant(
        [Decimal("0.30"), Decimal("0.10")], ["passed", "passed"], "baseline"
    )
    alternative = variant(
        [Decimal("0.12"), Decimal("0.20")], ["passed", "passed"], "targeted-context"
    )

    result = compare(benchmark, baseline, alternative)

    assert result.correctness_preserved is True
    assert result.comparison_status == "correctness_preserving"
    assert savings_kind(result) == "benchmark"


def test_unknown_cost_inconclusive() -> None:
    benchmark = make_benchmark()
    baseline = variant([Decimal("0.30")], ["passed"], "baseline")
    alternative = variant([None], ["passed"], "targeted-context")

    result = compare(benchmark, baseline, alternative)

    assert result.comparison_status == "inconclusive"
    assert result.correctness_preserved is None
    assert result.cost_delta is None
    assert savings_kind(result) == "potential"
    assert result.reasons


def test_model_inefficiency_fires_on_costlier_not_better(tmp_path: Path) -> None:
    conn = connect(tmp_path / "tokenpilot.sqlite3")
    try:
        assert migrate(conn) == 3
        conn.execute(
            "INSERT INTO projects (id, name, default_currency, created_at, updated_at) "
            "VALUES ('p1', 'demo', 'USD', ?, ?)",
            (CREATED_AT, CREATED_AT),
        )
        conn.execute(
            "INSERT INTO tasks (id, project_id, title, created_at) "
            "VALUES ('t1', 'p1', 'discount bug', ?)",
            (CREATED_AT,),
        )
        store = BenchmarkStore(conn)
        benchmark = store.create_benchmark(
            benchmark_id=BENCHMARK_ID,
            project_id="p1",
            task_id="t1",
            name="discount bug",
            description=None,
            initial_git_sha="abc123",
            acceptance=make_benchmark().acceptance,
            baseline=make_benchmark().baseline,
            alternatives=[],
            task_prompt="fix the discount bug",
            initial_ref="main",
            repeat_count=1,
            timeout_s=300,
        )
        base_run = store.create_run(
            benchmark.id, "baseline", "fake-large", _baseline_config, 0
        )
        alt_run = store.create_run(
            benchmark.id, "targeted-context", "fake-large", _alternative_config, 0
        )
        methodology = {
            "run_ids": {"baseline": [base_run.id], "alternative": [alt_run.id]},
            "repeat_counts": {"baseline": 3, "alternative": 3},
            "eligible_counts": {"baseline": 3, "alternative": 3},
            "success_rates": {"baseline": 1 / 3, "alternative": 1.0},
            "cost_stdev": {"baseline": 0.01, "alternative": 0.01},
            "low_sample": False,
            "variables_changed": ["context_strategy"],
            "interleaved": True,
        }
        conn.execute(
            "INSERT INTO benchmark_comparisons (id, benchmark_id, baseline_run_id, "
            "alternative_run_id, cost_delta, cost_delta_pct, correctness_preserved, "
            "comparison_status, methodology_json, created_at) "
            "VALUES ('cmp-1', ?, ?, ?, 0.19, 61.29, 0, 'measured', ?, ?)",
            (
                benchmark.id,
                base_run.id,
                alt_run.id,
                json.dumps(methodology),
                CREATED_AT,
            ),
        )
        conn.commit()

        ctx = DetectionContext(
            events=[],
            sessions={},
            tasks={},
            thresholds=Thresholds(),
            now=datetime(2026, 10, 28, 13, 0, 0, tzinfo=UTC),
            conn=conn,
        )
        findings = ModelInefficiencyDetector().detect(ctx)
    finally:
        conn.close()

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "model_inefficiency"
    assert finding.rule_version == 1
    assert finding.severity in ("informational", "low", "medium")
    assert finding.scope.project_id == "p1"
    assert {ref.kind for ref in finding.evidence} == {"benchmark_run"}
    assert finding.measurements["costlier_variant"] == "baseline"
