"""Detector threshold settings over HTTP (Task 2.0, P20)."""

from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tokenpilot.db.database import Database
from tokenpilot.detectors.thresholds import Thresholds

THRESHOLDS = "/api/v1/settings/thresholds"

# The golden wire form: every one of the 16 defaults as JSON (money = numbers).
DEFAULTS: dict[str, Any] = {
    "repeat_window_s": 300,
    "retry_min_attempts": 2,
    "unsuccessful_min_cost": 0.5,
    "runaway_max_requests": 40,
    "runaway_max_cost": 2.0,
    "runaway_max_duration_min": 60,
    "runaway_max_retries": 5,
    "open_session_grace_min": 15,
    "context_min_chars": 2000,
    "ratio_threshold": 50.0,
    "ratio_min_input_tokens": 20000,
    "context_repeat_min_occurrences": 3,
    "context_medium_repeated_tokens": 50000,
    "ratio_low_min_events": 5,
    "severity_high_cost": 1.0,
    "severity_medium_cost": 0.1,
}


def test_thresholds_default_get(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get(THRESHOLDS, headers=auth_headers)

    assert response.status_code == 200, response.text
    assert response.json() == DEFAULTS
    assert set(DEFAULTS) == set(Thresholds.model_fields)


def test_thresholds_put_round_trips(
    client: TestClient, app: FastAPI, auth_headers: dict[str, str]
) -> None:
    payload = dict(DEFAULTS)
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
        {**DEFAULTS, "bogus": 1},
        {**DEFAULTS, "repeat_window_s": 0},
        {**DEFAULTS, "ratio_threshold": -1.0},
        {**DEFAULTS, "runaway_max_cost": -1},
    ]

    for payload in cases:
        response = client.put(THRESHOLDS, json=payload, headers=auth_headers)
        assert response.status_code == 422, payload
        assert response.json()["error"]["code"] == "validation_error"

    # A rejected PUT changes nothing.
    assert client.get(THRESHOLDS, headers=auth_headers).json() == DEFAULTS
