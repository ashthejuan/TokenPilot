"""A fake OpenAI-compatible upstream for gateway tests and manual runs.

Tests use :class:`FakeUpstream` with ``httpx.MockTransport``: enqueue one
behavior per expected request and inspect ``requests`` afterwards. When the
queue is empty the fake answers ``ok`` with a small default usage, so
fire-and-forget tests (concurrency, auth) need no setup. Every chat response
carries a unique ``id`` so gateway events never dedup against each other.

Manual runs: ``python -m tests.fakes.fake_upstream --port 8799`` serves the
same behaviors over HTTP. The default is ``ok`` with usage; the
``X-Fake-Behavior`` header picks another (``ok``, ``stream``, ``error``,
``html``, ``timeout``, ``reset``).

Demo / offline benchmarks: tool-calling agent requests get a scripted
invoicing fix (list_files → read_file → write_file → done). Usage scales with
full_repo vs targeted prompts. ``TOKENPILOT_FAKE_DEMO_SCENARIO`` or header
``X-Fake-Demo-Scenario`` selects ``success`` (both variants fix) or
``fail-alt`` (targeted write fails acceptance while full_repo still passes).
"""

from __future__ import annotations

import argparse
import itertools
import json
import os
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx

DEFAULT_OK_USAGE: dict[str, Any] = {"prompt_tokens": 10, "completion_tokens": 5}
DEFAULT_MODEL = "fake-large"
FULL_REPO_USAGE: dict[str, Any] = {"prompt_tokens": 80_000, "completion_tokens": 200}
TARGETED_USAGE: dict[str, Any] = {"prompt_tokens": 8_000, "completion_tokens": 200}

# Sticky demo scenario for the HTTP server (env seeds it; header can override).
_DEMO_SCENARIO_LOCK = threading.Lock()
_DEMO_SCENARIO = os.environ.get("TOKENPILOT_FAKE_DEMO_SCENARIO", "success").strip() or "success"

_FIXED_APPLY_DISCOUNT = '''\
def apply_discount(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal,
    tax_rate_percent: int | float | str | Decimal,
) -> int:
    """Return the final total after discount and tax, in cents.

    Intended behaviour (discount before tax):

    * discount the subtotal first,
    * charge percentage tax on the discounted subtotal,
    * add the flat levy in full.

    For a $100.00 subtotal with a 20% discount and 10% tax the
    intended total is $80.00 + $8.00 tax + $12.00 levy = $100.00
    (10_000 cents). ``invoicing.totals.invoice_total`` implements
    the same calculation and the two must agree.
    """
    _validate_subtotal(subtotal_cents)
    _validate_discount_percent(discount_percent)
    discounted = discounted_subtotal(subtotal_cents, discount_percent)
    return discounted + compute_total_tax(discounted, tax_rate_percent)
'''

_BUGGY_APPLY_DISCOUNT = '''\
def apply_discount(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal,
    tax_rate_percent: int | float | str | Decimal,
) -> int:
    """Return the final total after discount and tax, in cents."""
    _validate_subtotal(subtotal_cents)
    _validate_discount_percent(discount_percent)
    # Intentionally wrong for fail-alt honesty scenario.
    taxed_total = subtotal_cents + compute_total_tax(
        subtotal_cents, tax_rate_percent
    )
    return taxed_total - discount_amount(taxed_total, discount_percent)
'''

