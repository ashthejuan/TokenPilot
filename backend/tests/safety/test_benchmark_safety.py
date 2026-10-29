"""Benchmark safety tests (PRD §15.3): timeouts, scoring, cost honesty, cancel."""

import contextlib
import json
import subprocess
import threading
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tokenpilot.benchmarks.runner import (
    INTERRUPTED_BY_RESTART,
    BenchmarkStore,
    execute_run,
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
def _running(
    settings: Settings, scripted: ScriptedModel
) -> Iterator[tuple[FastAPI, TestClient]]:
    app = _make_app(settings, scripted)
    with TestClient(app) as client:
        yield app, client


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


def _seed_benchmark(
    app: FastAPI,
    client: TestClient,
    repo: Path,
    *,
    timeout_s: int = 60,
    command: list[str] | None = None,
    model_id: str = "fake-large",
) -> tuple[str, str]:
    """Register project + benchmark + one queued run via the API. Returns ids."""
    project = client.post(
        "/api/v1/projects",
        json={"name": "calc", "repository_path": str(repo)},
        headers=AUTH,
    ).json()
    bench_response = client.post(
        "/api/v1/benchmarks",
        json={
            "project_id": project["id"],
            "repository_path": str(repo),
            "name": "fix-add",
            "task_prompt": "Fix add().",
            "initial_ref": "main",
            "acceptance": {
                "command": command or ["python", "-m", "pytest", "-q"],
                "required_pass": ["tests/test_calc.py::test_add"],
                "min_success_rate": 1.0,
            },
            "timeout_s": timeout_s,
            "repeat_count": 1,
            "baseline": {
                "model_id": model_id,
                "context_strategy": "full_repo",
                "max_steps": 8,
                "retry_policy": {"max_retries": 0},
            },
            "alternatives": [],
        },
        headers=AUTH,
    )
    assert bench_response.status_code == 201, bench_response.text
    bench = bench_response.json()
    conn = connect(app.state.settings.db_path)
    try:
        run = BenchmarkStore(conn).create_run(
            bench["id"],
            "baseline",
            model_id,
            {
                "model_id": model_id,
                "context_strategy": "full_repo",
                "max_steps": 8,
                "retry_policy": {"max_retries": 0},
                "temperature": None,
                "prompt_template": "fix_v1",
                "context_files": [],
            },
            0,
        )
        conn.commit()
    finally:
        conn.close()
    return bench["id"], run.id


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


def test_timeout_never_recorded_as_passed(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo", FIXED)
    scripted = ScriptedModel(
        [ScriptedModel.tools(ScriptedModel.call("done", summary="nothing to do"))]
    )
    with _running(settings, scripted) as (app, client):
        app.state.benchmark_worker.stop()
        _, run_id = _seed_benchmark(
            app,
            client,
            repo,
            timeout_s=1,
            command=["python", "-c", "import time; time.sleep(30)"],
        )
        finished = _execute(settings, app, run_id)
    assert finished.outcome == "timed_out"
    assert finished.run_status == "completed"
    assert finished.test_exit_code is None


def test_agent_timeout_marks_timed_out(settings: Settings, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo", FIXED)
    scripted = ScriptedModel(
        [ScriptedModel.tools(ScriptedModel.call("list_files"))] * 50,
        delay_s=0.2,
    )
    with _running(settings, scripted) as (app, client):
        app.state.benchmark_worker.stop()
        _, run_id = _seed_benchmark(app, client, repo, timeout_s=1)
        finished = _execute(settings, app, run_id)
    assert finished.outcome == "timed_out"
    assert finished.run_status == "completed"


def test_model_claims_done_but_tests_fail_is_failed(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel(
        [ScriptedModel.tools(ScriptedModel.call("done", summary="fixed, trust me"))]
    )
    with _running(settings, scripted) as (app, client):
        app.state.benchmark_worker.stop()
        _, run_id = _seed_benchmark(app, client, repo)
        finished = _execute(settings, app, run_id)
    assert finished.outcome == "failed"
    assert finished.run_status == "completed"
    assert finished.test_exit_code != 0
    assert finished.test_results is not None
    assert finished.test_results["required"] == {"tests/test_calc.py::test_add": "failed"}


def test_required_test_missing_is_failed(settings: Settings, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel(
        [
            ScriptedModel.tools(
                ScriptedModel.call("write_file", path="calc.py", content=FIXED),
                ScriptedModel.call(
                    "write_file", path="tests/test_calc.py", content="# wiped\n"
                ),
            ),
            ScriptedModel.tools(ScriptedModel.call("done", summary="cleaned up")),
        ]
    )
    with _running(settings, scripted) as (app, client):
        app.state.benchmark_worker.stop()
        _, run_id = _seed_benchmark(app, client, repo)
        finished = _execute(settings, app, run_id)
    assert finished.outcome == "failed"
    assert finished.test_results is not None
    assert finished.test_results["required"] == {"tests/test_calc.py::test_add": "missing"}


def test_unknown_cost_event_makes_total_cost_null(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel(
        [
            ScriptedModel.tools(
                ScriptedModel.call("write_file", path="calc.py", content=FIXED)
            ),
            ScriptedModel.tools(ScriptedModel.call("done", summary="fixed")),
        ]
    )
    with _running(settings, scripted) as (app, client):
        app.state.benchmark_worker.stop()
        # Provider `fake` has no pricing for this model id, so every event is unpriced.
        _, run_id = _seed_benchmark(app, client, repo, model_id="muse-spark-1.3")
        finished = _execute(settings, app, run_id)
    assert finished.outcome == "passed"
    assert finished.total_cost is None
    assert finished.currency is None
    assert finished.unknown_cost_events == finished.request_count == 2


def test_interrupted_run_marked_inconclusive_on_restart(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo")
    scripted = ScriptedModel([])
    with _running(settings, scripted) as (app, client):
        app.state.benchmark_worker.stop()
        _, run_id = _seed_benchmark(app, client, repo)
        conn = connect(settings.db_path)
        try:
            BenchmarkStore(conn).update_run(run_id, run_status="running")
            conn.commit()
        finally:
            conn.close()

    # A fresh process recovers the run left behind by the dead one.
    scripted2 = ScriptedModel([])
    app2 = _make_app(settings, scripted2)
    with TestClient(app2), app2.state.db.read() as conn:
        recovered = BenchmarkStore(conn).get_run(run_id)
    assert recovered is not None
    assert recovered.run_status == "failed"
    assert recovered.outcome == "inconclusive"
    assert recovered.error == INTERRUPTED_BY_RESTART


def test_cancel_stops_run_and_marks_cancelled(
    settings: Settings, tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path / "repo", FIXED)
    scripted = ScriptedModel(
        [ScriptedModel.tools(ScriptedModel.call("list_files"))] * 100,
        delay_s=0.02,
    )
    with _running(settings, scripted) as (app, client):
        app.state.benchmark_worker.stop()
        _, run_id = _seed_benchmark(app, client, repo)
        cancel = threading.Event()
        outcome: dict[str, Any] = {}

        def target() -> None:
            outcome["run"] = _execute(settings, app, run_id, cancel=cancel)

        thread = threading.Thread(target=target)
        thread.start()
        try:
            deadline = time.monotonic() + 30
            while len(scripted.requests) < 3 and time.monotonic() < deadline:
                time.sleep(0.02)
            assert len(scripted.requests) >= 3, "agent never started"
            cancel.set()
            thread.join(timeout=60)
            assert not thread.is_alive(), "run did not stop after cancel"
        finally:
            cancel.set()
            thread.join(timeout=60)
    finished: BenchmarkRunOut = outcome["run"]
    assert finished.outcome == "cancelled"
    assert finished.run_status == "completed"
    assert len(scripted.requests) < 100


def test_gateway_down_marks_inconclusive(settings: Settings, tmp_path: Path) -> None:
    repo = _make_repo(tmp_path / "repo", FIXED)

    def _down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("gateway is down", request=request)

    scripted = ScriptedModel([])
    app = _make_app(settings, scripted)
    with TestClient(app) as client:
        app.state.benchmark_worker.stop()
        _, run_id = _seed_benchmark(app, client, repo)
        conn = connect(settings.db_path)
        try:
            finished = execute_run(
                conn,
                run_id,
                gateway_url=GATEWAY_URL,
                local_token=LOCAL_TOKEN,
                data_dir=settings.data_dir,
                transport=httpx.MockTransport(_down),
            )
        finally:
            conn.close()
    assert finished.outcome == "inconclusive"
    assert finished.run_status == "failed"
    assert finished.error is not None
