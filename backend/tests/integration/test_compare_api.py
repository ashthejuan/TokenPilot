"""`POST /api/v1/benchmarks/{id}/compare`: persist the classification and return it."""

from fastapi.testclient import TestClient

from tokenpilot.benchmarks.runner import BenchmarkStore
from tokenpilot.config import Settings
from tokenpilot.db.connection import connect
from tokenpilot.schemas.benchmarks import (
    AcceptanceConfig,
    AlternativeSpec,
    RunConfig,
)
from tokenpilot.timeutil import utc_now_z

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


def _seed_benchmark(settings: Settings) -> str:
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
        now = utc_now_z()
        store.update_run(
            base_run.id,
            run_status="completed",
            outcome="passed",
            total_cost=0.30,
            completed_at=now,
            eligible=1,
        )
        store.update_run(
            alt_run.id,
            run_status="completed",
            outcome="passed",
            total_cost=0.12,
            completed_at=now,
            eligible=1,
        )
        conn.commit()
        return benchmark.id
    finally:
        conn.close()


def _compare(client: TestClient, auth_headers: dict[str, str], benchmark_id: str) -> dict:
    response = client.post(
        f"/api/v1/benchmarks/{benchmark_id}/compare",
        json={
            "baseline_variant": "baseline",
            "alternative_variant": "targeted-context",
        },
        headers=auth_headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_compare_persists_verified_row_and_returns_it(
    client: TestClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    benchmark_id = _seed_benchmark(settings)

    body = _compare(client, auth_headers, benchmark_id)

    assert body["benchmark_id"] == benchmark_id
    assert body["comparison_status"] == "verified"
    assert body["correctness_preserved"] is True
    assert body["cost_delta"] == 0.18
    assert body["methodology"]["low_sample"] is True
    conn = connect(settings.db_path)
    try:
        rows = conn.execute(
            "SELECT baseline_run_id, alternative_run_id, cost_delta, "
            "comparison_status, methodology_json "
            "FROM benchmark_comparisons WHERE benchmark_id = ?",
            (benchmark_id,),
        ).fetchall()
    finally:
        conn.close()
    assert len(rows) == 1
    assert rows[0]["comparison_status"] == "verified"
    assert rows[0]["cost_delta"] == 0.18
    assert body["baseline_run_id"] == rows[0]["baseline_run_id"]
    assert body["alternative_run_id"] == rows[0]["alternative_run_id"]


def test_compare_unknown_benchmark_is_404(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        "/api/v1/benchmarks/does-not-exist/compare",
        json={"baseline_variant": "baseline", "alternative_variant": "x"},
        headers=auth_headers,
    )

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_compare_unknown_variant_is_404(
    client: TestClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    benchmark_id = _seed_benchmark(settings)

    response = client.post(
        f"/api/v1/benchmarks/{benchmark_id}/compare",
        json={"baseline_variant": "baseline", "alternative_variant": "nope"},
        headers=auth_headers,
    )

    assert response.status_code == 404


def test_compare_same_variant_is_422(
    client: TestClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    benchmark_id = _seed_benchmark(settings)

    response = client.post(
        f"/api/v1/benchmarks/{benchmark_id}/compare",
        json={"baseline_variant": "baseline", "alternative_variant": "baseline"},
        headers=auth_headers,
    )

    assert response.status_code == 422


def test_compare_requires_token(client: TestClient) -> None:
    response = client.post(
        "/api/v1/benchmarks/bench-1/compare",
        json={"baseline_variant": "baseline", "alternative_variant": "x"},
    )

    assert response.status_code == 401
