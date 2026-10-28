"""Streaming gateway proxy tests (Task 1.4)."""

import json
import time
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fakes.fake_upstream import FakeUpstream, error, reset_mid_stream, stream
from tokenpilot.db.database import Database
from tokenpilot.gateway.proxy import CaptureContext, relay_stream

CHAT = "/gateway/v1/chat/completions"
EVENTS = "/api/v1/usage/events"
EVENT_ID_HEADER = "X-TokenPilot-Event-Id"


def chat_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "fake-large",
        "messages": [{"role": "user", "content": "ping"}],
        "stream": True,
    }
    body.update(overrides)
    return body


def list_events(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get(EVENTS, headers=headers)
    assert response.status_code == 200
    return list(response.json()["items"])


def sse_line(payload: str) -> bytes:
    return f"data: {payload}\n\n".encode()


def test_stream_relays_chunks_and_records_final_usage(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    chunks = [
        json.dumps({"choices": [{"index": 0, "delta": {"content": "hel"}}]}),
        json.dumps({"choices": [{"index": 0, "delta": {"content": "lo"}}]}),
    ]
    usage = {"prompt_tokens": 30, "completion_tokens": 12}
    fake.enqueue(stream(chunks, usage))

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == 200
    expected = (
        sse_line(chunks[0])
        + sse_line(chunks[1])
        + sse_line(json.dumps({"id": "chatcmpl-fake-0001", "usage": usage}))
        + b"data: [DONE]\n\n"
    )
    assert response.content == expected
    assert response.headers["content-type"] == "text/event-stream"
    (event,) = list_events(gateway_client, auth_headers)
    assert event["id"] == response.headers[EVENT_ID_HEADER]
    assert (event["input_tokens"], event["output_tokens"]) == (30, 12)
    assert event["usage_source"] == "provider"
    assert event["status"] == "success"
    assert event["metadata"]["gateway_added_include_usage"] is True
    # stream:true without stream_options gains include_usage on the way out.
    (upstream_request,) = fake.requests
    forwarded = json.loads(upstream_request.content.decode("utf-8"))
    assert forwarded["stream_options"] == {"include_usage": True}


def test_stream_without_usage_records_unknown_tokens(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    fake.enqueue(stream([json.dumps({"choices": [{"delta": {"content": "x"}}]})]))

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == 200
    (event,) = list_events(gateway_client, auth_headers)
    assert event["input_tokens"] is None
    assert event["output_tokens"] is None
    assert event["usage_source"] == "unavailable"
    assert event["status"] == "success"
    assert event["cost"]["cost_basis"] == "unavailable"


def test_stream_with_existing_stream_options_forwarded_unchanged(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    usage = {"prompt_tokens": 4, "completion_tokens": 2}
    fake.enqueue(stream([json.dumps({"choices": []})], usage))
    raw = json.dumps(chat_body(stream_options={"include_usage": False})).encode("utf-8")

    response = gateway_client.post(
        CHAT, content=raw, headers={**auth_headers, "Content-Type": "application/json"}
    )

    assert response.status_code == 200
    (upstream_request,) = fake.requests
    assert upstream_request.content == raw
    (event,) = list_events(gateway_client, auth_headers)
    assert "gateway_added_include_usage" not in event["metadata"]
    assert (event["input_tokens"], event["output_tokens"]) == (4, 2)


def test_stream_reset_mid_flight_records_error_event(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    fake.enqueue(reset_mid_stream(2))

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == 200
    assert response.content == sse_line(
        json.dumps({"choices": [{"index": 0, "delta": {"content": "tok0"}}]})
    ) + sse_line(json.dumps({"choices": [{"index": 0, "delta": {"content": "tok1"}}]}))
    (event,) = list_events(gateway_client, auth_headers)
    assert event["status"] == "error"
    assert event["error_category"] == "connection_error"
    assert event["http_status"] == 200
    assert event["usage_source"] == "unavailable"


async def test_client_disconnect_mid_stream_records_event(gateway_app: FastAPI) -> None:
    async with gateway_app.router.lifespan_context(gateway_app):
        db: Database = gateway_app.state.db
        ctx = CaptureContext(
            db=db,
            provider="fake",
            event_id="evt-disconnect-1",
            started_at=datetime.now(UTC),
            start_mono=time.monotonic(),
            model_id="fake-large",
            fingerprint=None,
            metadata={},
        )

        async def body() -> Any:
            yield b'data: {"choices":[]}\n\n'
            yield b'data: {"choices":[]}\n\n'

        upstream = httpx.Response(
            200, content=body(), headers={"content-type": "text/event-stream"}
        )
        relay = relay_stream(upstream, ctx)
        assert await relay.__anext__() == b'data: {"choices":[]}\n\n'
        await relay.aclose()

        with db.read() as conn:
            rows = conn.execute(
                "SELECT id, status, error_category FROM usage_events"
            ).fetchall()
    assert [(r["id"], r["status"], r["error_category"]) for r in rows] == [
        ("evt-disconnect-1", "error", "client_disconnected")
    ]


def test_invalid_json_body_forwarded_unchanged(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    raw = b'{"model": "fake-large", "messages": [broken'

    response = gateway_client.post(
        CHAT, content=raw, headers={**auth_headers, "Content-Type": "application/json"}
    )

    assert response.status_code == 200
    (upstream_request,) = fake.requests
    assert upstream_request.content == raw
    (event,) = list_events(gateway_client, auth_headers)
    assert event["model_id"] == "unknown"
    assert event["request_fingerprint"] is None


def test_stream_request_with_fast_error_relays_whole_body(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    body = {"error": {"code": "bad_request", "message": "nope"}}
    fake.enqueue(error(400, body))

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == 400
    assert response.content == json.dumps(body).encode()
    (event,) = list_events(gateway_client, auth_headers)
    assert event["status"] == "error"
    assert event["error_category"] == "bad_request"


def test_stream_uses_last_chunk_with_usage(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    chunks = [
        json.dumps({"usage": {"prompt_tokens": 1, "completion_tokens": 1}}),
        json.dumps({"choices": [{"delta": {"content": "mid"}}]}),
        json.dumps({"usage": {"prompt_tokens": 9, "completion_tokens": 8}}),
    ]
    fake.enqueue(stream(chunks))

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == 200
    (event,) = list_events(gateway_client, auth_headers)
    assert (event["input_tokens"], event["output_tokens"]) == (9, 8)
