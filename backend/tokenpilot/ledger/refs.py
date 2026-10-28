"""Resolve caller-supplied references (project id or slug) to stored rows."""

import re
import sqlite3

from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.common import SLUG_PATTERN
from tokenpilot.timeutil import utc_now_z

_SLUG = re.compile(SLUG_PATTERN)


class LedgerRefError(ValueError):
    """A reference the caller supplied cannot be honoured. `code` is the API error code."""

    code = "invalid_reference"
    details: dict[str, str | None] | None = None


class ProjectRefError(LedgerRefError):
    code = "invalid_project_ref"


class TaskProjectMismatchError(LedgerRefError):
    code = "task_project_mismatch"

    def __init__(self, task_id: str, task_project_id: str | None, project_id: str | None) -> None:
        super().__init__(
            f"task {task_id!r} belongs to project {task_project_id!r}, not {project_id!r}; "
            "change the task or the project in the same request"
        )
        self.details = {
            "task_id": task_id,
            "task_project_id": task_project_id,
            "project_id": project_id,
        }


class SessionProjectMismatchError(LedgerRefError):
    code = "session_project_mismatch"

    def __init__(
        self, session_id: str, session_project_id: str | None, project_id: str | None
    ) -> None:
        super().__init__(
            f"session {session_id!r} belongs to project {session_project_id!r}, "
            f"not {project_id!r}; change the session or the project in the same request"
        )
        self.details = {
            "session_id": session_id,
            "session_project_id": session_project_id,
            "project_id": project_id,
        }


class BenchmarkRunRefError(LedgerRefError):
    code = "unknown_benchmark_run"


def resolve_project_ref(conn: sqlite3.Connection, ref: str) -> str:
    """Return a project id for an id or slug, creating `{name: ref, slug: ref}` if new.

    An explicit identifier is the strongest attribution signal (FR-02), so an
    unknown but well-formed ref creates the project instead of being dropped.
    """
    row = conn.execute(
        "SELECT id FROM projects WHERE id = ? OR slug = ? ORDER BY id = ? DESC LIMIT 1",
        (ref, ref, ref),
    ).fetchone()
    if row is not None:
        return str(row["id"])
    if not _SLUG.match(ref):
        raise ProjectRefError(f"project reference {ref!r} is not a project id or a valid slug")
    return LedgerRepository(conn).create_project(name=ref, slug=ref).id


def resolve_task_ref(conn: sqlite3.Connection, ref: str, project_id: str | None) -> str | None:
    """Return a task id for an internal id or the caller's own task id.

    A caller-supplied id is matched within `project_id`; an unknown one is
    created there (D3). Without a project nothing can be matched or created,
    so the result is None and the caller keeps the ref in metadata.
    """
    repository = LedgerRepository(conn)
    if repository.task_project(ref) is not None:
        return ref
    if project_id is None:
        return None
    existing = repository.find_task_by_external_id(project_id, ref)
    if existing is not None:
        return existing
    return repository.create_task(project_id=project_id, external_task_id=ref)


def get_or_create_session(
    conn: sqlite3.Connection,
    external_session_id: str,
    source: str,
    project_id: str | None,
    *,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> str:
    """Return the session keyed on (`source`, `external_session_id`), creating it if new.

    A session without a project adopts one once known. `started_at`/`ended_at`
    are the event's start and completion (completion defaults to the start); the
    session span only ever widens, since events can arrive out of order.
    """
    repository = LedgerRepository(conn)
    when = started_at or utc_now_z()
    end = max(when, ended_at) if ended_at else when
    row = repository.find_session(source, external_session_id)
    if row is None:
        return repository.create_session(
            source=source,
            external_session_id=external_session_id,
            project_id=project_id,
            started_at=when,
            ended_at=end,
        )
    if row["project_id"] is None and project_id is not None:
        repository.update_session_origin(row["id"], project_id=project_id, started_at=None)
    repository.widen_session_span(row["id"], started_at=when, ended_at=end)
    return str(row["id"])
