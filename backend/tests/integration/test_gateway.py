"""Non-streaming gateway proxy tests (Task 1.4)."""

import asyncio
import json
from typing import Any
from unittest.mock import patch

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from tests.fakes.fake_upstream import FakeUpstream, error, html, ok, timeout
from tokenpilot.config import Settings
from tokenpilot.main import create_app

CHAT = "/gateway/v1/chat/completions"
EVENTS = "/api/v1/usage/events"
EVENT_ID_HEADER = "X-TokenPilot-Event-Id"


def chat_body(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "model": "fake-large",
        "messages": [{"role": "user", "content": "ping"}],
    }
    body.update(overrides)
    return body


def list_events(client: TestClient, headers: dict[str, str]) -> list[dict[str, Any]]:
    response = client.get(EVENTS, headers=headers)
    assert response.status_code == 200
    return list(response.json()["items"])


def test_success_records_usage_latency_and_cost(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    fake.enqueue(ok({"prompt_tokens": 100, "completion_tokens": 50}))

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["choices"][0]["message"]["content"] == "ok"
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


def test_upstream_key_injected_and_client_token_not_forwarded(
    gateway_client: TestClient,
    auth_headers: dict[str, str],
    fake: FakeUpstream,
    gateway_settings: Settings,
) -> None:
    gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    (upstream_request,) = fake.requests
    expected = gateway_settings.upstream_api_key
    assert expected is not None
    assert upstream_request.headers["authorization"] == f"Bearer {expected.get_secret_value()}"
    assert upstream_request.headers["accept-encoding"] == "identity"
    client_token = auth_headers["Authorization"].removeprefix("Bearer ")
    assert client_token not in str(upstream_request.headers)


def test_attribution_headers_stripped_and_applied(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    headers = {
        **auth_headers,
        "X-TokenPilot-Project": "alpha",
        "X-TokenPilot-Session": "sess-1",
        "X-TokenPilot-Task": "task-1",
        "X-TokenPilot-Retry-Of": "nonexistent-parent",
    }

    response = gateway_client.post(CHAT, json=chat_body(), headers=headers)

    assert response.status_code == 200
    (upstream_request,) = fake.requests
    for name in upstream_request.headers:
        assert not name.lower().startswith("x-tokenpilot-"), name
    (event,) = list_events(gateway_client, auth_headers)
    # Explicit task beats explicit project; the task is created under alpha.
    assert event["metadata"]["attribution_basis"] == "explicit_task"
    assert event["task_id"] is not None
    assert event["session_id"] is not None
    projects = gateway_client.get("/api/v1/projects", headers=auth_headers).json()
    assert {p["slug"] for p in projects} == {"alpha"}
    assert event["project_id"] == projects[0]["id"]
    # Unknown retry parents are ignored, never fatal.
    assert event["retry_group_id"] is None


def test_upstream_4xx_recorded_with_error_category(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    body = {"error": {"code": "rate_limited", "message": "slow down"}}
    fake.enqueue(error(429, body))

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == 429
    assert response.content == json.dumps(body).encode("utf-8")
    assert EVENT_ID_HEADER in response.headers
    (event,) = list_events(gateway_client, auth_headers)
    assert event["status"] == "error"
    assert event["error_category"] == "rate_limited"
    assert event["http_status"] == 429
    assert event["usage_source"] == "unavailable"


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (400, "bad_request"),
        (401, "auth"),
        (403, "auth"),
        (404, "not_found"),
        (408, "timeout"),
        (413, "too_large"),
        (418, "client_error"),
        (500, "upstream_error"),
        (503, "upstream_error"),
    ],
)
def test_error_category_mapping(
    gateway_client: TestClient,
    auth_headers: dict[str, str],
    fake: FakeUpstream,
    status: int,
    category: str,
) -> None:
    fake.enqueue(error(status, {"error": {"code": "x", "message": "y"}}))

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == status
    (event,) = list_events(gateway_client, auth_headers)
    assert event["error_category"] == category
    assert event["status"] == "error"


def test_upstream_timeout_records_event_and_returns_504(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    fake.enqueue(timeout())

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == 504
    assert response.json()["error"]["code"] == "upstream_timeout"
    assert EVENT_ID_HEADER in response.headers
    (event,) = list_events(gateway_client, auth_headers)
    assert event["status"] == "timeout"
    assert event["error_category"] == "timeout"
    assert event["http_status"] is None


def test_upstream_transport_error_returns_502(
    auth_headers: dict[str, str], gateway_settings: Settings
) -> None:
    def _broken(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection refused", request=request)

    app = create_app(gateway_settings, upstream_transport=httpx.MockTransport(_broken))
    with TestClient(app) as client:
        response = client.post(CHAT, json=chat_body(), headers=auth_headers)
        assert response.status_code == 502
        assert response.json()["error"]["code"] == "upstream_error"
        assert EVENT_ID_HEADER in response.headers
        (event,) = list_events(client, auth_headers)
    assert event["status"] == "error"
    assert event["error_category"] == "connection_error"


def test_model_and_messages_forwarded_unchanged(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    raw = (
        b'{"model":"fake-large","messages":[{"role":"user","content":"ping"}],'
        b'"temperature":0.7,"top_p":1}'
    )

    response = gateway_client.post(
        CHAT, content=raw, headers={**auth_headers, "Content-Type": "application/json"}
    )

    assert response.status_code == 200
    (upstream_request,) = fake.requests
    assert upstream_request.content == raw
    assert upstream_request.headers["content-type"] == "application/json"


async def test_concurrent_requests_all_recorded(
    gateway_app: FastAPI, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    assert not fake.requests
    async with gateway_app.router.lifespan_context(gateway_app):
        transport = httpx.ASGITransport(app=gateway_app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            responses = await asyncio.gather(
                *(
                    client.post(CHAT, json=chat_body(), headers=auth_headers)
                    for _ in range(20)
                )
            )
    assert [r.status_code for r in responses] == [200] * 20
    assert len({r.headers[EVENT_ID_HEADER] for r in responses}) == 20

    with TestClient(gateway_app) as check:
        events = list_events(check, auth_headers)
    assert len(events) == 20
    assert len({e["id"] for e in events}) == 20


def test_non_json_upstream_body_relayed_and_recorded(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    fake.enqueue(html(502, "<html>bad gateway</html>"))

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == 502
    assert response.content == b"<html>bad gateway</html>"
    (event,) = list_events(gateway_client, auth_headers)
    assert event["usage_source"] == "unavailable"
    assert event["error_category"] == "upstream_error"
    assert event["status"] == "error"
    assert event["http_status"] == 502


def test_path_project_default_and_header_precedence(
    gateway_client: TestClient, auth_headers: dict[str, str]
) -> None:
    path_response = gateway_client.post(
        "/gateway/p/alpha/v1/chat/completions", json=chat_body(), headers=auth_headers
    )
    header_response = gateway_client.post(
        "/gateway/p/alpha/v1/chat/completions",
        json=chat_body(),
        headers={**auth_headers, "X-TokenPilot-Project": "beta"},
    )

    assert path_response.status_code == 200
    assert header_response.status_code == 200
    events = {e["id"]: e for e in list_events(gateway_client, auth_headers)}
    projects = {
        p["id"]: p["slug"]
        for p in gateway_client.get("/api/v1/projects", headers=auth_headers).json()
    }
    path_event = events[path_response.headers[EVENT_ID_HEADER]]
    header_event = events[header_response.headers[EVENT_ID_HEADER]]
    assert projects[path_event["project_id"]] == "alpha"
    assert path_event["metadata"]["attribution_basis"] == "gateway_default"
    assert projects[header_event["project_id"]] == "beta"
    assert header_event["metadata"]["attribution_basis"] == "explicit_project"


def test_ledger_failure_does_not_break_response(
    gateway_client: TestClient,
    auth_headers: dict[str, str],
    fake: FakeUpstream,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import tokenpilot.gateway.proxy as proxy

    def _boom(*args: object, **kwargs: object) -> object:
        raise RuntimeError("ledger is down")

    monkeypatch.setattr(proxy, "ingest_event", _boom)
    fake.enqueue(ok({"prompt_tokens": 3, "completion_tokens": 1}))

    response = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["usage"] == {"prompt_tokens": 3, "completion_tokens": 1}


def test_malformed_tools_still_relayed_without_fingerprint(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    # Non-dict tools have no .get: fingerprinting must fail soft (None), never
    # 500 the relay.
    raw = json.dumps(chat_body(tools=[None, "x"])).encode()

    response = gateway_client.post(
        CHAT, content=raw, headers={**auth_headers, "Content-Type": "application/json"}
    )

    assert response.status_code == 200
    (upstream_request,) = fake.requests
    assert upstream_request.content == raw
    (event,) = list_events(gateway_client, auth_headers)
    assert event["request_fingerprint"] is None


def test_unknown_benchmark_run_keeps_response_but_skips_event(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    # ingest rejects unknown benchmark runs; the gateway never fails the model
    # call for that, so the response succeeds and no event is recorded.
    headers = {**auth_headers, "X-TokenPilot-Benchmark-Run": "no-such-run"}

    response = gateway_client.post(CHAT, json=chat_body(), headers=headers)

    assert response.status_code == 200
    (upstream_request,) = fake.requests
    assert "x-tokenpilot-benchmark-run" not in {n.lower() for n in upstream_request.headers}
    assert list_events(gateway_client, auth_headers) == []


def test_missing_upstream_key_returns_503(
    auth_headers: dict[str, str], settings: Settings, fake: FakeUpstream
) -> None:
    assert settings.upstream_api_key is None
    app = create_app(settings, upstream_transport=fake.transport())

    with TestClient(app) as client:
        response = client.post(CHAT, json=chat_body(), headers=auth_headers)
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "upstream_not_configured"
        assert list_events(client, auth_headers) == []
    assert fake.requests == []


def test_benchmark_traffic_uses_dedicated_upstream_client(
    gateway_client: TestClient, gateway_app: FastAPI, auth_headers: dict[str, str]
) -> None:
    # Worker-driven benchmark traffic must never share the server loop's
    # upstream client (loop-affine pool: "Event loop is closed" on reuse).
    shared = gateway_app.state.upstream
    dedicated = gateway_app.state.benchmark_upstream
    assert shared is not dedicated
    with (
        patch.object(shared, "post", wraps=shared.post) as shared_post,
        patch.object(dedicated, "post", wraps=dedicated.post) as dedicated_post,
    ):
        normal = gateway_client.post(CHAT, json=chat_body(), headers=auth_headers)
        benchmarked = gateway_client.post(
            CHAT,
            json=chat_body(),
            headers={**auth_headers, "X-TokenPilot-Benchmark-Run": "run-1"},
        )
    assert normal.status_code == 200
    assert benchmarked.status_code == 200
    assert shared_post.call_count == 1
    assert dedicated_post.call_count == 1


def test_models_relayed_without_event(
    gateway_client: TestClient, auth_headers: dict[str, str], fake: FakeUpstream
) -> None:
    response = gateway_client.get("/gateway/v1/models", headers=auth_headers)
    slug_response = gateway_client.get("/gateway/p/alpha/v1/models", headers=auth_headers)

    assert response.status_code == 200
    assert [m["id"] for m in response.json()["data"]] == ["fake-large", "fake-small"]
    assert slug_response.status_code == 200
    assert list_events(gateway_client, auth_headers) == []
