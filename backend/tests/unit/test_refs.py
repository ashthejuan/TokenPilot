import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tokenpilot.db.connection import connect
from tokenpilot.db.migrate import migrate
from tokenpilot.ledger.refs import ProjectRefError, resolve_project_ref


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "refs.sqlite3")
    migrate(connection)
    yield connection
    connection.close()


def _insert_project(conn: sqlite3.Connection, project_id: str, slug: str) -> None:
    conn.execute(
        "INSERT INTO projects (id, name, slug, created_at, updated_at) "
        "VALUES (?, ?, ?, '2026-10-28T00:00:00Z', '2026-10-28T00:00:00Z')",
        (project_id, slug, slug),
    )


def test_project_ref_resolves_id_slug_or_creates(conn: sqlite3.Connection) -> None:
    _insert_project(conn, "p1", "alpha")

    assert resolve_project_ref(conn, "p1") == "p1"
    assert resolve_project_ref(conn, "alpha") == "p1"

    created_id = resolve_project_ref(conn, "smoke")
    row = conn.execute("SELECT name, slug FROM projects WHERE id = ?", (created_id,)).fetchone()
    assert (row["name"], row["slug"]) == ("smoke", "smoke")
    assert resolve_project_ref(conn, "smoke") == created_id

    with pytest.raises(ProjectRefError):
        resolve_project_ref(conn, "Bad Ref!")
    count = conn.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
    assert count == 2
