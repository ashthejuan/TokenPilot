"""Buffered Responses API gateway proxy tests (Task 2)."""

import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.fakes.fake_upstream import FakeUpstream, ok

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


def test_responses_success_records_usage(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    fake.enqueue(ok({"input_tokens": 100, "output_tokens": 50}))

    response = gateway_client.post(RESPONSES, json=responses_body(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["object"] == "response"
    event_id = response.headers[EVENT_ID_HEADER]
    (event,) = list_events(gateway_client, auth_headers)
    assert event["id"] == event_id
    assert (event["input_tokens"], event["output_tokens"]) == (100, 50)
    assert event["usage_source"] == "provider"
    assert event["status"] == "success"
    assert event["error_category"] is None
    assert event["http_status"] == 200
    assert event["latency_ms"] is not None and event["latency_ms"] >= 0
    assert event["model_id"] == "fake-large"
    assert event["provider"] == "fake"
    assert event["source_event_id"] == response.json()["id"]
    # (100 * 3.00 + 50 * 15.00) / 1e6 on fake-large.
    assert event["cost"]["estimated_cost"] == pytest.approx(0.00105)
    assert event["cost"]["currency"] == "USD"
    assert event["cost"]["cost_basis"] == "estimated"


def test_responses_project_slug_attributes(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    fake.enqueue(ok({"input_tokens": 10, "output_tokens": 5}))

    response = gateway_client.post(
        "/gateway/p/alpha/v1/responses", json=responses_body(), headers=auth_headers
    )

    assert response.status_code == 200
    (event,) = list_events(gateway_client, auth_headers)
    projects = {
        p["id"]: p["slug"]
        for p in gateway_client.get("/api/v1/projects", headers=auth_headers).json()
    }
    assert projects[event["project_id"]] == "alpha"
    assert event["metadata"]["attribution_basis"] == "gateway_default"
    assert event["id"] == response.headers[EVENT_ID_HEADER]


def test_responses_does_not_inject_stream_options_on_non_stream(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    gateway_client.post(RESPONSES, json=responses_body(), headers=auth_headers)

    forwarded = json.loads(fake.requests[0].content)
    assert "stream_options" not in forwarded
