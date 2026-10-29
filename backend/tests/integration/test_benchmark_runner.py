"""Benchmark runner, run API, worker, and metrics tests."""

import asyncio
import contextlib
import json
import subprocess
import time
import uuid
from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tokenpilot.benchmarks.metrics import (
    cost_per_success,
    latency_stats,
    retry_amplification,
    stdev_cost,
    success_rate,
    summarize,
)
from tokenpilot.benchmarks.runner import (
    BenchmarkStore,
    execute_run,
    parse_pytest_verbose,
)
from tokenpilot.config import Settings
from tokenpilot.db.connection import connect
from tokenpilot.main import create_app
from tokenpilot.schemas.benchmarks import BenchmarkRunOut

LOCAL_TOKEN = "test-local-token"
GATEWAY_URL = "http://testserver/gateway/v1"
AUTH = {"Authorization": f"Bearer {LOCAL_TOKEN}"}
BUGGY = "def add(a, b):\n    return a - b\n"
FIXED = "def add(a, b):\n    return a + b\n"


class ScriptedModel:
    """A scripted chat-completions upstream that issues tool calls like a model."""

    def __init__(
        self,
        script: list[dict[str, Any]],
        *,
        usage: dict[str, Any] | None = None,
        delay_s: float = 0.0,
    ) -> None:
        self._script = list(script)
        self.requests: list[httpx.Request] = []
        self.delay_s = delay_s
        self.usage = dict(usage or {"prompt_tokens": 100, "completion_tokens": 20})
        self._n = 0

    @staticmethod
    def call(name: str, **args: Any) -> dict[str, Any]:
        return {"name": name, "arguments": args}

    @staticmethod
    def tools(*calls: dict[str, Any]) -> dict[str, Any]:
        return {"kind": "tools", "calls": list(calls)}

    @staticmethod
    def stop(text: str = "all done") -> dict[str, Any]:
        return {"kind": "stop", "content": text}

    @staticmethod
    def fail(status: int, message: str = "boom") -> dict[str, Any]:
        return {"kind": "error", "status": status, "message": message}

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.delay_s:
            time.sleep(self.delay_s)
        if request.url.path.endswith("/models"):
            return httpx.Response(200, json={"object": "list", "data": []})
        self._n += 1
        item = self._script.pop(0) if self._script else ScriptedModel.stop("default stop")
        if item["kind"] == "error":
            return httpx.Response(
                item["status"], json={"error": {"message": item["message"]}}
            )
        try:
            model = json.loads(request.content.decode("utf-8")).get("model")
        except (ValueError, UnicodeDecodeError):
            model = None
        calls = []
        if item["kind"] == "tools":
            for i, call in enumerate(item["calls"]):
                calls.append(
                    {
                        "id": f"call-{self._n}-{i}",
                        "type": "function",
                        "function": {
                            "name": call["name"],
                            "arguments": json.dumps(call["arguments"]),
                        },
                    }
                )
        message: dict[str, Any] = {"role": "assistant", "content": item.get("content")}
        if calls:
            message["tool_calls"] = calls
        return httpx.Response(
            200,
            json={
                "id": f"chatcmpl-scripted-{self._n:04d}",
                "object": "chat.completion",
                "model": model or "fake-large",
                "choices": [
                    {
                        "index": 0,
                        "message": message,
                        "finish_reason": "tool_calls" if calls else "stop",
                    }
                ],
                "usage": dict(self.usage),
            },
        )


def _make_app(settings: Settings, scripted: ScriptedModel) -> FastAPI:
    app_settings = Settings(
        _env_file=None,
        local_token=settings.local_token,
        db_path=settings.db_path,
        data_dir=settings.data_dir,
        upstream_api_key=SecretStr("fake-test-key"),
        upstream_provider="fake",
    )
    return create_app(app_settings, upstream_transport=scripted.transport())


@contextlib.contextmanager
def _running(settings: Settings, scripted: ScriptedModel) -> Iterator[FastAPI]:
    app = _make_app(settings, scripted)
    with TestClient(app):
        yield app


def _git(repo: Path, *args: str) -> str:
    out = subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    )
    return out.stdout.strip()


