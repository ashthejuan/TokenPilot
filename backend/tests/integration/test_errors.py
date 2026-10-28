import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel


class _Probe(BaseModel):
    count: int


def test_validation_error_uses_structured_shape(
    app: FastAPI, auth_headers: dict[str, str]
) -> None:
    @app.post("/api/v1/_probe")
    def probe(body: _Probe) -> dict[str, int]:
        return {"count": body.count}

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/_probe", json={"count": "not-a-number"}, headers=auth_headers
        )

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "validation_error"
    assert set(error) == {"code", "message", "details"}
    assert isinstance(error["details"], list)
    assert error["details"][0]["loc"] == ["body", "count"]


def test_unknown_path_uses_structured_shape(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.get("/api/v1/does-not-exist", headers=auth_headers)

    assert response.status_code == 404
    error = response.json()["error"]
    assert error["code"] == "not_found"
    assert set(error) == {"code", "message", "details"}


def test_method_not_allowed_uses_structured_shape(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    response = client.post("/api/v1/health", headers=auth_headers)

    assert response.status_code == 405
    assert response.json()["error"]["code"] == "method_not_allowed"


def test_unhandled_error_is_structured_and_redacted(
    app: FastAPI,
    auth_headers: dict[str, str],
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-abcdefghijklmnop1234"

    @app.get("/api/v1/_boom")
    def boom() -> None:
        raise RuntimeError(f"upstream rejected key {secret}")

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/v1/_boom", headers=auth_headers)

    assert response.status_code == 500
    assert response.json() == {
        "error": {
            "code": "internal_error",
            "message": "internal server error",
            "details": None,
        }
    }
    assert secret not in response.text
    assert secret not in caplog.text
