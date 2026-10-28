"""Detector threshold settings over HTTP (Task 2.0, P20)."""

from decimal import Decimal
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tokenpilot.db.database import Database
from tokenpilot.detectors.thresholds import Thresholds

THRESHOLDS = "/api/v1/settings/thresholds"


def defaults() -> dict[str, Any]:
    """The defaults exactly as JSON: money as numbers, integers as integers."""
    return Thresholds().model_dump(mode="json")


def test_thresholds_default_get(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get(THRESHOLDS, headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json() == defaults()
    # Spot-check the defaults the detectors rely on (P10, P20).
    model = Thresholds()
    assert model.repeat_window_s == 300
    assert model.unsuccessful_min_cost == Decimal("0.50")
    assert model.severity_medium_cost == Decimal("0.10")
    assert model.ratio_threshold == 50.0


def test_thresholds_put_round_trips(
    client: TestClient, app: FastAPI, auth_headers: dict[str, str]
) -> None:
    payload = defaults()
    payload["repeat_window_s"] = 600
    payload["unsuccessful_min_cost"] = 0.25

    response = client.put(THRESHOLDS, json=payload, headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["reanalysis_required"] is True
    assert body["thresholds"]["repeat_window_s"] == 600
    assert body["thresholds"]["unsuccessful_min_cost"] == 0.25

    stored = client.get(THRESHOLDS, headers=auth_headers).json()
    assert stored == body["thresholds"]
    db: Database = app.state.db
    with db.read() as conn:
        row = conn.execute(
            "SELECT value_json FROM app_settings WHERE key = 'detector_thresholds'"
        ).fetchone()
    assert row is not None


def test_thresholds_rejects_unknown_key_and_non_positive(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    cases: list[dict[str, Any]] = [
        {"bogus": 1},
        {**defaults(), "bogus": 1},
        {**defaults(), "repeat_window_s": 0},
        {**defaults(), "ratio_threshold": -1.0},
        {**defaults(), "runaway_max_cost": -1},
    ]

    for payload in cases:
        response = client.put(THRESHOLDS, json=payload, headers=auth_headers)
        assert response.status_code == 422, payload
        assert response.json()["error"]["code"] == "validation_error"

    # A rejected PUT changes nothing.
    assert client.get(THRESHOLDS, headers=auth_headers).json() == defaults()