_FIXED_DISCOUNTS_FILE = '''\
"""Percentage discounts for the invoicing fixture.

All money is integer cents. The discount helpers in this module
come in two flavours:

* :func:`discount_amount` and :func:`discounted_subtotal` work
  purely on a subtotal and know nothing about tax.
* :func:`apply_discount` returns the final amount a customer
  pays for a subtotal once a percentage discount and tax are
  both taken into account.

Correct order of operations for :func:`apply_discount`
------------------------------------------------------
1. Take the percentage discount off the subtotal.
2. Charge percentage tax on the *discounted* subtotal.
3. Add the flat per-invoice levy in full.

The levy (see ``invoicing.tax.FLAT_LEVY_CENTS``) is not part of
the price of the goods, so a discount must never reduce it, and
the percentage tax must be worked out on the discounted price,
not on the original subtotal.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from invoicing.tax import compute_total_tax


def _validate_subtotal(subtotal_cents: int) -> None:
    if subtotal_cents < 0:
        raise ValueError("subtotal_cents must be non-negative")


def _validate_discount_percent(
    discount_percent: int | float | str | Decimal,
) -> Decimal:
    rate = (
        discount_percent
        if isinstance(discount_percent, Decimal)
        else Decimal(str(discount_percent))
    )
    if rate < 0 or rate > 100:
        raise ValueError("discount percent must be between 0 and 100")
    return rate


def discount_amount(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal,
) -> int:
    """Return how many cents a percentage discount removes."""
    _validate_subtotal(subtotal_cents)
    rate = _validate_discount_percent(discount_percent)
    exact = (Decimal(subtotal_cents) * rate) / Decimal("100")
    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def discounted_subtotal(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal,
) -> int:
    """Return the subtotal after a percentage discount, in cents."""
    return subtotal_cents - discount_amount(subtotal_cents, discount_percent)


''' + _FIXED_APPLY_DISCOUNT

_BUGGY_DISCOUNTS_FILE = '''\
"""Percentage discounts for the invoicing fixture (intentionally broken)."""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from invoicing.tax import compute_total_tax


def _validate_subtotal(subtotal_cents: int) -> None:
    if subtotal_cents < 0:
        raise ValueError("subtotal_cents must be non-negative")


def _validate_discount_percent(
    discount_percent: int | float | str | Decimal,
) -> Decimal:
    rate = (
        discount_percent
        if isinstance(discount_percent, Decimal)
        else Decimal(str(discount_percent))
    )
    if rate < 0 or rate > 100:
        raise ValueError("discount percent must be between 0 and 100")
    return rate


def discount_amount(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal,
) -> int:
    _validate_subtotal(subtotal_cents)
    rate = _validate_discount_percent(discount_percent)
    exact = (Decimal(subtotal_cents) * rate) / Decimal("100")
    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def discounted_subtotal(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal,
) -> int:
    return subtotal_cents - discount_amount(subtotal_cents, discount_percent)


''' + _BUGGY_APPLY_DISCOUNT


@dataclass
class Behavior:
    kind: str
    status: int = 200
    body: dict[str, Any] | bytes | str | None = None
    usage: dict[str, Any] | None = None
    chunks: list[str] = field(default_factory=list)
    after_chunks: int = 0
    text: str = ""


def ok(usage: dict[str, Any] | None = None) -> Behavior:
    """200 JSON chat completion. ``usage=None`` omits the usage field."""
    return Behavior(kind="ok", usage=usage)


def error(status: int, body: dict[str, Any] | bytes | str) -> Behavior:
    """An upstream error status with the body relayed verbatim."""
    return Behavior(kind="error", status=status, body=body)


def timeout() -> Behavior:
    """Raise ``httpx.ConnectTimeout`` instead of responding."""
    return Behavior(kind="timeout")


def stream(chunks: list[str], usage: dict[str, Any] | None = None) -> Behavior:
    """SSE stream: each string becomes one ``data:`` line, then an optional
    final usage chunk, then ``data: [DONE]``.

    On ``/responses`` paths the final usage chunk uses a ``resp-fake-…`` id and
    ``input_tokens``/``output_tokens`` (chat keys are remapped). Chat paths keep
    ``chatcmpl-fake-…`` ids and the usage dict as enqueued.
    """
    return Behavior(kind="stream", chunks=list(chunks), usage=usage)


def reset_mid_stream(after_chunks: int) -> Behavior:
    """Yield ``after_chunks`` SSE deltas, then raise ``httpx.ConnectError``."""
    return Behavior(kind="reset", after_chunks=after_chunks)


def html(status: int, text: str) -> Behavior:
    """A non-JSON (proxy-style HTML) error body."""
    return Behavior(kind="html", status=status, text=text)


def _requested_model(request: httpx.Request) -> str:
    try:
        model = json.loads(request.content.decode("utf-8")).get("model")
    except (ValueError, UnicodeDecodeError, AttributeError):
        return DEFAULT_MODEL
    return model if isinstance(model, str) and model else DEFAULT_MODEL


