"""Repricing through the API: versions append, history is kept (Task 1.3, RF5)."""

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tokenpilot.db.database import Database

EVENTS = "/api/v1/usage/events"
PRICING = "/api/v1/settings/pricing"
META_URL = "https://dev.meta.ai/docs/pricing-rate-limits"


def make_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
        "provider": "fake",
        "model_id": "fake-large",
        "started_at": "2026-10-29T00:00:00Z",
        "usage_source": "provider",
        "status": "success",
        "input_tokens": 1_000_000,
        "output_tokens": 500_000,
    }
    event.update(overrides)
    return event


def post_event(client: TestClient, headers: dict[str, str], **overrides: Any) -> str:
    response = client.post(EVENTS, json=make_event(**overrides), headers=headers)
    assert response.status_code == 201
    return str(response.json()["results"][0]["id"])


def cost_rows(app: FastAPI, event_id: str) -> list[dict[str, Any]]:
    db: Database = app.state.db
    with db.read() as conn:
        rows = conn.execute(
            "SELECT pricing_version_id, estimated_cost, reported_cost, currency, cost_basis, "
            "reason, calculated_at FROM cost_records WHERE usage_event_id = ? "
            "ORDER BY calculated_at, rowid",
            (event_id,),
        ).fetchall()
    return [dict(row) for row in rows]


def current_version_id(
    client: TestClient, headers: dict[str, str], provider: str, model_id: str
) -> str:
    versions = client.get(PRICING, headers=headers).json()
    match = next(
        v for v in versions if v["provider"] == provider and v["model_id"] == model_id
    )
    return str(match["id"])


def test_reprice_appends_new_cost_record_and_keeps_history(
    app: FastAPI, client: TestClient, auth_headers: dict[str, str]
) -> None:
    event_id = post_event(client, auth_headers, source_event_id="reprice-1")
    old_version_id = current_version_id(client, auth_headers, "fake", "fake-large")

    before = client.get(f"{EVENTS}/{event_id}", headers=auth_headers).json()
    assert before["cost"]["estimated_cost"] == 10.5
    assert before["cost"]["currency"] == "USD"
    assert before["cost"]["cost_basis"] == "estimated"
    assert before["cost"]["reason"] is None
    assert before["cost"]["pricing_version_id"] == old_version_id

    response = client.put(
        PRICING,
        json={
            "provider": "fake",
            "model_id": "fake-large",
            "currency": "USD",
            "input_price_per_million": "6.00",
            "output_price_per_million": "30.00",
            "cached_input_price": "0.60",
            "pricing_source": "demo-simulated",
            "valid_from": "2026-10-28T00:00:00Z",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["repriced"] == 1
    new_version_id = body["version"]["id"]
    assert new_version_id != old_version_id

    rows = cost_rows(app, event_id)
    assert len(rows) == 2
    assert rows[0]["pricing_version_id"] == old_version_id
    assert rows[0]["estimated_cost"] == 10.5
    assert rows[1]["pricing_version_id"] == new_version_id
    assert rows[1]["estimated_cost"] == 21.0

    after = client.get(f"{EVENTS}/{event_id}", headers=auth_headers).json()
    assert after["cost"]["estimated_cost"] == 21.0
    assert after["cost"]["pricing_version_id"] == new_version_id

    listed = client.get(EVENTS, params={"provider": "fake"}, headers=auth_headers).json()
    assert listed["items"][0]["cost"]["pricing_version_id"] == new_version_id


def test_get_pricing_lists_current_versions_with_source(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get(PRICING, headers=auth_headers)

    assert response.status_code == 200
    versions = response.json()
    assert len(versions) == 8
    assert {(v["provider"], v["model_id"]) for v in versions} >= {
        ("fake", "fake-large"),
        ("fake", "fake-small"),
        ("meta", "muse-spark-1.3-contributor"),
    }
    for version in versions:
        assert version["pricing_source"], version["model_id"]
        assert version["valid_to"] is None
    meta = next(v for v in versions if v["model_id"] == "muse-wonder-1.0")
    assert meta["input_price_per_million"] == 4.0
    assert meta["output_price_per_million"] == 20.0
    assert meta["pricing_source"] == META_URL


def test_put_pricing_conflicts_on_same_valid_from(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.put(
        PRICING,
        json={
            "provider": "fake",
            "model_id": "fake-small",
            "currency": "USD",
            "input_price_per_million": "9.99",
            "output_price_per_million": "1.25",
            "valid_from": "2026-01-01T00:00:00Z",
        },
        headers=auth_headers,
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "conflict"


def test_put_pricing_identical_body_is_idempotent(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    body = {
        "provider": "fake",
        "model_id": "fake-small",
        "currency": "USD",
        "input_price_per_million": "0.50",
        "output_price_per_million": "2.50",
        "cached_input_price": "0.05",
        "pricing_source": "demo-simulated",
        "valid_from": "2026-11-01T00:00:00Z",
    }

    first = client.put(PRICING, json=body, headers=auth_headers)
    second = client.put(PRICING, json=body, headers=auth_headers)

    assert first.status_code == 200
    assert second.status_code == 200
    assert second.json()["version"]["id"] == first.json()["version"]["id"]
    assert second.json()["repriced"] == 0
    versions = client.get(PRICING, headers=auth_headers).json()
    assert len(versions) == 8
