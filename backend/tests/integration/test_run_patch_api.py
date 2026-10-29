"""`GET /api/v1/benchmark-runs/{id}/patch`: serve the run's exported patch as text."""

from pathlib import Path

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

PATCH_TEXT = (
    "diff --git a/invoicing/discounts.py b/invoicing/discounts.py\n"
    "--- a/invoicing/discounts.py\n"
    "+++ b/invoicing/discounts.py\n"
    "@@ -1 +1 @@\n"
    "-total = subtotal + tax - discount\n"
    "+total = (subtotal - discount) + tax\n"
)


def _seed_run_id(settings: Settings) -> str:
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
        run = store.create_run(benchmark.id, "baseline", "fake-large", BASE_CONFIG, 0)
        conn.commit()
        return run.id
    finally:
        conn.close()


def test_run_patch_serves_text_and_404s_without_patch(
    client: TestClient,
    auth_headers: dict[str, str],
    settings: Settings,
    tmp_path: Path,
) -> None:
    run_id = _seed_run_id(settings)

    missing = client.get(f"/api/v1/benchmark-runs/{run_id}/patch", headers=auth_headers)
    assert missing.status_code == 404

    patch_file = tmp_path / "run.patch"
    patch_file.write_text(PATCH_TEXT, encoding="utf-8")
    conn = connect(settings.db_path)
    try:
        BenchmarkStore(conn).update_run(run_id, patch_path=str(patch_file))
        conn.commit()
    finally:
        conn.close()

    response = client.get(f"/api/v1/benchmark-runs/{run_id}/patch", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"].startswith("text/plain")
    assert response.text == PATCH_TEXT

    unknown = client.get("/api/v1/benchmark-runs/does-not-exist/patch", headers=auth_headers)
    assert unknown.status_code == 404
