"""Tool-calling benchmark agent loop, run through the TokenPilot gateway.

Every model call carries the benchmark attribution headers, so agent usage is
captured by the same ledger path as real work (PRD §11.2 "same categories of
telemetry"). The model's `done` call only ends the loop; scoring happens
separately in :mod:`tokenpilot.benchmarks.runner` from the acceptance tests.
"""

import json
import threading
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from tokenpilot.benchmarks.agent_tools import AgentTools
from tokenpilot.schemas.benchmarks import RunConfig

GATEWAY_RUN_HEADER = "X-TokenPilot-Benchmark-Run"
GATEWAY_TASK_HEADER = "X-TokenPilot-Task"
GATEWAY_SESSION_HEADER = "X-TokenPilot-Session"
GATEWAY_RETRY_OF_HEADER = "X-TokenPilot-Retry-Of"
GATEWAY_EVENT_ID_HEADER = "X-TokenPilot-Event-Id"

PROMPT_TEMPLATES = {
    "fix_v1": (
        "You are a coding agent fixing a bug in the repository checked out in your "
        "workspace. Use list_files to see the files, read_file to read them, and "
        "write_file to edit them. There is no shell: you cannot run commands. "
        "Fix the task described by the user, then call the done tool with a short "
        "summary. Do not change any tests."
    ),
}

_TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "list_files",
            "description": "List all files in the workspace.",
            "parameters": {
                "type": "object",
                "properties": {},
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a workspace file (max 100 KB).",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_file",
            "description": "Write content to a workspace file, creating parents.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["path", "content"],
                "additionalProperties": False,
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "done",
            "description": "End the run with a short summary of what was changed.",
            "parameters": {
                "type": "object",
                "properties": {"summary": {"type": "string"}},
                "additionalProperties": False,
            },
        },
    },
]


class AgentCancelled(Exception):
    """The run's cancel flag was set between agent steps."""


class AgentTimeout(Exception):
    """The agent exceeded its deadline."""


class AgentGatewayError(Exception):
    """The gateway or upstream failed: transport error, 4xx, or retries exhausted."""


class _BadResponse(Exception):
    """The gateway answered 200 with a body that is not a chat completion."""


@dataclass(frozen=True)
class AgentResult:
    steps: int
    stopped_reason: Literal["done", "max_steps", "error"]
    error: str | None = None


def build_first_user_message(
    task_prompt: str, config: RunConfig, tools: AgentTools
) -> str:
    """The opening user message: task plus repo context per `context_strategy`."""
    if config.context_strategy == "targeted":
        listing = "\n".join(f"- {path}" for path in tools.list_files())
        parts = [task_prompt, f"Repository listing:\n{listing}"]
        for path in config.context_files:
            parts.append(f"=== {path} ===\n{tools.read_file(path)}")
        return "\n\n".join(parts)
    parts = [task_prompt, "Repository files (full_repo context):"]
    for path in tools.list_files():
        content = tools.read_file(path)
        if content.startswith("Error: ") or "\x00" in content:
            continue
        parts.append(f"=== {path} ===\n{content}")
    return "\n\n".join(parts)


def _chat_url(gateway_url: str) -> str:
    return gateway_url.rstrip("/") + "/chat/completions"


def _is_retryable(status: int) -> bool:
    return status == 429 or 500 <= status <= 599


def _execute_tool(tools: AgentTools, name: str, arguments: Any) -> str:
    if not isinstance(arguments, dict):
        return "Error: tool arguments must be a JSON object"
    if name == "list_files":
        files = tools.list_files()
        return "\n".join(files) if files else "(no files)"
    if name == "read_file":
        path = arguments.get("path")
        if not isinstance(path, str):
            return "Error: read_file requires a string 'path'"
        return tools.read_file(path)
    if name == "write_file":
        path, content = arguments.get("path"), arguments.get("content")
        if not isinstance(path, str) or not isinstance(content, str):
            return "Error: write_file requires string 'path' and 'content'"
        return tools.write_file(path, content)
    return f"Error: unknown tool {name!r}"


