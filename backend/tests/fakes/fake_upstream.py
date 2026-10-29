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
"""

import argparse
import itertools
import json
import threading
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import httpx

DEFAULT_OK_USAGE: dict[str, Any] = {"prompt_tokens": 10, "completion_tokens": 5}
DEFAULT_MODEL = "fake-large"


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
    final usage chunk, then ``data: [DONE]``."""
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
        return _chat_response(
            _requested_model(request), self._next_id(), behavior.usage, status=behavior.status
        )

    async def _stream_body(
        self, request: httpx.Request, chunks: list[str], usage: dict[str, Any] | None
    ) -> AsyncIterator[bytes]:
        _ = request
        for chunk in chunks:
            yield _sse_line(chunk)
        if usage is not None:
            yield _sse_line(json.dumps({"id": self._next_id(), "usage": usage}))
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
    events = bundle.get("events") or []
    first = events[0] if events and isinstance(events[0], dict) else {}
    evidence_id = first.get("id") if isinstance(first.get("id"), str) else None
    aggregates = bundle.get("aggregates") if isinstance(bundle.get("aggregates"), dict) else {}
    event_count = aggregates.get("event_count", len(events))
    count = event_count if isinstance(event_count, int) else len(events)
    summary = (
        "Bundle holds no related events for review."
        if count == 0
        else f"Bundle holds {count} related events for review."
    )

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

        canned = canned_investigation_for_request(raw_body)
        if canned is not None:
            with _CLI_LOCK:
                _CLI_FAKE.enqueue_investigation(canned, usage=dict(DEFAULT_OK_USAGE))
                send(_CLI_FAKE._handle(request))
            return

        name = self.headers.get("X-Fake-Behavior")
        if name is None and _body_wants_stream(raw_body):
            name = "stream"
        elif name is None:
            name = "ok"
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
