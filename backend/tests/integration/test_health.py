from fastapi.testclient import TestClient


def test_health_requires_token(client: TestClient) -> None:
    response = client.get("/api/v1/health")

    assert response.status_code == 401
    error = response.json()["error"]
    assert error["code"] == "unauthorized"
    assert set(error) == {"code", "message", "details"}


def test_health_rejects_wrong_token(client: TestClient) -> None:
    response = client.get(
        "/api/v1/health", headers={"Authorization": "Bearer not-the-token"}
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "unauthorized"


def test_health_ok_with_token(client: TestClient, auth_headers: dict[str, str]) -> None:
    response = client.get("/api/v1/health", headers=auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["db"] == "ok"
    assert isinstance(body["schema_version"], int)