def _sse_line(payload: str) -> bytes:
    return f"data: {payload}\n\n".encode()


class FakeUpstream:
    """Queued-behavior fake. One ``enqueue`` per expected request."""

    def __init__(self) -> None:
        self._behaviors: list[Behavior] = []
        self.requests: list[httpx.Request] = []
        self._ids = itertools.count(1)

    def enqueue(self, behavior: Behavior) -> None:
        self._behaviors.append(behavior)

    def enqueue_investigation(
        self, content: dict[str, Any], *, usage: dict[str, Any] | None = None
    ) -> None:
        """Queue a chat completion whose message content is the investigation JSON.

        Used when the request asks for ``response_format.json_schema.name == "investigation"``.
        """
        self._behaviors.append(Behavior(kind="investigation", body=content, usage=usage))

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _next_id(self) -> str:
        return f"chatcmpl-fake-{next(self._ids):04d}"

    def _next_responses_id(self) -> str:
        return f"resp-fake-{next(self._ids):04d}"

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        behavior = self._behaviors.pop(0) if self._behaviors else None
        if behavior is None:
            if request.url.path.endswith("/models"):
                return _models_response()
            behavior = ok(dict(DEFAULT_OK_USAGE))
        return self._respond(request, behavior)

    def _respond(self, request: httpx.Request, behavior: Behavior) -> httpx.Response:
        if behavior.kind == "timeout":
            raise httpx.ConnectTimeout("fake upstream timeout", request=request)
        if behavior.kind == "error":
            return _raw_response(behavior.status, behavior.body)
        if behavior.kind == "html":
            return httpx.Response(
                behavior.status,
                content=behavior.text.encode("utf-8"),
                headers={"content-type": "text/html; charset=utf-8"},
            )
        if behavior.kind == "stream":
            return httpx.Response(
                200,
                content=self._stream_body(request, behavior.chunks, behavior.usage),
                headers={"content-type": "text/event-stream"},
            )
        if behavior.kind == "reset":
            chunks = [_delta_chunk(i) for i in range(behavior.after_chunks)]
            return httpx.Response(
                200,
                content=self._reset_body(request, chunks),
                headers={"content-type": "text/event-stream"},
            )
        if behavior.kind == "investigation":
            body = behavior.body if isinstance(behavior.body, dict) else {}
            return _investigation_response(
                _requested_model(request),
                self._next_id(),
                body,
                behavior.usage,
                status=behavior.status,
            )
        if request.url.path.endswith("/responses"):
            return _responses_response(
                _requested_model(request),
                self._next_responses_id(),
                behavior.usage,
                status=behavior.status,
            )
        return _chat_response(
            _requested_model(request), self._next_id(), behavior.usage, status=behavior.status
        )

    async def _stream_body(
        self, request: httpx.Request, chunks: list[str], usage: dict[str, Any] | None
    ) -> AsyncIterator[bytes]:
        responses_path = request.url.path.endswith("/responses")
        for chunk in chunks:
            yield _sse_line(chunk)
        if usage is not None:
            if responses_path:
                mapped = _responses_usage(usage) or {}
                # Match Meta Responses SSE: usage on response.completed → response.usage
                payload = {
                    "type": "response.completed",
                    "response": {"id": self._next_responses_id(), "usage": mapped},
                }
            else:
                payload = {"id": self._next_id(), "usage": usage}
            yield _sse_line(json.dumps(payload))
        yield b"data: [DONE]\n\n"

    async def _reset_body(
        self, request: httpx.Request, chunks: list[str]
    ) -> AsyncIterator[bytes]:
        for chunk in chunks:
            yield _sse_line(chunk)
        raise httpx.ConnectError("fake connection reset", request=request)


def _body_wants_stream(raw_body: bytes) -> bool:
    try:
        parsed = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return False
    return isinstance(parsed, dict) and parsed.get("stream") is True


def _request_bundle(payload: dict[str, Any]) -> dict[str, Any]:
    """The evidence bundle JSON carried in the user message, or {} when absent."""
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return {}
    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        try:
            candidate = json.loads(message.get("content", ""))
        except (ValueError, TypeError, AttributeError):
            continue
        if isinstance(candidate, dict) and isinstance(candidate.get("events"), list):
            return candidate
    return {}