def _make_repo(path: Path, calc_source: str = BUGGY) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    (path / "calc.py").write_text(calc_source)
    tests = path / "tests"
    tests.mkdir(exist_ok=True)
    (tests / "__init__.py").write_text("")
    (tests / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    _git(path, "init", "--initial-branch=main")
    _git(path, "add", "-A")
    _git(
        path,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@t.t",
        "commit",
        "-m",
        "init",
    )
    return path


def _register_project(client: TestClient, repo: Path, name: str = "calc") -> dict[str, Any]:
    response = client.post(
        "/api/v1/projects",
        json={"name": name, "repository_path": str(repo)},
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _benchmark_body(project_id: str, repo: Path, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "project_id": project_id,
        "repository_path": str(repo),
        "name": "fix-add",
        "description": "Fix add()",
        "task_prompt": "Fix add() in calc.py so it returns a + b. Do not change tests.",
        "initial_ref": "main",
        "acceptance": {
            "command": ["python", "-m", "pytest", "-q"],
            "required_pass": ["tests/test_calc.py::test_add"],
            "min_success_rate": 1.0,
        },
        "timeout_s": 60,
        "repeat_count": 1,
        "baseline": {
            "model_id": "fake-large",
            "context_strategy": "full_repo",
            "max_steps": 8,
            "retry_policy": {"max_retries": 0},
        },
        "alternatives": [
            {
                "name": "targeted-context",
                "changes": {"context_strategy": "targeted"},
                "context_files": ["calc.py"],
            }
        ],
    }
    body.update(overrides)
    return body


def _create_benchmark(
    client: TestClient, project_id: str, repo: Path, **overrides: Any
) -> dict[str, Any]:
    response = client.post(
        "/api/v1/benchmarks",
        json=_benchmark_body(project_id, repo, **overrides),
        headers=AUTH,
    )
    assert response.status_code == 201, response.text
    return response.json()


def _fix_script() -> list[dict[str, Any]]:
    return [
        ScriptedModel.tools(ScriptedModel.call("list_files")),
        ScriptedModel.tools(ScriptedModel.call("read_file", path="calc.py")),
        ScriptedModel.tools(ScriptedModel.call("write_file", path="calc.py", content=FIXED)),
        ScriptedModel.tools(ScriptedModel.call("done", summary="fixed")),
    ]


def _run_config(model_id: str = "fake-large", **overrides: Any) -> dict[str, Any]:
    config: dict[str, Any] = {
        "model_id": model_id,
        "context_strategy": "full_repo",
        "max_steps": 8,
        "retry_policy": {"max_retries": 0},
        "temperature": None,
        "prompt_template": "fix_v1",
        "context_files": [],
    }
    config.update(overrides)
    return config


def _execute(
    settings: Settings, app: FastAPI, run_id: str, **kwargs: Any
) -> BenchmarkRunOut:
    conn = connect(settings.db_path)
    try:
        return execute_run(
            conn,
            run_id,
            gateway_url=GATEWAY_URL,
            local_token=LOCAL_TOKEN,
            data_dir=settings.data_dir,
            transport=httpx.ASGITransport(app=app),
            **kwargs,
        )
    finally:
        conn.close()


def test_run_passes_only_when_required_tests_pass(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel(_fix_script())
    app = _make_app(settings, scripted)
    with TestClient(app) as client:
        project = _register_project(client, repo)
        bench = _create_benchmark(client, project["id"], repo)
        conn = connect(settings.db_path)
        try:
            run = BenchmarkStore(conn).create_run(
                bench["id"], "baseline", "fake-large", _run_config(), 0
            )
            conn.commit()
        finally:
            conn.close()
        finished = _execute(settings, app, run.id)

    assert finished.run_status == "completed"
    assert finished.outcome == "passed"
    assert finished.test_exit_code == 0
    assert finished.test_results is not None
    assert finished.test_results["required"] == {"tests/test_calc.py::test_add": "passed"}
    assert finished.request_count == 4
    assert finished.retry_count == 0
    assert finished.total_tokens == 4 * (100 + 20)
    assert finished.total_cost is not None
    assert finished.currency == "USD"
    assert finished.unknown_cost_events == 0
    assert finished.duration_ms is not None
    assert finished.eligible is True
    assert finished.patch_path is not None
    patch = Path(finished.patch_path)
    assert patch.exists()
    assert "return a + b" in patch.read_text()
    assert finished.worktree_path is None
    assert not (settings.data_dir / "worktrees" / run.id).exists()


def _run_out(
    outcome: str | None,
    cost: str | None,
    *,
    status: str = "completed",
    requests: int = 4,
    retries: int = 0,
    duration_ms: int | None = 1000,
) -> BenchmarkRunOut:
    return BenchmarkRunOut(
        id=uuid.uuid4().hex,
        benchmark_id="b1",
        variant_name="baseline",
        model_id="fake-large",
        config={},
        run_status=status,  # type: ignore[arg-type]
        outcome=outcome,  # type: ignore[arg-type]
        total_cost=Decimal(cost) if cost is not None else None,
        currency="USD",
        unknown_cost_events=0,
        total_tokens=480,
        request_count=requests,
        retry_count=retries,
        duration_ms=duration_ms,
        test_exit_code=0,
        test_results=None,
        patch_path=None,
        worktree_path=None,
        started_at=None,
        completed_at=None,
        repeat_index=0,
        error=None,
        eligible=True,
    )


def test_parse_pytest_verbose_maps_outcomes_and_ignores_summary() -> None:
    text = (
        "tests/test_calc.py::test_add SKIPPED (agent was lazy) [100%]\n"
        "tests/test_calc.py::test_sub PASSED [100%]\n"
        "tests/test_calc.py::test_mul FAILED [100%]\n"
        "FAILED tests/test_calc.py::test_mul - assert False\n"
        "1 failed, 1 passed, 1 skipped in 0.50s\n"
    )
    assert parse_pytest_verbose(text) == {
        "tests/test_calc.py::test_add": "skipped",
        "tests/test_calc.py::test_sub": "passed",
        "tests/test_calc.py::test_mul": "failed",
    }


def test_metrics_success_rate_and_cost_per_success() -> None:
    runs = [
        _run_out("passed", "0.10"),
        _run_out("passed", "0.14"),
        _run_out("failed", "0.08"),
    ]
    assert success_rate(runs) == 2 / 3
    assert cost_per_success(runs) == Decimal("0.16")
    assert summarize(runs)["success_rate"] == 2 / 3


def test_metrics_none_when_no_eligible_runs() -> None:
    assert success_rate([]) is None
    assert cost_per_success([]) is None
    cancelled = [_run_out("cancelled", "0.10"), _run_out("inconclusive", "0.10")]
    assert success_rate(cancelled) is None
    assert cost_per_success(cancelled) is None
    assert cost_per_success([_run_out("failed", "0.08")]) is None
    assert cost_per_success([_run_out("passed", None)]) is None


def test_metrics_retry_latency_and_stdev() -> None:
    runs = [
        _run_out("passed", "0.10", requests=4, retries=1, duration_ms=1000),
        _run_out("passed", "0.14", requests=2, retries=0, duration_ms=3000),
    ]
    assert retry_amplification(runs) == Decimal(6) / Decimal(5)
    assert retry_amplification([]) is None
    stats = latency_stats(runs)
    assert stats == {"median": 2000.0, "p90": 3000.0}
    assert latency_stats([]) is None
    assert stdev_cost(runs) is not None
    assert stdev_cost(runs[:1]) is None


def test_create_benchmark_pins_sha_and_links_task(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel([])
    app = _make_app(settings, scripted)
    with TestClient(app) as client:
        project = _register_project(client, repo)
        bench = _create_benchmark(client, project["id"], repo)

        assert bench["initial_git_sha"] == _git(repo, "rev-parse", "HEAD")
        assert bench["task_id"] is not None
        assert bench["baseline"]["model_id"] == "fake-large"
        assert bench["alternatives"][0]["name"] == "targeted-context"
        with app.state.db.read() as conn:
            task = conn.execute(
                "SELECT project_id FROM tasks WHERE id = ?", (bench["task_id"],)
            ).fetchone()
            assert task is not None and task["project_id"] == project["id"]


def test_create_benchmark_idempotency_key_replays(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel([])
    app = _make_app(settings, scripted)
    with TestClient(app) as client:
        project = _register_project(client, repo)
        body = _benchmark_body(project["id"], repo)
        first = client.post(
            "/api/v1/benchmarks", json=body, headers={**AUTH, "Idempotency-Key": "k1"}
        )
        assert first.status_code == 201, first.text
        second = client.post(
            "/api/v1/benchmarks", json=body, headers={**AUTH, "Idempotency-Key": "k1"}
        )
        assert second.status_code == 200, second.text
        assert second.json()["id"] == first.json()["id"]
        third = client.post(
            "/api/v1/benchmarks", json=body, headers={**AUTH, "Idempotency-Key": "k2"}
        )
        assert third.status_code == 201, third.text
        assert third.json()["id"] != first.json()["id"]


def test_create_benchmark_rejects_unknown_project_and_repo_mismatch(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    other = _make_repo(tmp_path / "other")
    scripted = ScriptedModel([])
    app = _make_app(settings, scripted)
    with TestClient(app) as client:
        missing = client.post(
            "/api/v1/benchmarks", json=_benchmark_body("nope", repo), headers=AUTH
        )
        assert missing.status_code == 404

        project = _register_project(client, other)
        mismatch = client.post(
            "/api/v1/benchmarks",
            json=_benchmark_body(project["id"], repo),
            headers=AUTH,
        )
        assert mismatch.status_code == 422

        norepo = client.post(
            "/api/v1/projects", json={"name": "norepo"}, headers=AUTH
        ).json()
        unregistered = client.post(
            "/api/v1/benchmarks",
            json=_benchmark_body(norepo["id"], repo),
            headers=AUTH,
        )
        assert unregistered.status_code == 422

        bad_ref = client.post(
            "/api/v1/benchmarks",
            json=_benchmark_body(project["id"], other, initial_ref="no-such-branch"),
            headers=AUTH,
        )
        assert bad_ref.status_code == 422


def test_list_and_get_benchmark(settings: Settings, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel([])
    app = _make_app(settings, scripted)
    with TestClient(app) as client:
        project = _register_project(client, repo)
        bench = _create_benchmark(client, project["id"], repo)
        listed = client.get("/api/v1/benchmarks", headers=AUTH)
        assert listed.status_code == 200
        assert [b["id"] for b in listed.json()] == [bench["id"]]
        detail = client.get(f"/api/v1/benchmarks/{bench['id']}", headers=AUTH)
        assert detail.status_code == 200
        assert detail.json()["runs"] == []
        missing = client.get("/api/v1/benchmarks/nope", headers=AUTH)
        assert missing.status_code == 404


def test_start_runs_enqueues_interleaved(settings: Settings, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel([])
    app = _make_app(settings, scripted)
    with TestClient(app) as client:
        app.state.benchmark_worker.stop()
        project = _register_project(client, repo)
        bench = _create_benchmark(client, project["id"], repo)
        response = client.post(
            f"/api/v1/benchmarks/{bench['id']}/runs",
            json={"variants": ["baseline", "targeted-context"], "repeat_count": 2},
            headers=AUTH,
        )
        assert response.status_code == 202, response.text
        runs = response.json()
        assert [r["variant_name"] for r in runs] == [
            "baseline",
            "targeted-context",
            "baseline",
            "targeted-context",
        ]
        assert [r["repeat_index"] for r in runs] == [0, 0, 1, 1]
        assert {r["run_status"] for r in runs} == {"queued"}
        targeted = next(r for r in runs if r["variant_name"] == "targeted-context")
        assert targeted["config"]["context_strategy"] == "targeted"
        assert targeted["config"]["context_files"] == ["calc.py"]

        bad_variant = client.post(
            f"/api/v1/benchmarks/{bench['id']}/runs",
            json={"variants": ["nope"]},
            headers=AUTH,
        )
        assert bad_variant.status_code == 422
        missing = client.post(
            "/api/v1/benchmarks/nope/runs",
            json={"variants": ["baseline"]},
            headers=AUTH,
        )
        assert missing.status_code == 404


def test_get_run_and_cancel_queued_runs(settings: Settings, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel([])
    app = _make_app(settings, scripted)
    with TestClient(app) as client:
        app.state.benchmark_worker.stop()
        project = _register_project(client, repo)
        bench = _create_benchmark(client, project["id"], repo)
        runs = client.post(
            f"/api/v1/benchmarks/{bench['id']}/runs",
            json={"variants": ["baseline"], "repeat_count": 2},
            headers=AUTH,
        ).json()
        fetched = client.get(f"/api/v1/benchmark-runs/{runs[0]['id']}", headers=AUTH)
        assert fetched.status_code == 200
        assert fetched.json()["id"] == runs[0]["id"]
        assert client.get("/api/v1/benchmark-runs/nope", headers=AUTH).status_code == 404

        cancelled = client.post(
            f"/api/v1/benchmarks/{bench['id']}/cancel", headers=AUTH
        )
        assert cancelled.status_code == 200, cancelled.text
        assert sorted(cancelled.json()["cancelled_run_ids"]) == sorted(
            r["id"] for r in runs
        )
        for run in runs:
            fetched = client.get(
                f"/api/v1/benchmark-runs/{run['id']}", headers=AUTH
            ).json()
            assert fetched["run_status"] == "completed"
            assert fetched["outcome"] == "cancelled"
        assert (
            client.post("/api/v1/benchmarks/nope/cancel", headers=AUTH).status_code
            == 404
        )
        assert len(scripted.requests) == 0


def test_worker_executes_enqueued_run_to_completion(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel(_fix_script())
    app = _make_app(settings, scripted)
    with TestClient(app) as client:
        project = _register_project(client, repo)
        bench = _create_benchmark(client, project["id"], repo)
        runs = client.post(
            f"/api/v1/benchmarks/{bench['id']}/runs",
            json={"variants": ["baseline"], "repeat_count": 1},
            headers=AUTH,
        ).json()
        run_id = runs[0]["id"]
        deadline = time.monotonic() + 90
        final: dict[str, Any] = {}
        while time.monotonic() < deadline:
            final = client.get(f"/api/v1/benchmark-runs/{run_id}", headers=AUTH).json()
            if final["run_status"] in ("completed", "failed"):
                break
            time.sleep(0.2)
        assert final["run_status"] == "completed", final
        assert final["outcome"] == "passed", final


def test_worker_thread_event_loop_reused_across_entries() -> None:
    from tokenpilot.benchmarks import runner

    async def _probe() -> asyncio.AbstractEventLoop:
        return asyncio.get_running_loop()

    loop1 = runner._run_on_worker_loop(_probe())
    loop2 = runner._run_on_worker_loop(_probe())
    assert loop1 is loop2
    assert not loop1.is_closed()
    loop1.close()
    loop3 = runner._run_on_worker_loop(_probe())
    assert loop3 is not loop1
    assert not loop3.is_closed()


class _LoopAffinityTransport(httpx.AsyncBaseTransport):
    """Simulates a keep-alive pool bound to its first event loop.

    The real upstream HTTP pool holds connections tied to the loop that
    opened them; reuse from a fresh loop fails with `Event loop is closed`.
    The scripted MockTransport has no such affinity, so this wrapper adds
    it back to reproduce the second-sequential-run failure in-process.
    """

    def __init__(self, inner: httpx.AsyncBaseTransport) -> None:
        self._inner = inner
        self._first_loop: asyncio.AbstractEventLoop | None = None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        loop = asyncio.get_running_loop()
        if self._first_loop is None:
            self._first_loop = loop
        elif loop is not self._first_loop:
            raise RuntimeError("Event loop is closed")
        return await self._inner.handle_async_request(request)


def test_sequential_runs_second_is_not_inconclusive(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel(_fix_script() + _fix_script())
    app_settings = Settings(
        _env_file=None,
        local_token=settings.local_token,
        db_path=settings.db_path,
        data_dir=settings.data_dir,
        upstream_api_key=SecretStr("fake-test-key"),
        upstream_provider="fake",
    )
    app = create_app(
        app_settings,
        upstream_transport=_LoopAffinityTransport(scripted.transport()),
    )
    with TestClient(app) as client:
        app.state.benchmark_worker.stop()
        project = _register_project(client, repo)
        bench = _create_benchmark(client, project["id"], repo)
        conn = connect(settings.db_path)
        try:
            run1 = BenchmarkStore(conn).create_run(
                bench["id"], "baseline", "fake-large", _run_config(), 0
            )
            run2 = BenchmarkStore(conn).create_run(
                bench["id"], "baseline", "fake-large", _run_config(), 1
            )
            conn.commit()
        finally:
            conn.close()
        finished1 = _execute(settings, app, run1.id)
        finished2 = _execute(settings, app, run2.id)
    assert finished1.outcome == "passed", finished1
    assert finished2.outcome == "passed", finished2
    assert finished2.outcome != "inconclusive"
