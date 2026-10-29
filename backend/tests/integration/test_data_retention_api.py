"""Retention delete + privacy settings API (Phase 3, Task 3.4: Q13, Q14)."""

from fastapi.testclient import TestClient

from tokenpilot.db.database import Database
from tokenpilot.detectors.base import Finding, Scope
from tokenpilot.insights.repository import InsightRepository

PRIVACY = "/api/v1/settings/privacy"
DATA = "/api/v1/data"
EVENTS = "/api/v1/usage/events"


def make_event(**overrides: object) -> dict[str, object]:
    event: dict[str, object] = {
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


def test_privacy_reflects_settings(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get(PRIVACY, headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["store_content"] is False
    assert body["allow_content_transmission"] is False
    assert body["upstream_base_url"] == "https://api.meta.ai/v1"
    assert body["investigator_model"] == "muse-spark-1.3-contributor"
    assert body["local_token_configured"] is True
    assert body["contributor_training"] is True


def test_delete_data_before_removes_old_events_and_cascades_costs(
    client: TestClient, auth_headers: dict[str, str], app: object
) -> None:
    old = client.post(
        EVENTS,
        json=make_event(source_event_id="old-1", started_at="2026-01-01T00:00:00Z"),
        headers=auth_headers,
    )
    new = client.post(
        EVENTS,
        json=make_event(source_event_id="new-1", started_at="2026-10-27T10:00:00Z"),
        headers=auth_headers,
    )
    assert old.status_code == 201, old.text
    assert new.status_code == 201, new.text
    old_id = old.json()["results"][0]["id"]
    new_id = new.json()["results"][0]["id"]

    response = client.delete(
        DATA, params={"before": "2026-06-01T00:00:00Z"}, headers=auth_headers
    )

    assert response.status_code == 200, response.text
    assert response.json()["deleted_events"] == 1

    db: Database = app.state.db  # type: ignore[attr-defined]
    with db.read() as conn:
        remaining = {row["id"] for row in conn.execute("SELECT id FROM usage_events")}
        assert old_id not in remaining
        assert new_id in remaining
        assert (
            conn.execute(
                "SELECT COUNT(*) AS n FROM cost_records WHERE usage_event_id = ?",
                (old_id,),
            ).fetchone()["n"]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) AS n FROM cost_records WHERE usage_event_id = ?",
                (new_id,),
            ).fetchone()["n"]
            >= 1
        )


def test_delete_data_keeps_insights_sessions_pricing_and_boundary_event(
    client: TestClient, auth_headers: dict[str, str], app: object
) -> None:
    """Q13 keep-half: only strictly-older events go; insights, sessions,
    pricing, and the boundary event survive, and the counts shape holds."""
    pricing = client.put(
        "/api/v1/settings/pricing",
        json={
            "provider": "meta",
            "model_id": "muse-spark-1.3",
            "currency": "USD",
            "input_price_per_million": 1.0,
            "output_price_per_million": 2.0,
        },
        headers=auth_headers,
    )
    assert pricing.status_code == 200, pricing.text
    kept = client.post(
        EVENTS,
        json=make_event(
            source_event_id="keep-1",
            external_session_id="keep-s1",
            started_at="2026-01-01T00:00:00Z",
        ),
        headers=auth_headers,
    )
    assert kept.status_code == 201, kept.text
    edge = client.post(
        EVENTS,
        json=make_event(source_event_id="edge-1", started_at="2026-06-01T00:00:00Z"),
        headers=auth_headers,
    )
    assert edge.status_code == 201, edge.text
    finding = Finding(
        rule_id="repeated_request",
        rule_version=1,
        anchor="keep",
        severity="low",
        confidence=0.5,
        title="keep",
        summary="keep",
        scope=Scope(),
        evidence=[],
        measurements={},
        estimated_impact=None,
        impact_currency=None,
    )
    db: Database = app.state.db  # type: ignore[attr-defined]
    with db.write() as conn:
        InsightRepository(conn).upsert(finding, "2026-01-01T00:00:00.000Z")

    response = client.delete(
        DATA, params={"before": "2026-06-01T00:00:00Z"}, headers=auth_headers
    )

    assert response.status_code == 200, response.text
    assert response.json() == {
        "deleted_events": 1,
        "deleted_excerpt_files": 0,
        "deleted_worktrees": 0,
    }
    assert client.get("/api/v1/settings/pricing", headers=auth_headers).json() != []
    sessions = client.get("/api/v1/sessions", headers=auth_headers).json()["items"]
    assert any(item["external_session_id"] == "keep-s1" for item in sessions)
    insights = client.get("/api/v1/insights", headers=auth_headers).json()["items"]
    assert any(item["rule_id"] == "repeated_request" for item in insights)
    remaining = {
        item["source_event_id"]
        for item in client.get(EVENTS, headers=auth_headers).json()["items"]
    }
    assert "keep-1" not in remaining
    assert "edge-1" in remaining


def test_delete_data_requires_before_param(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.delete(DATA, headers=auth_headers)

    assert response.status_code == 422, response.text


def test_delete_data_rejects_naive_before(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    # Naive bounds are rejected like every other timestamp bound: UTC must be explicit.
    response = client.delete(DATA, params={"before": "2026-06-01T00:00:00"}, headers=auth_headers)

    assert response.status_code == 422, response.text


def test_delete_data_rejects_invalid_before(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.delete(DATA, params={"before": "not-a-date"}, headers=auth_headers)

    assert response.status_code == 422, response.text


def test_delete_data_auth_required(client: TestClient) -> None:
    response = client.delete(DATA, params={"before": "2026-06-01T00:00:00Z"})

    assert response.status_code == 401, response.text


def test_privacy_auth_required(client: TestClient) -> None:
    response = client.get(PRIVACY)

    assert response.status_code == 401, response.text
