"""The API stays responsive while a benchmark run is busy in the model (NFR)."""

from __future__ import annotations

import subprocess
import threading
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tokenpilot.config import Settings
from tokenpilot.main import create_app

LOCAL_TOKEN = "test-local-token"
AUTH = {"Authorization": f"Bearer {LOCAL_TOKEN}"}
SLEEP_S = 2.0
MAX_LATENCY_S = 0.5


class SleepingModel:
    """A chat upstream that blocks `sleep_s` per request, then stops the agent."""

    def __init__(self, sleep_s: float) -> None:
        self.sleep_s = sleep_s
        self.entered = threading.Event()
        self.calls = 0

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls += 1
        self.entered.set()
        time.sleep(self.sleep_s)
        return httpx.Response(
            200,
            json={
                "id": f"chatcmpl-sleep-{self.calls:04d}",
                "object": "chat.completion",
                "model": "fake-large",
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "done"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 10, "completion_tokens": 5},
            },
        )


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)


def _make_repo(path: Path) -> Path:
    path.mkdir(parents=True)
    (path / "calc.py").write_text("def add(a, b):\n    return a - b\n")
    tests = path / "tests"
    tests.mkdir()
    (tests / "__init__.py").write_text("")
    (tests / "test_calc.py").write_text(
        "from calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"
    )
    _git(path, "init", "--initial-branch=main")
    _git(path, "add", "-A")
    _git(path, "-c", "user.name=t", "-c", "user.email=t@t.t", "commit", "-m", "init")
    return path


def test_api_responsive_during_benchmark(settings: Settings, tmp_path: Path) -> None:
    model = SleepingModel(SLEEP_S)
    app = create_app(
        Settings(
            _env_file=None,
            local_token=SecretStr(LOCAL_TOKEN),
            db_path=settings.db_path,
            data_dir=settings.data_dir,
            upstream_api_key=SecretStr("fake-test-key"),
            upstream_provider="fake",
        ),
        upstream_transport=model.transport(),
    )
    repo = _make_repo(tmp_path / "repo")
    with TestClient(app) as client:
        project = client.post(
            "/api/v1/projects",
            json={"name": "calc", "repository_path": str(repo)},
            headers=AUTH,
        )
        assert project.status_code == 201, project.text
        body: dict[str, Any] = {
            "project_id": project.json()["id"],
            "repository_path": str(repo),
            "name": "fix-add",
            "description": "Fix add()",
            "task_prompt": "Fix add() in calc.py. Do not change tests.",
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
                "max_steps": 4,
                "retry_policy": {"max_retries": 0},
            },
            "alternatives": [],
        }
        created = client.post("/api/v1/benchmarks", json=body, headers=AUTH)
        assert created.status_code == 201, created.text
        started = client.post(
            f"/api/v1/benchmarks/{created.json()['id']}/runs",
            json={"variants": ["baseline"], "repeat_count": 1},
            headers=AUTH,
        )
        assert started.status_code == 202, started.text

        # The run is now blocked inside the (sleeping) fake model.
        assert model.entered.wait(timeout=30), "benchmark never reached the model"
        latencies: list[float] = []
        for _ in range(5):
            begin = time.perf_counter()
            response = client.get("/api/v1/usage/summary", headers=AUTH)
            latencies.append(time.perf_counter() - begin)
            assert response.status_code == 200
            time.sleep(0.1)

        assert max(latencies) < MAX_LATENCY_S, latencies
