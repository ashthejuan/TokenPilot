"""`GET /api/v1/usage/summary` and session cost fields over HTTP (Task 1.5)."""

from typing import Any

from fastapi.testclient import TestClient

EVENTS = "/api/v1/usage/events"
SUMMARY = "/api/v1/usage/summary"
SESSIONS = "/api/v1/sessions"
# fake-small input is "0.25" per 1M tokens (demo-simulated seed): 4M tokens = $1.
ONE_DOLLAR = 4_000_000


def make_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "provider": "fake",
        "model_id": "fake-small",
        "started_at": "2026-10-29T10:00:00Z",
        "usage_source": "provider",
        "status": "success",
        "input_tokens": ONE_DOLLAR,
        "output_tokens": 0,
    }
    event.update(overrides)
    return event


def post(client: TestClient, headers: dict[str, str], *events: dict[str, Any]) -> list[str]:
    response = client.post(EVENTS, json=list(events), headers=headers)
    assert response.status_code == 201
    return [item["id"] for item in response.json()["results"]]


def get_summary(client: TestClient, headers: dict[str, str], **params: Any) -> Any:
    response = client.get(SUMMARY, params=params, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_summary_endpoint_shape(client: TestClient, auth_headers: dict[str, str]) -> None:
    post(
        client,
        auth_headers,
        make_event(source_event_id="a", project_id="alpha"),
        make_event(source_event_id="b", input_tokens=None, usage_source="unavailable"),
    )

    body = get_summary(client, auth_headers)

    assert body["total_estimated_cost"] == 1.0
    assert body["currency"] == "USD"
    assert body["cost_basis"] == "simulated"
    assert body["events_with_unknown_cost"] == 1
    assert body["request_count"] == 2
    assert body["coverage"] == {
        "attributed_pct": 50.0,
        "priced_pct": 50.0,
        "provider_usage_pct": 50.0,
        "mixed_currency": False,
    }
    assert body["by_model"][0]["currency"] == "USD"
    assert body["by_model"][0]["events_with_unknown_tokens"] == 1
    assert body["timeseries"][0]["bucket_start"] == "2026-10-29T00:00:00.000Z"


def test_summary_requires_auth(client: TestClient) -> None:
    assert client.get(SUMMARY).status_code == 401


def test_summary_validates_query(client: TestClient, auth_headers: dict[str, str]) -> None:
    for params in (
        {"bucket": "week"},
        {"outcome": "success"},
        {"from": "2026-10-29T00:00:00"},
    ):
        response = client.get(SUMMARY, params=params, headers=auth_headers)
        assert response.status_code == 422, params
        assert response.json()["error"]["code"] == "validation_error"


def test_summary_window_and_bucket_params(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    post(
        client,
        auth_headers,
        make_event(source_event_id="a", started_at="2026-10-29T10:00:00Z"),
        make_event(source_event_id="b", started_at="2026-10-29T11:00:00+01:00"),
        make_event(source_event_id="c", started_at="2026-10-30T10:00:00Z"),
    )

    body = get_summary(
        client,
        auth_headers,
        **{"from": "2026-10-29T00:00:00Z", "to": "2026-10-30T00:00:00Z", "bucket": "hour"},
    )

    assert body["request_count"] == 2
    assert [p["bucket_start"] for p in body["timeseries"]] == ["2026-10-29T10:00:00.000Z"]
    assert body["timeseries"][0]["request_count"] == 2


def test_summary_reflects_attribution_correction(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    event_id, _ = post(
        client,
        auth_headers,
        make_event(source_event_id="a", project_id="alpha"),
        make_event(source_event_id="b", project_id="beta", input_tokens=2 * ONE_DOLLAR),
    )
    projects = {p["name"]: p["project_id"] for p in get_summary(client, auth_headers)["by_project"]}

    response = client.patch(
        f"{EVENTS}/{event_id}/attribution",
        json={"project_id": projects["beta"]},
        headers=auth_headers,
    )
    assert response.status_code == 200

    by_project = get_summary(client, auth_headers)["by_project"]
    assert [(p["name"], p["estimated_cost"], p["request_count"]) for p in by_project] == [
        ("beta", 3.0, 2)
    ]


def test_session_cost_fields_filled_from_latest_costs(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    post(
        client,
        auth_headers,
        make_event(source_event_id="a", external_session_id="s1"),
        make_event(
            source_event_id="b",
            external_session_id="s1",
            started_at="2026-10-29T10:05:00Z",
            completed_at="2026-10-29T10:05:02.5Z",
            input_tokens=2 * ONE_DOLLAR,
        ),
        make_event(
            source_event_id="c",
            external_session_id="s1",
            model_id="fake-large",
            started_at="2026-10-29T10:01:00Z",
            input_tokens=None,
            usage_source="unavailable",
        ),
    )

    item = client.get(SESSIONS, headers=auth_headers).json()["items"][0]
    assert (item["total_estimated_cost"], item["currency"]) == (3.0, "USD")
    assert item["ended_at"] == "2026-10-29T10:05:02.500Z"

    detail = client.get(f"{SESSIONS}/{item['id']}", headers=auth_headers).json()
    assert detail["session"]["total_estimated_cost"] == 3.0
    models = {m["model_id"]: m for m in detail["by_model"]}
    assert (models["fake-small"]["estimated_cost"], models["fake-small"]["currency"]) == (
        3.0,
        "USD",
    )
    assert models["fake-small"]["events_with_unknown_tokens"] == 0
    assert (models["fake-large"]["estimated_cost"], models["fake-large"]["currency"]) == (
        None,
        None,
    )
    assert models["fake-large"]["events_with_unknown_tokens"] == 1


def test_session_ended_at_uses_started_at_without_completion(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    post(
        client,
        auth_headers,
        make_event(source_event_id="late", external_session_id="s1",
                   started_at="2026-10-29T10:09:00Z"),
        make_event(source_event_id="early", external_session_id="s1",
                   started_at="2026-10-29T10:00:00Z"),
    )

    item = client.get(SESSIONS, headers=auth_headers).json()["items"][0]

    assert item["started_at"] == "2026-10-29T10:00:00.000Z"
    assert item["ended_at"] == "2026-10-29T10:09:00.000Z"


def test_session_ended_at_covers_event_moved_in_by_correction(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    _, moved_id = post(
        client,
        auth_headers,
        make_event(source_event_id="a", external_session_id="s1"),
        make_event(source_event_id="b", started_at="2026-10-29T11:00:00Z"),
    )
    session = client.get(SESSIONS, headers=auth_headers).json()["items"][0]

    response = client.patch(
        f"{EVENTS}/{moved_id}/attribution",
        json={"session_id": session["id"]},
        headers=auth_headers,
    )
    assert response.status_code == 200

    item = client.get(f"{SESSIONS}/{session['id']}", headers=auth_headers).json()["session"]
    assert item["ended_at"] == "2026-10-29T11:00:00.000Z"
    assert item["total_estimated_cost"] == 2.0
