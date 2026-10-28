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
