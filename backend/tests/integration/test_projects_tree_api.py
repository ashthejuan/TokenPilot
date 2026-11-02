"""Integration tests for GET /api/v1/projects/{id}/tree."""

from pathlib import Path

from fastapi.testclient import TestClient


def _make_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "pkg" / "a.py").write_text("print('a')\n")
    (repo / "pkg" / "nested").mkdir()
    (repo / "pkg" / "nested" / "b.py").write_text("print('b')\n")
    (repo / "README.md").write_text("# repo\n")
    (repo / ".git").mkdir()
    (repo / ".git" / "config").write_text("[core]\n")
    return repo


def _create_project(
    client: TestClient,
    auth_headers: dict[str, str],
    repository_path: str | None,
    *,
    name: str = "Tree Proj",
) -> str:
    body: dict[str, object] = {"name": name}
    if repository_path is not None:
        body["repository_path"] = repository_path
    created = client.post("/api/v1/projects", json=body, headers=auth_headers)
    assert created.status_code == 201
    return created.json()["id"]


def test_tree_lists_immediate_children_at_root_and_subpath(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path)
    project_id = _create_project(client, auth_headers, str(repo))

    root = client.get(f"/api/v1/projects/{project_id}/tree", headers=auth_headers)
    assert root.status_code == 200
    body = root.json()
    assert body["path"] == ""
    assert sorted(body["entries"], key=lambda e: e["name"]) == [
        {"name": "README.md", "path": "README.md", "kind": "file"},
        {"name": "pkg", "path": "pkg", "kind": "dir"},
    ]

    sub = client.get(
        f"/api/v1/projects/{project_id}/tree",
        params={"path": "pkg"},
        headers=auth_headers,
    )
    assert sub.status_code == 200
    sub_body = sub.json()
    assert sub_body["path"] == "pkg"
    assert sorted(sub_body["entries"], key=lambda e: e["name"]) == [
        {"name": "a.py", "path": "pkg/a.py", "kind": "file"},
        {"name": "nested", "path": "pkg/nested", "kind": "dir"},
    ]


def test_tree_rejects_escape_paths(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path)
    project_id = _create_project(client, auth_headers, str(repo))

    for escape in ("..", "../outside", "/etc"):
        response = client.get(
            f"/api/v1/projects/{project_id}/tree",
            params={"path": escape},
            headers=auth_headers,
        )
        assert response.status_code == 400, escape
        assert response.json()["error"]["code"] == "bad_request"


def test_tree_404_missing_project_repo_or_non_directory(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    missing = client.get("/api/v1/projects/nope/tree", headers=auth_headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"

    no_repo_id = _create_project(client, auth_headers, None, name="No Repo")
    no_repo = client.get(f"/api/v1/projects/{no_repo_id}/tree", headers=auth_headers)
    assert no_repo.status_code == 404
    assert no_repo.json()["error"]["code"] == "not_found"

    repo = _make_repo(tmp_path)
    project_id = _create_project(client, auth_headers, str(repo), name="Has Repo")

    as_file = client.get(
        f"/api/v1/projects/{project_id}/tree",
        params={"path": "README.md"},
        headers=auth_headers,
    )
    assert as_file.status_code == 404
    assert as_file.json()["error"]["code"] == "not_found"

    gone = client.get(
        f"/api/v1/projects/{project_id}/tree",
        params={"path": "does-not-exist"},
        headers=auth_headers,
    )
    assert gone.status_code == 404
    assert gone.json()["error"]["code"] == "not_found"


def test_tree_skips_git_entries(
    client: TestClient, auth_headers: dict[str, str], tmp_path: Path
) -> None:
    repo = _make_repo(tmp_path)
    project_id = _create_project(client, auth_headers, str(repo))

    root = client.get(f"/api/v1/projects/{project_id}/tree", headers=auth_headers)
    assert root.status_code == 200
    names = [e["name"] for e in root.json()["entries"]]
    assert ".git" not in names
    assert all(n.casefold() != ".git" for n in names)

    into_git = client.get(
        f"/api/v1/projects/{project_id}/tree",
        params={"path": ".git"},
        headers=auth_headers,
    )
    assert into_git.status_code == 404
    assert into_git.json()["error"]["code"] == "not_found"
