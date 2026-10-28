"""Decide which project, session and task an event belongs to (FR-02).

Precedence: explicit task (its project) > explicit project > the session's
project > the gateway default > unattributed. Only identifier fields are read;
metadata and message text never influence attribution.
"""

import sqlite3
from dataclasses import dataclass
from typing import Literal

from tokenpilot.ledger.normalize import NormalizedEvent
from tokenpilot.ledger.refs import ProjectRefError, resolve_project_ref, resolve_task_ref
from tokenpilot.ledger.repository import LedgerRepository

AttributionBasis = Literal[
    "explicit_task", "explicit_project", "session", "gateway_default", "unattributed"
]


@dataclass(frozen=True)
class GatewayDefaults:
    """Project-level defaults a gateway request carries."""

    project_ref: str | None = None


@dataclass(frozen=True)
class Attribution:
    """`session_id` is the session that already exists, if any; ingest creates the rest."""

    project_id: str | None
    session_id: str | None
    task_id: str | None
    basis: AttributionBasis
    unresolved_task_ref: str | None = None
    unresolved_project_ref: str | None = None


def resolve_attribution(
    conn: sqlite3.Connection,
    e: NormalizedEvent,
    source: str,
    defaults: GatewayDefaults | None,
) -> Attribution:
    repository = LedgerRepository(conn)

    session_row = (
        repository.find_session(source, e.external_session_id) if e.external_session_id else None
    )
    session_id = str(session_row["id"]) if session_row is not None else None
    session_project = (
        str(session_row["project_id"])
        if session_row is not None and session_row["project_id"] is not None
        else None
    )

    explicit_project = resolve_project_ref(conn, e.project_id) if e.project_id else None

    default_project = None
    unresolved_project_ref = None
    if (
        explicit_project is None
        and session_project is None
        and defaults is not None
        and defaults.project_ref
    ):
        try:
            default_project = resolve_project_ref(conn, defaults.project_ref)
        except ProjectRefError:
            if source != "gateway":
                raise
            # The gateway never rejects a model call over a bad project label.
            unresolved_project_ref = defaults.project_ref

    # A new task ref is created under the strongest project known besides the task.
    context_project = explicit_project or session_project or default_project
    task_id = resolve_task_ref(conn, e.task_id, context_project) if e.task_id else None
    unresolved_task_ref = e.task_id if e.task_id and task_id is None else None

    project_id: str | None
    basis: AttributionBasis
    if task_id is not None:
        project_id, basis = repository.task_project(task_id), "explicit_task"
    elif explicit_project is not None:
        project_id, basis = explicit_project, "explicit_project"
    elif session_project is not None:
        project_id, basis = session_project, "session"
    elif default_project is not None:
        project_id, basis = default_project, "gateway_default"
    else:
        project_id, basis = None, "unattributed"

    return Attribution(
        project_id=project_id,
        session_id=session_id,
        task_id=task_id,
        basis=basis,
        unresolved_task_ref=unresolved_task_ref,
        unresolved_project_ref=unresolved_project_ref,
    )
