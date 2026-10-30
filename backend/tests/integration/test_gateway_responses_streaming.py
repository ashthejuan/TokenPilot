"""Streaming Responses API gateway proxy tests (Task 3)."""

import json
from typing import Any

from fastapi.testclient import TestClient

from tests.fakes.fake_upstream import FakeUpstream, stream

RESPONSES = "/gateway/v1/responses"
EVENTS = "/api/v1/usage/events"
EVENT_ID_HEADER = "X-TokenPilot-Event-Id"


def responses_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"model": "fake-large", "input": "ping"}
    body.update(overrides)
    return body


def list_events(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get(EVENTS, headers=headers)
    assert response.status_code == 200
    return list(response.json()["items"])


def sse_line(payload: str) -> bytes:
    return f"data: {payload}\n\n".encode()


def test_responses_stream_records_final_usage(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    chunks = [
        json.dumps({"type": "response.output_text.delta", "delta": "hel"}),
        json.dumps({"type": "response.output_text.delta", "delta": "lo"}),
    ]
    usage = {"input_tokens": 30, "output_tokens": 12}
    fake.enqueue(stream(chunks, usage))

    response = gateway_client.post(
        RESPONSES, json=responses_body(stream=True), headers=auth_headers
    )

    assert response.status_code == 200
    completed = {
        "type": "response.completed",
        "response": {"id": "resp-fake-0001", "usage": usage},
    }
    expected = (
        sse_line(chunks[0])
        + sse_line(chunks[1])
        + sse_line(json.dumps(completed))
        + b"data: [DONE]\n\n"
    )
    assert response.content == expected
    assert response.headers["content-type"] == "text/event-stream"
    (event,) = list_events(gateway_client, auth_headers)
    assert event["id"] == response.headers[EVENT_ID_HEADER]
    assert (event["input_tokens"], event["output_tokens"]) == (30, 12)
    assert event["source_event_id"] == "resp-fake-0001"
    assert event["usage_source"] == "provider"
    assert event["status"] == "success"
    assert event["metadata"].get("gateway_added_include_usage") is None
    (upstream_request,) = fake.requests
    forwarded = json.loads(upstream_request.content.decode("utf-8"))
    assert "stream_options" not in forwarded


def test_responses_stream_without_usage_records_unknown_tokens(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    fake.enqueue(
        stream([json.dumps({"type": "response.output_text.delta", "delta": "x"})])
    )

    response = gateway_client.post(
        RESPONSES, json=responses_body(stream=True), headers=auth_headers
    )

    assert response.status_code == 200
    (event,) = list_events(gateway_client, auth_headers)
    assert event["input_tokens"] is None
    assert event["output_tokens"] is None
    assert event["usage_source"] == "unavailable"
    assert event["status"] == "success"
    assert event["cost"]["cost_basis"] == "unavailable"
    assert event["metadata"].get("gateway_added_include_usage") is None