def canned_investigation_for_request(raw_body: bytes) -> dict[str, Any] | None:
    """A valid `InvestigationOutput` derived from the request's own bundle.

    The CLI fake server has no seeded insight, so it cites the bundle it was
    sent: the first event id (via ``evidence_ids`` only, never embedded in
    prose where digit runs would fail number validation) and the aggregate
    ``event_count``. Every other string is digit-free by construction.
    Returns None for non-investigation requests.
    """
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    response_format = payload.get("response_format")
    schema = response_format.get("json_schema") if isinstance(response_format, dict) else None
    if not isinstance(schema, dict) or schema.get("name") != "investigation":
        return None

    bundle = _request_bundle(payload)
    raw_events = bundle.get("events")
    events = raw_events if isinstance(raw_events, list) else []
    first = events[0] if events and isinstance(events[0], dict) else {}
    evidence_id = first.get("id") if isinstance(first.get("id"), str) else None
    raw_aggregates = bundle.get("aggregates")
    aggregates: dict[str, Any] = raw_aggregates if isinstance(raw_aggregates, dict) else {}
    event_count = aggregates.get("event_count", len(events))
    count = event_count if isinstance(event_count, int) else len(events)
    summary = (
        "Bundle holds no related events for review."
        if count == 0
        else f"Bundle holds {count} related events for review."
    )

    # Offline demo (TOKENPILOT_FAKE_DEMO_MODE=1): recommend context_strategy so
    # insight → benchmark yields full_repo vs targeted. Leave the default
    # retry_policy canned answer for unit / investigate e2e tests.
    demo_mode = os.environ.get("TOKENPILOT_FAKE_DEMO_MODE", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )

    if demo_mode:
        return {
            "title": "Repeated full-repo context during debugging",
            "summary": (
                summary
                if count == 0
                else f"Bundle holds {count} related events; large context may be resent."
            ),
            "observed_facts": [
                {
                    "statement": (
                        "The earliest related event in the bundle shows "
                        "a retry after a rate limit."
                    ),
                    "evidence_ids": [evidence_id] if evidence_id else [],
                }
            ],
            "root_cause_hypothesis": (
                "Debugging turns may resend the full repository on every request."
            ),
            "impact_assessment": "Each retry adds spend without new progress.",
            "recommendation": {
                "action": "Test a targeted-context strategy",
                "variable_to_change": "context_strategy",
                "expected_direction": "lower_cost",
                "validation_procedure": (
                    "Replay the same task with targeted context and the same tests."
                ),
                "proposed_benchmark": {
                    "baseline_change": "Keep full_repo context.",
                    "alternative_change": "Send only the files needed for the fix.",
                },
            },
            "confidence": "medium",
            "limitations": ["The bundle covers recent events only."],
            "verdict": "supported",
        }

    return {
        "title": "Retry pattern under review",
        "summary": summary,
        "observed_facts": [
            {
                "statement": (
                    "The earliest related event in the bundle shows "
                    "a retry after a rate limit."
                ),
                "evidence_ids": [evidence_id] if evidence_id else [],
            }
        ],
        "root_cause_hypothesis": (
            "Retries after rate limits repeat work that the first attempt started."
        ),
        "impact_assessment": "Each retry adds spend without new progress.",
        "recommendation": {
            "action": "Cap automatic retries for rate-limited calls.",
            "variable_to_change": "retry_policy",
            "expected_direction": "lower_cost",
            "validation_procedure": "Compare retry spend before and after the cap.",
            "proposed_benchmark": {
                "baseline_change": "Keep current retry behavior.",
                "alternative_change": "Cap retries after rate limits.",
            },
        },
        "confidence": "medium",
        "limitations": ["The bundle covers recent events only."],
        "verdict": "supported",
    }


def _demo_scenario() -> str:
    with _DEMO_SCENARIO_LOCK:
        return _DEMO_SCENARIO


def set_demo_scenario(scenario: str) -> None:
    """Set the sticky demo scenario (``success`` or ``fail-alt``)."""
    global _DEMO_SCENARIO
    normalized = scenario.strip().lower() if scenario else "success"
    if normalized not in ("success", "fail-alt"):
        normalized = "success"
    with _DEMO_SCENARIO_LOCK:
        _DEMO_SCENARIO = normalized


