from pathlib import Path

from fastapi.testclient import TestClient

from tokenpilot.config import Settings


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
    assert body["schema_version"] == 1


def test_health_reports_which_database_serves_the_request(
    client: TestClient, auth_headers: dict[str, str], settings: Settings
) -> None:
    response = client.get("/api/v1/health", headers=auth_headers)

    assert response.json()["db_path"] == str(settings.db_path.resolve())


def test_health_fails_when_configured_database_has_no_schema(
    settings: Settings, client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    settings.db_path = tmp_path / "never-migrated.sqlite3"

    response = client.get("/api/v1/health", headers=auth_headers)

    assert response.status_code == 503
    assert response.json()["error"]["code"] == "unavailable"