async def run_agent(
    task_prompt: str,
    config: RunConfig,
    tools: AgentTools,
    gateway_url: str,
    run_id: str,
    *,
    task_id: str | None = None,
    local_token: str = "",
    transport: httpx.AsyncBaseTransport | None = None,
    timeout_s: float | None = None,
    cancel: threading.Event | None = None,
) -> AgentResult:
    """Run the tool loop until `done`, `max_steps`, or an infrastructure failure.

    Raises :class:`AgentCancelled`, :class:`AgentTimeout`, or
    :class:`AgentGatewayError`; anything else ends the loop with a result.
    """
    if config.prompt_template not in PROMPT_TEMPLATES:
        raise ValueError(f"unknown prompt_template {config.prompt_template!r}")
    deadline = time.monotonic() + timeout_s if timeout_s is not None else None
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": PROMPT_TEMPLATES[config.prompt_template]},
        {"role": "user", "content": build_first_user_message(task_prompt, config, tools)},
    ]
    steps = 0
    async with httpx.AsyncClient(transport=transport) as client:
        while True:
            if cancel is not None and cancel.is_set():
                raise AgentCancelled(f"run {run_id} cancelled")
            if deadline is not None and time.monotonic() >= deadline:
                raise AgentTimeout(f"run {run_id} exceeded {timeout_s}s")
            try:
                assistant = await _chat(
                    client,
                    gateway_url,
                    run_id,
                    task_id,
                    local_token,
                    config,
                    messages,
                    deadline,
                )
            except _BadResponse as exc:
                return AgentResult(steps=steps, stopped_reason="error", error=str(exc))
            messages.append(assistant)
            calls = assistant.get("tool_calls") or []
            if not calls:
                return AgentResult(steps=steps, stopped_reason="done")
            if not isinstance(calls, list) or any(
                not isinstance(call, dict) for call in calls
            ):
                return AgentResult(
                    steps=steps,
                    stopped_reason="error",
                    error="malformed tool_calls in model response",
                )
            steps += 1
            for call in calls:
                func = call.get("function")
                function = func if isinstance(func, dict) else {}
                name = function.get("name", "")
                if name == "done":
                    return AgentResult(steps=steps, stopped_reason="done")
                try:
                    arguments = json.loads(function.get("arguments", ""))
                except ValueError:
                    arguments = None
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call.get("id", ""),
                        "content": _execute_tool(tools, name, arguments),
                    }
                )
            if steps >= config.max_steps:
                return AgentResult(steps=steps, stopped_reason="max_steps")


async def _chat(
    client: httpx.AsyncClient,
    gateway_url: str,
    run_id: str,
    task_id: str | None,
    local_token: str,
    config: RunConfig,
    messages: list[dict[str, Any]],
    deadline: float | None,
) -> dict[str, Any]:
    """One model call with `retry_policy` retries; transport failures raise."""
    body: dict[str, Any] = {
        "model": config.model_id,
        "messages": messages,
        "tools": _TOOL_DEFINITIONS,
        "stream": False,
    }
    if config.temperature is not None:
        body["temperature"] = config.temperature
    headers = {
        "Authorization": f"Bearer {local_token}",
        GATEWAY_RUN_HEADER: run_id,
        GATEWAY_SESSION_HEADER: f"bench-{run_id}",
    }
    if task_id is not None:
        headers[GATEWAY_TASK_HEADER] = task_id
    attempts = 1 + config.retry_policy.max_retries
    for attempt in range(attempts):
        timeout = _request_timeout(deadline)
        try:
            response = await client.post(
                _chat_url(gateway_url), json=body, headers=headers, timeout=timeout
            )
        except httpx.TimeoutException as exc:
            if deadline is not None and time.monotonic() >= deadline:
                raise AgentTimeout(f"run {run_id} exceeded its deadline") from exc
            raise AgentGatewayError(f"model call timed out: {exc}") from exc
        except httpx.TransportError as exc:
            raise AgentGatewayError(f"gateway unreachable: {exc}") from exc
        if _is_retryable(response.status_code) and attempt + 1 < attempts:
            event_id = response.headers.get(GATEWAY_EVENT_ID_HEADER)
            if event_id:
                headers[GATEWAY_RETRY_OF_HEADER] = event_id
            continue
        if _is_retryable(response.status_code):
            raise AgentGatewayError(
                f"gateway returned {response.status_code} after {attempts} attempts"
            )
        if not 200 <= response.status_code < 300:
            raise AgentGatewayError(f"gateway returned {response.status_code}")
        try:
            payload = response.json()
            choice = payload["choices"][0]["message"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            raise _BadResponse(f"unparseable model response: {exc}") from exc
        if not isinstance(choice, dict):
            raise _BadResponse("model choice message is not an object")
        return {"role": "assistant", **choice}
    raise AssertionError("unreachable: attempts >= 1")


def _request_timeout(deadline: float | None) -> httpx.Timeout:
    """Per-request timeouts, capped by the agent deadline when one is set."""
    if deadline is None:
        return httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
    remaining = max(deadline - time.monotonic(), 0.001)
    return httpx.Timeout(
        connect=min(10.0, remaining),
        read=remaining,
        write=min(30.0, remaining),
        pool=10.0,
    )
