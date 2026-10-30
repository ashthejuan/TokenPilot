from fastapi.testclient import TestClient


def test_project_crud_roundtrip(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/projects",
        json={"name": "My Cool App!", "repository_path": "/work/app"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    project = created.json()
    assert project["name"] == "My Cool App!"
    assert project["slug"] == "my-cool-app"
    assert project["repository_path"] == "/work/app"
    assert project["default_currency"] == "USD"
    assert project["created_at"].endswith("Z")

    fetched = client.get(f"/api/v1/projects/{project['id']}", headers=auth_headers)
    assert fetched.status_code == 200
    assert fetched.json()["id"] == project["id"]

    patched = client.patch(
        f"/api/v1/projects/{project['id']}",
        json={"name": "Renamed", "slug": "renamed", "default_currency": "EUR"},
        headers=auth_headers,
    )
    assert patched.status_code == 200
    body = patched.json()
    assert (body["name"], body["slug"], body["default_currency"]) == ("Renamed", "renamed", "EUR")
    assert body["repository_path"] == "/work/app"
    assert body["updated_at"] >= project["updated_at"]

    cleared = client.patch(
        f"/api/v1/projects/{project['id']}", json={"repository_path": None}, headers=auth_headers
    )
    assert cleared.json()["repository_path"] is None

    listed = client.get("/api/v1/projects", headers=auth_headers).json()
    assert [p["id"] for p in listed] == [project["id"]]


def test_duplicate_slug_conflict(client: TestClient, auth_headers: dict[str, str]) -> None:
    first = client.post("/api/v1/projects", json={"name": "Alpha"}, headers=auth_headers)
    second = client.post("/api/v1/projects", json={"name": "Beta"}, headers=auth_headers)

    clash = client.post(
        "/api/v1/projects", json={"name": "Other", "slug": "alpha"}, headers=auth_headers
    )
    assert clash.status_code == 409
    assert clash.json()["error"]["code"] == "conflict"

    patch_clash = client.patch(
        f"/api/v1/projects/{second.json()['id']}", json={"slug": "alpha"}, headers=auth_headers
    )
    assert patch_clash.status_code == 409
    assert patch_clash.json()["error"]["code"] == "conflict"

    assert first.status_code == 201
    assert len(client.get("/api/v1/projects", headers=auth_headers).json()) == 2


def test_project_validation_and_not_found(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    for name in ("!!!", ""):
        response = client.post("/api/v1/projects", json={"name": name}, headers=auth_headers)
        assert response.status_code == 422
    bad_slug = client.post(
        "/api/v1/projects", json={"name": "x", "slug": "Bad Slug"}, headers=auth_headers
    )
    assert bad_slug.status_code == 422
    null_name = client.patch("/api/v1/projects/nope", json={"name": None}, headers=auth_headers)
    assert null_name.status_code == 422

    missing = client.get("/api/v1/projects/nope", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"
    gone = client.patch("/api/v1/projects/nope", json={"name": "n"}, headers=auth_headers)
    assert gone.status_code == 404
    delete_missing = client.delete("/api/v1/projects/nope", headers=auth_headers)
    assert delete_missing.status_code == 404
    assert delete_missing.json()["error"]["code"] == "not_found"


def test_delete_project(client: TestClient, auth_headers: dict[str, str]) -> None:
    created = client.post(
        "/api/v1/projects",
        json={"name": "Temp", "repository_path": "/tmp/temp"},
        headers=auth_headers,
    )
    assert created.status_code == 201
    project_id = created.json()["id"]

    deleted = client.delete(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert deleted.status_code == 204
    assert deleted.content == b""

    assert client.get(f"/api/v1/projects/{project_id}", headers=auth_headers).status_code == 404
    listed = client.get("/api/v1/projects", headers=auth_headers).json()
    assert listed == []

    again = client.delete(f"/api/v1/projects/{project_id}", headers=auth_headers)
    assert again.status_code == 404
