"""`GET /api/v1/benchmarks/{id}/comparisons`: persisted rows, newest first."""

import json

from fastapi.testclient import TestClient

from tokenpilot.benchmarks.runner import BenchmarkStore
from tokenpilot.config import Settings
from tokenpilot.db.connection import connect
from tokenpilot.schemas.benchmarks import (
    AcceptanceConfig,
    AlternativeSpec,
    RunConfig,
)

BASE_CONFIG = {
    "model_id": "fake-large",
    "context_strategy": "full_repo",
    "max_steps": 12,
    "retry_policy": {"max_retries": 2},
    "temperature": None,
    "prompt_template": "fix_v1",
    "context_files": [],
}
ALT_CONFIG = {**BASE_CONFIG, "context_strategy": "targeted"}


def _seed_benchmark(settings: Settings) -> tuple[str, str, str]:
    conn = connect(settings.db_path)
    try:
        conn.execute(
            "INSERT INTO projects (id, name, default_currency, created_at, updated_at) "
            "VALUES ('p1', 'demo', 'USD', '2026-10-28T00:00:00Z', "
            "'2026-10-28T00:00:00Z')"
        )
        conn.execute(
            "INSERT INTO tasks (id, project_id, title, created_at) "
            "VALUES ('t1', 'p1', 'discount bug', '2026-10-28T00:00:00Z')"
        )
        store = BenchmarkStore(conn)
        benchmark = store.create_benchmark(
            benchmark_id="bench-1",
            project_id="p1",
            task_id="t1",
            name="discount bug",
            description=None,
            initial_git_sha="abc123",
            acceptance=AcceptanceConfig(
                command=["python", "-m", "pytest", "-q"],
                required_pass=["tests/test_discounts.py::test_x"],
                min_success_rate=1.0,
            ),
            baseline=RunConfig.model_validate(BASE_CONFIG),
            alternatives=[
                AlternativeSpec(
                    name="targeted-context",
                    changes={"context_strategy": "targeted"},
                    context_files=["invoicing/discounts.py"],
                )
            ],
            task_prompt="fix the discount bug",
            initial_ref="main",
            repeat_count=1,
            timeout_s=300,
        )
        base_run = store.create_run(
            benchmark.id, "baseline", "fake-large", BASE_CONFIG, 0
        )
        alt_run = store.create_run(
            benchmark.id, "targeted-context", "fake-large", ALT_CONFIG, 0
        )
        conn.commit()
        return benchmark.id, base_run.id, alt_run.id
    finally:
        conn.close()


def _insert_comparison(
    settings: Settings,
    *,
    comparison_id: str,
    benchmark_id: str,
    base_run_id: str,
    alt_run_id: str,
    status: str,
    created_at: str,
) -> None:
    conn = connect(settings.db_path)
    try:
        conn.execute(
            "INSERT INTO benchmark_comparisons (id, benchmark_id, baseline_run_id, "
            "alternative_run_id, cost_delta, cost_delta_pct, correctness_preserved, "
            "comparison_status, methodology_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                comparison_id,
                benchmark_id,
                base_run_id,
                alt_run_id,
                0.18,
                60.0,
                1,
                status,
                json.dumps(
                    {"low_sample": True, "reasons": [f"{status} by test seed"]},
                    sort_keys=True,
                ),
                created_at,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def test_comparisons_returns_rows_newest_first(
    client: TestClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    benchmark_id, base_run_id, alt_run_id = _seed_benchmark(settings)
    _insert_comparison(
        settings,
        comparison_id="cmp-old",
        benchmark_id=benchmark_id,
        base_run_id=base_run_id,
        alt_run_id=alt_run_id,
        status="measured",
        created_at="2026-10-28T00:00:01.000Z",
    )
    _insert_comparison(
        settings,
        comparison_id="cmp-new",
        benchmark_id=benchmark_id,
        base_run_id=base_run_id,
        alt_run_id=alt_run_id,
        status="verified",
        created_at="2026-10-28T00:00:02.000Z",
    )

    response = client.get(
        f"/api/v1/benchmarks/{benchmark_id}/comparisons", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert [row["id"] for row in body] == ["cmp-new", "cmp-old"]
    latest = body[0]
    assert latest["benchmark_id"] == benchmark_id
    assert latest["baseline_variant"] == "baseline"
    assert latest["alternative_variant"] == "targeted-context"
    assert latest["baseline_run_id"] == base_run_id
    assert latest["alternative_run_id"] == alt_run_id
    assert latest["comparison_status"] == "verified"
    assert latest["correctness_preserved"] is True
    assert latest["cost_delta"] == 0.18
    assert latest["methodology"]["low_sample"] is True
    assert latest["reasons"] == ["verified by test seed"]


def test_comparisons_unknown_benchmark_is_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get(
        "/api/v1/benchmarks/does-not-exist/comparisons", headers=auth_headers
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_comparisons_empty_list_when_none(
    client: TestClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    benchmark_id, _, _ = _seed_benchmark(settings)

    response = client.get(
        f"/api/v1/benchmarks/{benchmark_id}/comparisons", headers=auth_headers
    )

    assert response.status_code == 200, response.text
    assert response.json() == []
