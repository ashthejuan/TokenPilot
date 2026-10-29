"""Agent loop tests: context strategies, attribution, retries, step bounds."""

import asyncio
import contextlib
import json
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from tokenpilot.benchmarks.agent import run_agent
from tokenpilot.benchmarks.agent_tools import AgentTools
from tokenpilot.config import Settings
from tokenpilot.main import create_app
from tokenpilot.schemas.benchmarks import RunConfig

LOCAL_TOKEN = "test-local-token"
GATEWAY_URL = "http://testserver/gateway/v1"


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


def _config(**overrides: Any) -> RunConfig:
    base: dict[str, Any] = {
        "model_id": "fake-large",
        "context_strategy": "full_repo",
        "max_steps": 8,
        "retry_policy": {"max_retries": 0},
    }
    base.update(overrides)
    return RunConfig.model_validate(base)


def _workspace(tmp_path: Path) -> Path:
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "alpha.py").write_text("ALPHA_MARKER = 1\n")
    (ws / "beta.py").write_text("BETA_MARKER = 2\n")
    (ws / "gamma.py").write_text("GAMMA_MARKER = 3\n")
    (ws / "delta.py").write_text("DELTA_MARKER = 4\n")
    (ws / "epsilon.py").write_text("EPSILON_MARKER = 5\n")
    (ws / "zeta.py").write_text("ZETA_MARKER = 6\n")
    return ws


def _first_user_message(scripted: ScriptedModel) -> str:
    body = json.loads(scripted.requests[0].content.decode("utf-8"))
    assert body["stream"] is not True
    users = [m for m in body["messages"] if m["role"] == "user"]
    assert users, "agent must send a user message"
    content = users[0]["content"]
    assert isinstance(content, str)
    return content


def _seed_run(app: FastAPI, run_id: str) -> None:
    with app.state.db.write() as conn:
        conn.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) "
            "VALUES ('p1', 'p', 't', 't')"
        )
        conn.execute(
            "INSERT INTO benchmarks (id, project_id, name, created_at) "
            "VALUES ('b1', 'p1', 'b', 't')"
        )
        conn.execute(
            "INSERT INTO benchmark_runs (id, benchmark_id, variant_name, run_status) "
            "VALUES (?, 'b1', 'baseline', 'queued')",
            (run_id,),
        )


def test_agent_full_repo_sends_all_files_targeted_sends_subset(
    settings: Settings, tmp_path: Path
) -> None:
    ws = _workspace(tmp_path)

    full_scripted = ScriptedModel([ScriptedModel.stop()])
    with _running(settings, full_scripted) as app:
        result = asyncio.run(
            run_agent(
                "Fix it.",
                _config(context_strategy="full_repo"),
                AgentTools(ws),
                GATEWAY_URL,
                "run-full",
                local_token=LOCAL_TOKEN,
                transport=httpx.ASGITransport(app=app),
            )
        )
    assert result.stopped_reason == "done"
    full_msg = _first_user_message(full_scripted)
    for marker in ("ALPHA", "BETA", "GAMMA", "DELTA", "EPSILON", "ZETA"):
        assert f"{marker}_MARKER" in full_msg

    targeted_scripted = ScriptedModel([ScriptedModel.stop()])
    with _running(settings, targeted_scripted) as app:
        asyncio.run(
            run_agent(
                "Fix it.",
                _config(
                    context_strategy="targeted",
                    context_files=["alpha.py", "beta.py", "gamma.py"],
                ),
                AgentTools(ws),
                GATEWAY_URL,
                "run-targeted",
                local_token=LOCAL_TOKEN,
                transport=httpx.ASGITransport(app=app),
            )
        )
    targeted_msg = _first_user_message(targeted_scripted)
    for marker in ("ALPHA", "BETA", "GAMMA"):
        assert f"{marker}_MARKER" in targeted_msg
    for marker in ("DELTA", "EPSILON", "ZETA"):
        assert f"{marker}_MARKER" not in targeted_msg
    # The targeted prompt still names every file so the model can navigate.
    assert "delta.py" in targeted_msg
    assert len(full_msg) > len(targeted_msg)


