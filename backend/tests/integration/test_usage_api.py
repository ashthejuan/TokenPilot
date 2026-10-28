import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tokenpilot.db.database import Database

EVENTS = "/api/v1/usage/events"
BASE = datetime(2026, 10, 27, 10, 0, 0, tzinfo=UTC)


def make_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "provider": "meta",
        "model_id": "muse-spark-1.3",
        "started_at": "2026-10-27T10:00:00Z",
        "usage_source": "provider",
        "status": "success",
        "input_tokens": 100,
        "output_tokens": 20,
    }
    event.update(overrides)
    return event


def count_events(client: TestClient, headers: dict[str, str]) -> int:
    return len(client.get(EVENTS, headers=headers).json()["items"])


def test_duplicate_ingest_not_double_counted(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    body = make_event(source_event_id="evt-1")

    first = client.post(EVENTS, json=body, headers=auth_headers)
    second = client.post(EVENTS, json=body, headers=auth_headers)

    assert first.status_code == 201
    assert second.status_code == 201
    first_result = first.json()["results"][0]
    second_result = second.json()["results"][0]
    assert first_result["duplicate"] is False
    assert second_result["duplicate"] is True
    assert second_result["id"] == first_result["id"]
    assert count_events(client, auth_headers) == 1


def test_duplicate_inside_one_batch(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = make_event(idempotency_key="same")

    response = client.post(EVENTS, json=[body, body], headers=auth_headers)

    results = response.json()["results"]
    assert [r["duplicate"] for r in results] == [False, True]
    assert results[0]["id"] == results[1]["id"]
    assert count_events(client, auth_headers) == 1


def test_failed_request_without_usage_persisted(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    body = make_event(
        usage_source="unavailable",
        status="error",
        http_status=500,
        error_category="upstream_error",
    )
    del body["input_tokens"], body["output_tokens"]

    created = client.post(EVENTS, json=body, headers=auth_headers)
    event_id = created.json()["results"][0]["id"]
    event = client.get(f"{EVENTS}/{event_id}", headers=auth_headers).json()

    assert event["status"] == "error"
    assert event["usage_source"] == "unavailable"
    assert event["http_status"] == 500
    assert event["error_category"] == "upstream_error"
    assert event["input_tokens"] is None
    assert event["output_tokens"] is None
    assert event["cached_tokens"] is None


def test_events_paginated(client: TestClient, auth_headers: dict[str, str]) -> None:
    # Pairs share a started_at so the id tie-break is exercised.
    batch = [
        make_event(
            source_event_id=f"e{i}", started_at=(BASE + timedelta(seconds=i // 2)).isoformat()
        )
        for i in range(250)
    ]
    for start in range(0, 250, 125):
        response = client.post(EVENTS, json=batch[start : start + 125], headers=auth_headers)
        assert response.status_code == 201

    page1 = client.get(EVENTS, params={"limit": 200}, headers=auth_headers).json()
    assert len(page1["items"]) == 200
    assert page1["next_cursor"] is not None

    page2 = client.get(
        EVENTS, params={"limit": 200, "cursor": page1["next_cursor"]}, headers=auth_headers
    ).json()
    assert len(page2["items"]) == 50
    assert page2["next_cursor"] is None

    items = page1["items"] + page2["items"]
    assert len({item["id"] for item in items}) == 250
    keys = [(item["started_at"], item["id"]) for item in items]
    assert keys == sorted(keys, reverse=True)


def test_default_page_size_is_50_and_limit_capped(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    batch = [make_event(source_event_id=f"e{i}") for i in range(60)]
    client.post(EVENTS, json=batch, headers=auth_headers)

    assert len(client.get(EVENTS, headers=auth_headers).json()["items"]) == 50
    assert client.get(EVENTS, params={"limit": 201}, headers=auth_headers).status_code == 422
    assert client.get(EVENTS, params={"limit": 0}, headers=auth_headers).status_code == 422
    assert client.get(EVENTS, params={"cursor": "garbage"}, headers=auth_headers).status_code == 422


def test_filters(client: TestClient, auth_headers: dict[str, str]) -> None:
    client.post(
        EVENTS,
        json=[
            make_event(source_event_id="a", started_at="2026-10-27T10:00:00Z"),
            make_event(
                source_event_id="b",
                started_at="2026-10-27T11:00:00Z",
                model_id="other-model",
                status="error",
            ),
            make_event(source_event_id="c", started_at="2026-10-27T12:00:00Z", provider="fake"),
        ],
        headers=auth_headers,
    )

    def ids(**params: str) -> list[str]:
        response = client.get(EVENTS, params=params, headers=auth_headers).json()
        return [item["source_event_id"] for item in response["items"]]

    assert ids(model_id="other-model") == ["b"]
    assert ids(status="error") == ["b"]
    assert ids(provider="fake") == ["c"]
    assert ids(**{"from": "2026-10-27T11:00:00Z"}) == ["c", "b"]
    assert ids(to="2026-10-27T11:00:00Z") == ["a"]
    assert ids(**{"from": "2026-10-27T10:30:00Z", "to": "2026-10-27T12:00:00Z"}) == ["b"]
    naive = client.get(EVENTS, params={"from": "2026-10-27T11:00:00"}, headers=auth_headers)
    assert naive.status_code == 422


def test_get_event_not_found(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get(f"{EVENTS}/missing", headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"


def test_naive_timestamp_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(
        EVENTS, json=make_event(started_at="2026-10-27T10:00:00"), headers=auth_headers
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert count_events(client, auth_headers) == 0


def test_batch_over_500_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    batch = [make_event(source_event_id=f"e{i}") for i in range(501)]

    response = client.post(EVENTS, json=batch, headers=auth_headers)

    assert response.status_code == 422
    assert count_events(client, auth_headers) == 0


def test_empty_batch_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.post(EVENTS, json=[], headers=auth_headers).status_code == 422


def test_batch_of_500_accepted(client: TestClient, auth_headers: dict[str, str]) -> None:
    batch = [make_event(source_event_id=f"e{i}") for i in range(500)]

    response = client.post(EVENTS, json=batch, headers=auth_headers)

    assert response.status_code == 201
    assert len(response.json()["results"]) == 500


def test_invalid_item_rejects_whole_batch(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        EVENTS, json=[make_event(), make_event(output_tokens=-1)], headers=auth_headers
    )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert error["details"][0]["loc"][1] == 1
    assert count_events(client, auth_headers) == 0


def test_unknown_fields_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    body = make_event(messages=[{"role": "user", "content": "secret prompt"}])

    response = client.post(EVENTS, json=body, headers=auth_headers)

    assert response.status_code == 422
    assert count_events(client, auth_headers) == 0


def test_non_object_body_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert client.post(EVENTS, json="nope", headers=auth_headers).status_code == 422
    assert client.post(EVENTS, content=b"{not json", headers=auth_headers).status_code == 422


def test_raw_event_json_has_no_secrets(
    client: TestClient, app: FastAPI, auth_headers: dict[str, str]
) -> None:
    body = make_event(metadata={"authorization": "Bearer x", "api_key": "y", "note": "ok"})

    created = client.post(EVENTS, json=body, headers=auth_headers)

    event_id = created.json()["results"][0]["id"]
    db: Database = app.state.db
    with db.read() as conn:
        row = conn.execute(
            "SELECT raw_event_json, metadata_json FROM usage_events WHERE id = ?", (event_id,)
        ).fetchone()
    assert "Bearer x" not in row["raw_event_json"]
    assert '"y"' not in row["raw_event_json"]
    assert json.loads(row["raw_event_json"])["metadata"] == {"note": "ok"}
    assert json.loads(row["metadata_json"]) == {"note": "ok"}


def test_explicit_project_id_resolves_slug_id_or_creates(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    project = client.post("/api/v1/projects", json={"name": "Alpha"}, headers=auth_headers).json()

    results = client.post(
        EVENTS,
        json=[
            make_event(source_event_id="1", project_id=project["id"]),
            make_event(source_event_id="2", project_id="alpha"),
            make_event(source_event_id="3", project_id="smoke"),
            make_event(source_event_id="4"),
        ],
        headers=auth_headers,
    ).json()["results"]

    events = [client.get(f"{EVENTS}/{r['id']}", headers=auth_headers).json() for r in results]
    assert events[0]["project_id"] == project["id"]
    assert events[1]["project_id"] == project["id"]
    assert events[2]["project_id"] not in (None, project["id"])
    assert events[3]["project_id"] is None

    projects = client.get("/api/v1/projects", headers=auth_headers).json()
    assert {p["slug"] for p in projects} == {"alpha", "smoke"}

    filtered = client.get(EVENTS, params={"project_id": project["id"]}, headers=auth_headers)
    assert len(filtered.json()["items"]) == 2


def test_invalid_project_ref_rejects_batch(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post(
        EVENTS,
        json=[
            make_event(source_event_id="1"),
            make_event(source_event_id="2", project_id="Bad Ref!"),
        ],
        headers=auth_headers,
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "invalid_project_ref"
    assert count_events(client, auth_headers) == 0


def test_unknown_benchmark_run_rejected(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.post(EVENTS, json=make_event(benchmark_run_id="nope"), headers=auth_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "unknown_benchmark_run"
    assert count_events(client, auth_headers) == 0