def _parse_payload(raw_body: bytes) -> dict[str, Any] | None:
    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _is_tool_agent_request(payload: dict[str, Any]) -> bool:
    """True when the request looks like the benchmark coding agent."""
    tools = payload.get("tools")
    if isinstance(tools, list) and tools:
        return True
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return False
    return any(isinstance(m, dict) and m.get("role") == "tool" for m in messages)


def _first_user_content(payload: dict[str, Any]) -> str:
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return ""
    for message in messages:
        if isinstance(message, dict) and message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else ""
    return ""


def _looks_full_repo(payload: dict[str, Any]) -> bool:
    content = _first_user_content(payload)
    if "full_repo context" in content:
        return True
    if "Repository listing:" in content:
        return False
    return len(content) >= 20_000


def _agent_step(payload: dict[str, Any]) -> int:
    """0=list_files, 1=read_file, 2=write_file, 3+=done from tool-result count."""
    messages = payload.get("messages")
    if not isinstance(messages, list):
        return 0
    return sum(1 for m in messages if isinstance(m, dict) and m.get("role") == "tool")


def _tool_call(name: str, arguments: dict[str, Any], call_id: str) -> dict[str, Any]:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


def demo_agent_response(
    payload: dict[str, Any], source_id: str, *, scenario: str | None = None
) -> dict[str, Any]:
    """Scripted invoicing-fix tool loop for offline benchmarks."""
    model = payload.get("model")
    model_id = model if isinstance(model, str) and model else DEFAULT_MODEL
    full_repo = _looks_full_repo(payload)
    usage = dict(FULL_REPO_USAGE if full_repo else TARGETED_USAGE)
    step = _agent_step(payload)
    active = (scenario or _demo_scenario()).strip().lower() or "success"
    write_fixed = not (active == "fail-alt" and not full_repo)

    if step == 0:
        message: dict[str, Any] = {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("list_files", {}, f"{source_id}-list")],
        }
        finish = "tool_calls"
    elif step == 1:
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                _tool_call(
                    "read_file",
                    {"path": "invoicing/discounts.py"},
                    f"{source_id}-read",
                )
            ],
        }
        finish = "tool_calls"
    elif step == 2:
        content = _FIXED_DISCOUNTS_FILE if write_fixed else _BUGGY_DISCOUNTS_FILE
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                _tool_call(
                    "write_file",
                    {"path": "invoicing/discounts.py", "content": content},
                    f"{source_id}-write",
                )
            ],
        }
        finish = "tool_calls"
    else:
        summary = (
            "Fixed apply_discount to discount before tax."
            if write_fixed
            else "Attempted a fix; leaving apply_discount unchanged for honesty demo."
        )
        message = {
            "role": "assistant",
            "content": None,
            "tool_calls": [_tool_call("done", {"summary": summary}, f"{source_id}-done")],
        }
        finish = "tool_calls"

    return {
        "id": source_id,
        "object": "chat.completion",
        "model": model_id,
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
        "usage": usage,
    }


def _delta_chunk(index: int) -> str:
    return json.dumps({"choices": [{"index": 0, "delta": {"content": f"tok{index}"}}]})


def _chat_response(
    model: str, source_id: str, usage: dict[str, Any] | None, status: int = 200
) -> httpx.Response:
    body: dict[str, Any] = {
        "id": source_id,
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": "ok"},
                "finish_reason": "stop",
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(
        status,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )


def _responses_usage(usage: dict[str, Any] | None) -> dict[str, Any] | None:
    """Map enqueued usage to Responses keys (accept chat or Responses shapes)."""
    if usage is None:
        return None
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    mapped: dict[str, Any] = {}
    if input_tokens is not None:
        mapped["input_tokens"] = input_tokens
    if output_tokens is not None:
        mapped["output_tokens"] = output_tokens
    # Preserve any other keys (e.g. details) without remapping.
    for key, value in usage.items():
        if key in ("input_tokens", "output_tokens", "prompt_tokens", "completion_tokens"):
            continue
        mapped[key] = value
    return mapped


def _responses_response(
    model: str, source_id: str, usage: dict[str, Any] | None, status: int = 200
) -> httpx.Response:
    body: dict[str, Any] = {
        "id": source_id,
        "object": "response",
        "model": model,
    }
    mapped = _responses_usage(usage)
    if mapped is not None:
        body["usage"] = mapped
    return httpx.Response(
        status,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )


def _investigation_response(
    model: str,
    source_id: str,
    content: dict[str, Any],
    usage: dict[str, Any] | None,
    status: int = 200,
) -> httpx.Response:
    body: dict[str, Any] = {
        "id": source_id,
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {
                    "role": "assistant",
                    "content": json.dumps(content),
                },
                "finish_reason": "stop",
            }
        ],
    }
    if usage is not None:
        body["usage"] = usage
    return httpx.Response(
        status,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )


