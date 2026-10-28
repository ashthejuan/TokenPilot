from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from tokenpilot.db.database import Database
from tokenpilot.ledger.fingerprint import context_blocks

EVENTS = "/api/v1/usage/events"
PROJECTS = "/api/v1/projects"


def make_event(**overrides: Any) -> dict[str, Any]:
    event: dict[str, Any] = {
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


def post_event(client: TestClient, headers: dict[str, str], **overrides: Any) -> str:
    response = client.post(EVENTS, json=make_event(**overrides), headers=headers)
    assert response.status_code == 201
    return str(response.json()["results"][0]["id"])


def create_project(client: TestClient, headers: dict[str, str], name: str) -> str:
    return str(client.post(PROJECTS, json={"name": name}, headers=headers).json()["id"])


def patch(
    client: TestClient, headers: dict[str, str], event_id: str, body: dict[str, Any]
) -> Any:
    return client.patch(f"{EVENTS}/{event_id}/attribution", json=body, headers=headers)


def raw_json(app: FastAPI, event_id: str) -> str:
    db: Database = app.state.db
    with db.read() as conn:
        row = conn.execute(
            "SELECT raw_event_json FROM usage_events WHERE id = ?", (event_id,)
        ).fetchone()
    return str(row["raw_event_json"])


def audit_rows(app: FastAPI) -> list[dict[str, Any]]:
    db: Database = app.state.db
    with db.read() as conn:
        rows = conn.execute(
            "SELECT usage_event_id, field, old_value, new_value, changed_by, changed_at "
            "FROM attribution_changes ORDER BY changed_at, field"
        ).fetchall()
    return [dict(row) for row in rows]


def test_attribution_correction_is_audited_and_raw_unchanged(
    app: FastAPI, client: TestClient, auth_headers: dict[str, str]
) -> None:
    event_id = post_event(client, auth_headers, source_event_id="e1")
    new_project = create_project(client, auth_headers, "Corrected")
    raw_before = raw_json(app, event_id)

    response = patch(client, auth_headers, event_id, {"project_id": new_project})

    assert response.status_code == 200
    assert response.json()["id"] == event_id
    assert response.json()["project_id"] == new_project
    listed = client.get(EVENTS, params={"project_id": new_project}, headers=auth_headers).json()
    assert [item["id"] for item in listed["items"]] == [event_id]
    rows = audit_rows(app)
    assert len(rows) == 1
    assert (rows[0]["field"], rows[0]["old_value"], rows[0]["new_value"]) == (
        "project_id",
        None,
        new_project,
    )
    assert rows[0]["changed_by"] == "local_user"
    assert rows[0]["changed_at"].endswith("Z") and len(rows[0]["changed_at"]) == 24
    assert raw_json(app, event_id) == raw_before


def test_patch_null_unattributes_and_omitted_field_unchanged(
    app: FastAPI, client: TestClient, auth_headers: dict[str, str]
) -> None:
    event_id = post_event(
        client, auth_headers, project_id="p1", task_id="T-1", external_session_id="s1"
    )
    original = client.get(f"{EVENTS}/{event_id}", headers=auth_headers).json()

    response = patch(client, auth_headers, event_id, {"task_id": None})

    body = response.json()
    assert body["task_id"] is None
    assert body["project_id"] == original["project_id"] is not None
    assert body["session_id"] == original["session_id"] is not None
    rows = audit_rows(app)
    assert [(r["field"], r["old_value"], r["new_value"]) for r in rows] == [
        ("task_id", original["task_id"], None)
    ]


def test_patch_unchanged_value_writes_no_audit_row(
    app: FastAPI, client: TestClient, auth_headers: dict[str, str]
) -> None:
    event_id = post_event(client, auth_headers, project_id="p1")
    project_id = client.get(f"{EVENTS}/{event_id}", headers=auth_headers).json()["project_id"]

    assert patch(client, auth_headers, event_id, {"project_id": project_id}).status_code == 200
    assert patch(client, auth_headers, event_id, {}).status_code == 200

    assert audit_rows(app) == []


def test_patch_multiple_fields_one_row_each(
    app: FastAPI, client: TestClient, auth_headers: dict[str, str]
) -> None:
    event_id = post_event(client, auth_headers, project_id="p1", task_id="T-1")
    original = client.get(f"{EVENTS}/{event_id}", headers=auth_headers).json()

    response = patch(client, auth_headers, event_id, {"project_id": None, "task_id": None})

    assert response.json()["project_id"] is None
    assert response.json()["task_id"] is None
    assert {r["field"] for r in audit_rows(app)} == {"project_id", "task_id"}
    assert original["project_id"] is not None


def test_patch_unknown_references_are_404_and_write_nothing(
    app: FastAPI, client: TestClient, auth_headers: dict[str, str]
) -> None:
    event_id = post_event(client, auth_headers)
    real_project = create_project(client, auth_headers, "Real")

    for field in ("project_id", "session_id", "task_id"):
        response = patch(client, auth_headers, event_id, {field: "nope"})
        assert response.status_code == 404, field
        assert response.json()["error"]["code"] == "not_found"
    # A valid change next to an unknown one must not be applied half-way.
    mixed = patch(client, auth_headers, event_id, {"project_id": real_project, "task_id": "nope"})
    assert mixed.status_code == 404

    assert audit_rows(app) == []
    after = client.get(f"{EVENTS}/{event_id}", headers=auth_headers).json()
    assert after["project_id"] is None


def test_patch_unknown_event_is_404(client: TestClient, auth_headers: dict[str, str]) -> None:
    assert patch(client, auth_headers, "missing", {"project_id": None}).status_code == 404


def test_patch_rejects_unknown_fields(client: TestClient, auth_headers: dict[str, str]) -> None:
    event_id = post_event(client, auth_headers)

    assert patch(client, auth_headers, event_id, {"model_id": "x"}).status_code == 422


def test_context_blocks_survive_ingest_as_hashes_only(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    secret_text = "private source code " * 130  # > 2000 chars
    blocks = context_blocks([{"role": "user", "content": secret_text}])
    metadata = {
        "context_blocks": [vars(block) for block in blocks],
        "context_blocks_basis": "approximate",
    }

    event_id = post_event(client, auth_headers, metadata=metadata)
    stored = client.get(f"{EVENTS}/{event_id}", headers=auth_headers)

    assert stored.json()["metadata"]["context_blocks"][0]["position"] == 0
    assert stored.json()["metadata"]["context_blocks_basis"] == "approximate"
    assert "private source code" not in stored.text