def test_agent_usage_attributed_to_run(settings: Settings, tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    scripted = ScriptedModel(
        [
            ScriptedModel.tools(ScriptedModel.call("list_files")),
            ScriptedModel.tools(ScriptedModel.call("done", summary="fixed")),
        ]
    )
    with _running(settings, scripted) as app:
        _seed_run(app, "run-attr")
        result = asyncio.run(
            run_agent(
                "Fix it.",
                _config(),
                AgentTools(ws),
                GATEWAY_URL,
                "run-attr",
                task_id="task-1",
                local_token=LOCAL_TOKEN,
                transport=httpx.ASGITransport(app=app),
            )
        )
        assert result.stopped_reason == "done"
        assert result.steps == 2
        assert len(scripted.requests) == 2
        with app.state.db.read() as conn:
            rows = conn.execute(
                "SELECT benchmark_run_id, session_id FROM usage_events"
            ).fetchall()
            assert len(rows) == 2
            assert {row["benchmark_run_id"] for row in rows} == {"run-attr"}
            session = conn.execute(
                "SELECT external_session_id FROM sessions WHERE id = ?",
                (rows[0]["session_id"],),
            ).fetchone()
            assert session["external_session_id"] == "bench-run-attr"


def test_agent_retries_429_with_retry_of(settings: Settings, tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    scripted = ScriptedModel(
        [
            ScriptedModel.fail(429, "slow down"),
            ScriptedModel.tools(ScriptedModel.call("done", summary="ok")),
        ]
    )
    with _running(settings, scripted) as app:
        _seed_run(app, "run-retry")
        result = asyncio.run(
            run_agent(
                "Fix it.",
                _config(retry_policy={"max_retries": 1}),
                AgentTools(ws),
                GATEWAY_URL,
                "run-retry",
                local_token=LOCAL_TOKEN,
                transport=httpx.ASGITransport(app=app),
            )
        )
        assert result.stopped_reason == "done"
        assert len(scripted.requests) == 2
        with app.state.db.read() as conn:
            rows = conn.execute(
                "SELECT attempt, retry_group_id, retry_source FROM usage_events "
                "ORDER BY started_at, id"
            ).fetchall()
            assert len(rows) == 2
            assert rows[0]["retry_group_id"] == rows[1]["retry_group_id"]
            assert rows[0]["retry_group_id"] is not None
            assert rows[1]["retry_source"] == "explicit"
            assert sorted(row["attempt"] for row in rows) == [1, 2]


def test_agent_max_steps_bounds_loop(settings: Settings, tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    scripted = ScriptedModel(
        [ScriptedModel.tools(ScriptedModel.call("list_files"))] * 6
    )
    with _running(settings, scripted) as app:
        result = asyncio.run(
            run_agent(
                "Fix it.",
                _config(max_steps=3),
                AgentTools(ws),
                GATEWAY_URL,
                "run-steps",
                local_token=LOCAL_TOKEN,
                transport=httpx.ASGITransport(app=app),
            )
        )
    assert result.stopped_reason == "max_steps"
    assert result.steps == 3
    assert len(scripted.requests) == 3


def test_agent_stop_without_tools_ends_run(settings: Settings, tmp_path: Path) -> None:
    ws = _workspace(tmp_path)
    scripted = ScriptedModel([ScriptedModel.stop("I fixed it by hand")])
    with _running(settings, scripted) as app:
        result = asyncio.run(
            run_agent(
                "Fix it.",
                _config(),
                AgentTools(ws),
                GATEWAY_URL,
                "run-stop",
                local_token=LOCAL_TOKEN,
                transport=httpx.ASGITransport(app=app),
            )
        )
    assert result.stopped_reason == "done"
    assert result.steps == 0


def test_agent_unknown_tool_returns_error_result(
    settings: Settings, tmp_path: Path
) -> None:
    ws = _workspace(tmp_path)
    scripted = ScriptedModel(
        [
            ScriptedModel.tools(ScriptedModel.call("run_shell", command="ls")),
            ScriptedModel.tools(ScriptedModel.call("done")),
        ]
    )
    with _running(settings, scripted) as app:
        result = asyncio.run(
            run_agent(
                "Fix it.",
                _config(),
                AgentTools(ws),
                GATEWAY_URL,
                "run-unknown-tool",
                local_token=LOCAL_TOKEN,
                transport=httpx.ASGITransport(app=app),
            )
        )
    assert result.stopped_reason == "done"
    assert len(scripted.requests) == 2
    second = json.loads(scripted.requests[1].content.decode("utf-8"))
    tool_msgs = [m for m in second["messages"] if m["role"] == "tool"]
    assert tool_msgs and "Error" in tool_msgs[0]["content"]