def _raw_response(
    status: int, body: dict[str, Any] | bytes | str | None
) -> httpx.Response:
    if isinstance(body, dict):
        return httpx.Response(
            status,
            content=json.dumps(body).encode("utf-8"),
            headers={"content-type": "application/json"},
        )
    content = body.encode("utf-8") if isinstance(body, str) else (body or b"")
    return httpx.Response(status, content=content)


def _models_response() -> httpx.Response:
    return httpx.Response(
        200,
        content=json.dumps(
            {
                "object": "list",
                "data": [
                    {"id": "fake-large", "object": "model"},
                    {"id": "fake-small", "object": "model"},
                ],
            }
        ).encode("utf-8"),
        headers={"content-type": "application/json"},
    )


# --- HTTP server for manual runs -------------------------------------------


_BEHAVIORS: dict[str, Callable[[], Behavior]] = {
    "ok": lambda: ok(dict(DEFAULT_OK_USAGE)),
    "stream": lambda: stream([_delta_chunk(0), _delta_chunk(1)], dict(DEFAULT_OK_USAGE)),
    "error": lambda: error(429, {"error": {"code": "rate_limited", "message": "slow down"}}),
    "html": lambda: html(502, "<html>bad gateway</html>"),
    "timeout": timeout,
    "reset": lambda: reset_mid_stream(2),
}

# One fake for the whole CLI server, so chat ids stay unique across requests
# (reused ids would dedup in the gateway ledger). Guarded by a lock because
# ThreadingHTTPServer serves requests concurrently.
_CLI_FAKE = FakeUpstream()
_CLI_LOCK = threading.Lock()
_CLI_FALLBACK_IDS = itertools.count(1)


def _log_request(path: str, headers: dict[str, str], raw_body: bytes) -> None:
    """Append what this upstream received to ``TOKENPILOT_FAKE_REQUEST_LOG`` (JSONL).

    Security tests read it to prove which credentials crossed the proxy.
    """
    target = os.environ.get("TOKENPILOT_FAKE_REQUEST_LOG", "").strip()
    if not target:
        return
    line = json.dumps(
        {"path": path, "headers": headers, "body": raw_body.decode("utf-8", "replace")}
    )
    with _CLI_LOCK, open(target, "a", encoding="utf-8") as handle:
        handle.write(line + "\n")


def _echo_text(headers: dict[str, str]) -> str:
    """A hostile upstream's echo: the auth it was sent plus any configured secrets."""
    configured = os.environ.get("TOKENPILOT_FAKE_ECHO_SECRETS", "")
    extra = [item for item in configured.split(",") if item]
    auth = next((v for k, v in headers.items() if k.lower() == "authorization"), "")
    return " ".join([auth, *extra])


def _cli_handle(request: httpx.Request, behavior_name: str) -> httpx.Response:
    with _CLI_LOCK:
        _CLI_FAKE.enqueue(_BEHAVIORS.get(behavior_name, _BEHAVIORS["ok"])())
        return _CLI_FAKE._handle(request)


