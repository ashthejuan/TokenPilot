from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient

EVENTS = "/api/v1/usage/events"
SESSIONS = "/api/v1/sessions"
BASE = datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)


def make_event(offset_s: int = 0, **overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "provider": "meta",
        "model_id": "muse-spark-1.3",
        "started_at": (BASE + timedelta(seconds=offset_s)).isoformat(),
        "usage_source": "provider",
        "status": "success",
        "input_tokens": 100,
        "output_tokens": 20,
    }
    event.update(overrides)
    return event


def post(client: TestClient, headers: dict[str, str], *events: dict[str, Any]) -> None:
    response = client.post(EVENTS, json=list(events), headers=headers)
    assert response.status_code == 201


def list_sessions(client: TestClient, headers: dict[str, str], **params: Any) -> Any:
    response = client.get(SESSIONS, params=params, headers=headers)
    assert response.status_code == 200
    return response.json()


def test_list_sessions_summary_fields(client: TestClient, auth_headers: dict[str, str]) -> None:
    post(
        client,
        auth_headers,
        make_event(0, external_session_id="s1", project_id="p1", source_event_id="a"),
        make_event(10, external_session_id="s1", source_event_id="b"),
        make_event(20, source_event_id="no-session"),
    )

    page = list_sessions(client, auth_headers)

    assert len(page["items"]) == 1
    item = page["items"][0]
    assert item["external_session_id"] == "s1"
    assert item["request_count"] == 2
    assert item["total_estimated_cost"] is None
    assert item["currency"] is None
    assert item["outcome"] == "unknown"
    assert item["started_at"] == "2026-10-27T10:00:00.000Z"
    assert page["next_cursor"] is None


def test_list_sessions_filters_by_project_and_outcome(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    post(
        client,
        auth_headers,
        make_event(0, external_session_id="a", project_id="p1", source_event_id="1"),
        make_event(1, external_session_id="b", project_id="p2", source_event_id="2"),
    )
    items = list_sessions(client, auth_headers)["items"]
    by_ext = {item["external_session_id"]: item for item in items}
    client.patch(
        f"{SESSIONS}/{by_ext['a']['id']}", json={"outcome": "success"}, headers=auth_headers
    )

    by_project = list_sessions(client, auth_headers, project_id=by_ext["b"]["project_id"])
    by_outcome = list_sessions(client, auth_headers, outcome="success")

    assert [i["external_session_id"] for i in by_project["items"]] == ["b"]
    assert [i["external_session_id"] for i in by_outcome["items"]] == ["a"]
    bad = client.get(SESSIONS, params={"outcome": "bogus"}, headers=auth_headers)
    assert bad.status_code == 422


def test_list_sessions_paginated_newest_first(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Pairs share a started_at so the id tie-break is exercised.
    post(
        client,
        auth_headers,
        *[
            make_event(i // 2, external_session_id=f"s{i}", source_event_id=f"e{i}")
            for i in range(7)
        ],
    )

    page1 = list_sessions(client, auth_headers, limit=3)
    page2 = list_sessions(client, auth_headers, limit=3, cursor=page1["next_cursor"])
    page3 = list_sessions(client, auth_headers, limit=3, cursor=page2["next_cursor"])

    items = page1["items"] + page2["items"] + page3["items"]
    assert (len(page1["items"]), len(page2["items"]), len(page3["items"])) == (3, 3, 1)
    assert page3["next_cursor"] is None
    assert len({i["id"] for i in items}) == 7
    keys = [(i["started_at"], i["id"]) for i in items]
    assert keys == sorted(keys, reverse=True)
    assert client.get(SESSIONS, params={"cursor": "junk"}, headers=auth_headers).status_code == 422


def test_session_detail_events_and_by_model(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    post(
        client,
        auth_headers,
        make_event(30, external_session_id="s1", source_event_id="c", model_id="m2"),
        make_event(0, external_session_id="s1", source_event_id="a"),
        make_event(10, external_session_id="s1", source_event_id="b", output_tokens=None),
    )
    session_id = list_sessions(client, auth_headers)["items"][0]["id"]

    detail = client.get(f"{SESSIONS}/{session_id}", headers=auth_headers).json()

    assert [e["source_event_id"] for e in detail["events"]] == ["a", "b", "c"]
    assert detail["outcome"] == "unknown"
    assert detail["outcome_source"] is None
    assert detail["session"]["id"] == session_id
    assert detail["session"]["request_count"] == 3
    models = {m["model_id"]: m for m in detail["by_model"]}
    assert models["muse-spark-1.3"]["request_count"] == 2
    assert models["muse-spark-1.3"]["input_tokens"] == 200
    assert models["muse-spark-1.3"]["output_tokens"] == 20
    assert models["muse-spark-1.3"]["estimated_cost"] is None
    assert models["m2"]["request_count"] == 1


def test_session_detail_all_null_tokens_stay_null(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    post(
        client,
        auth_headers,
        make_event(
            0,
            external_session_id="s1",
            usage_source="unavailable",
            input_tokens=None,
            output_tokens=None,
        ),
    )
    session_id = list_sessions(client, auth_headers)["items"][0]["id"]

    detail = client.get(f"{SESSIONS}/{session_id}", headers=auth_headers).json()

    assert detail["by_model"][0]["input_tokens"] is None
    assert detail["by_model"][0]["output_tokens"] is None


def test_session_detail_caps_events_at_500(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    for start in range(0, 510, 255):
        post(
            client,
            auth_headers,
            *[
                make_event(i, external_session_id="big", source_event_id=f"e{i}")
                for i in range(start, min(start + 255, 510))
            ],
        )
    session_id = list_sessions(client, auth_headers)["items"][0]["id"]

    detail = client.get(f"{SESSIONS}/{session_id}", headers=auth_headers).json()

    assert len(detail["events"]) == 500
    assert detail["session"]["request_count"] == 510


def test_session_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    url = f"{SESSIONS}/missing"
    responses = [
        client.get(url, headers=auth_headers),
        client.patch(url, json={"outcome": "success"}, headers=auth_headers),
    ]
    for response in responses:
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


def test_session_outcome_patch_manual(client: TestClient, auth_headers: dict[str, str]) -> None:
    post(client, auth_headers, make_event(0, external_session_id="s1"))
    session_id = list_sessions(client, auth_headers)["items"][0]["id"]

    response = client.patch(
        f"{SESSIONS}/{session_id}", json={"outcome": "failure"}, headers=auth_headers
    )

    assert response.status_code == 200
    assert response.json()["outcome"] == "failure"
    assert response.json()["outcome_source"] == "manual"
    detail = client.get(f"{SESSIONS}/{session_id}", headers=auth_headers).json()
    assert (detail["outcome"], detail["outcome_source"]) == ("failure", "manual")

    invalid = client.patch(
        f"{SESSIONS}/{session_id}", json={"outcome": "great"}, headers=auth_headers
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"


def test_session_money_fields_are_json_numbers_or_null(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    post(client, auth_headers, make_event(0, external_session_id="s1"))
    session_id = list_sessions(client, auth_headers)["items"][0]["id"]

    detail = client.get(f"{SESSIONS}/{session_id}", headers=auth_headers).json()

    assert detail["session"]["total_estimated_cost"] is None
    assert detail["by_model"][0]["estimated_cost"] is None