class _Handler(BaseHTTPRequestHandler):
    server_version = "FakeUpstream/1.0"

    def _serve(self) -> None:
        import asyncio

        length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(length) if length else b""
        url = f"http://fake{self.path}"
        request = httpx.Request(
            self.command,
            url,
            content=raw_body,
            headers={"content-type": self.headers.get("Content-Type", "application/json")},
        )
        async def read_all(response: httpx.Response) -> bytes:
            if isinstance(response.stream, httpx.AsyncByteStream):
                chunks = [chunk async for chunk in response.stream]
                return b"".join(chunks)
            return response.read()

        def send(response: httpx.Response) -> None:
            body = asyncio.run(read_all(response))
            self.send_response(response.status_code)
            self.send_header(
                "Content-Type", response.headers.get("content-type", "application/json")
            )
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        received = {name: value for name, value in self.headers.items()}
        _log_request(self.path, received, raw_body)

        behavior_header = self.headers.get("X-Fake-Behavior")
        if behavior_header in ("echo-error", "echo-id"):
            # Security tests: an upstream that reflects credentials back, either in
            # an error body or in the response id (which the ledger stores).
            echo = _echo_text(received)
            if behavior_header == "echo-error":
                send(
                    _raw_response(
                        401, {"error": {"code": "bad_credentials", "message": f"rejected {echo}"}}
                    )
                )
            else:
                send(
                    _chat_response(
                        DEFAULT_MODEL,
                        "chatcmpl-echo-" + echo.replace(" ", "-"),
                        dict(DEFAULT_OK_USAGE),
                    )
                )
            return

        scenario_header = self.headers.get("X-Fake-Demo-Scenario")
        if scenario_header:
            set_demo_scenario(scenario_header)

        canned = canned_investigation_for_request(raw_body)
        if canned is not None:
            with _CLI_LOCK:
                _CLI_FAKE.enqueue_investigation(canned, usage=dict(DEFAULT_OK_USAGE))
                send(_CLI_FAKE._handle(request))
            return

        payload = _parse_payload(raw_body)
        if payload is not None and _is_tool_agent_request(payload):
            with _CLI_LOCK:
                source_id = _CLI_FAKE._next_id()
            body = demo_agent_response(payload, source_id)
            send(
                httpx.Response(
                    200,
                    content=json.dumps(body).encode("utf-8"),
                    headers={"content-type": "application/json"},
                )
            )
            return

        # Seed sessions and other non-agent traffic: honor X-Fake-Behavior.
        # For large full-repo-looking prompts without tools, return high usage
        # so offline seeding can still price expensive sessions.
        name = self.headers.get("X-Fake-Behavior")
        if name is None and _body_wants_stream(raw_body):
            name = "stream"
        elif name is None:
            name = "ok"

        if name == "ok" and payload is not None:
            usage = (
                dict(FULL_REPO_USAGE)
                if _looks_full_repo(payload)
                else dict(DEFAULT_OK_USAGE)
            )
            # Cheap control prompts stay tiny; mid-size "expensive" seeds that
            # are not full_repo still need enough tokens to clear detector D.
            user = _first_user_content(payload)
            if 4_000 <= len(user) < 20_000:
                usage = {"prompt_tokens": 200_000, "completion_tokens": 50}
            model = payload.get("model")
            model_id = model if isinstance(model, str) and model else DEFAULT_MODEL
            with _CLI_LOCK:
                source_id = _CLI_FAKE._next_id()
            send(_chat_response(model_id, source_id, usage))
            return

        try:
            response = _cli_handle(request, name)
        except httpx.ConnectTimeout:
            import time

            time.sleep(120)
            response = _chat_response(
                DEFAULT_MODEL,
                f"chatcmpl-fake-cli-{next(_CLI_FALLBACK_IDS):04d}",
                dict(DEFAULT_OK_USAGE),
            )

        if name == "reset":
            # Partial body, then drop the connection mid-stream.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", "100000")
            self.end_headers()
            self.wfile.write(_sse_line(_delta_chunk(0)))
            self.wfile.write(_sse_line(_delta_chunk(1)))
            self.wfile.flush()
            self.close_connection = True
            return

        send(response)

    do_GET = _serve
    do_POST = _serve

    def log_message(self, *args: object) -> None:
        pass


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tests.fakes.fake_upstream")
    parser.add_argument("--port", type=int, default=8799)
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), _Handler)
    print(f"fake upstream on http://127.0.0.1:{args.port} (X-Fake-Behavior selects behavior)")
    server.serve_forever()


if __name__ == "__main__":
    main()
