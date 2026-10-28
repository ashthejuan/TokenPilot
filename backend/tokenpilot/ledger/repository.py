"""SQL for the ledger. Callers own the transaction (`Database.write()` / `read()`)."""

import json
import sqlite3
import uuid
from typing import Any

from tokenpilot.ledger.normalize import NormalizedEvent
from tokenpilot.schemas.common import Page, Paged, decode_cursor, encode_cursor
from tokenpilot.schemas.projects import Project
from tokenpilot.schemas.usage import EventFilters, UsageEvent
from tokenpilot.timeutil import utc_now_z

_EVENT_COLUMNS = (
    "id, source_event_id, idempotency_key, project_id, session_id, task_id, provider, "
    "model_id, input_tokens, output_tokens, cached_tokens, reasoning_tokens, usage_source, "
    "status, latency_ms, http_status, retry_group_id, retry_source, attempt, "
    "request_fingerprint, started_at, completed_at, error_category, benchmark_run_id, "
    "metadata_json"
)
_PROJECT_COLUMNS = "id, name, slug, repository_path, default_currency, created_at, updated_at"


def _event_from_row(row: sqlite3.Row) -> UsageEvent:
    values = dict(row)
    values["metadata"] = json.loads(values.pop("metadata_json"))
    return UsageEvent.model_validate(values)


class LedgerRepository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    def insert_event(
        self,
        e: NormalizedEvent,
        *,
        event_id: str,
        project_id: str | None,
        session_id: str | None,
        task_id: str | None,
        retry_group_id: str | None,
        retry_source: str | None,
        attempt: int | None,
    ) -> tuple[UsageEvent, bool]:
        """Insert `e`, or return the row that already owns its idempotency key.

        `ON CONFLICT DO NOTHING` never raises, so a duplicate cannot poison the
        surrounding transaction. The bool is True when a new row was created.
        """
        cursor = self._conn.execute(
            "INSERT INTO usage_events (id, source_event_id, idempotency_key, project_id, "
            "session_id, task_id, provider, model_id, input_tokens, output_tokens, "
            "cached_tokens, reasoning_tokens, usage_source, status, latency_ms, http_status, "
            "retry_group_id, retry_source, attempt, request_fingerprint, started_at, "
            "completed_at, metadata_json, error_category, benchmark_run_id, raw_event_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT (idempotency_key) DO NOTHING",
            (
                event_id,
                e.source_event_id,
                e.idempotency_key,
                project_id,
                session_id,
                task_id,
                e.provider,
                e.model_id,
                e.input_tokens,
                e.output_tokens,
                e.cached_tokens,
                e.reasoning_tokens,
                e.usage_source,
                e.status,
                e.latency_ms,
                e.http_status,
                retry_group_id,
                retry_source,
                attempt,
                e.request_fingerprint,
                e.started_at,
                e.completed_at,
                json.dumps(e.metadata, sort_keys=True),
                e.error_category,
                e.benchmark_run_id,
                e.raw_event_json,
            ),
        )
        created = cursor.rowcount == 1
        row = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM usage_events "
            "WHERE idempotency_key = ?",
            (e.idempotency_key,),
        ).fetchone()
        return _event_from_row(row), created

    def get_event(self, event_id: str) -> UsageEvent | None:
        row = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM usage_events WHERE id = ?", (event_id,)
        ).fetchone()
        return _event_from_row(row) if row is not None else None

    def benchmark_run_exists(self, run_id: str) -> bool:
        row = self._conn.execute("SELECT 1 FROM benchmark_runs WHERE id = ?", (run_id,)).fetchone()
        return row is not None

    def query_events(self, f: EventFilters, page: Page) -> Paged[UsageEvent]:
        clauses: list[str] = []
        params: list[Any] = []
        equals = {
            "project_id": f.project_id,
            "session_id": f.session_id,
            "model_id": f.model_id,
            "provider": f.provider,
            "status": f.status,
        }
        for column, value in equals.items():
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if f.started_from is not None:
            clauses.append("started_at >= ?")
            params.append(f.started_from)
        if f.started_to is not None:
            clauses.append("started_at < ?")
            params.append(f.started_to)
        if page.cursor is not None:
            cursor_started, cursor_id = decode_cursor(page.cursor)
            clauses.append("(started_at < ? OR (started_at = ? AND id < ?))")
            params.extend([cursor_started, cursor_started, cursor_id])

        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM usage_events {where} "
            "ORDER BY started_at DESC, id DESC LIMIT ?",
            [*params, page.limit + 1],
        ).fetchall()

        items = [_event_from_row(row) for row in rows[: page.limit]]
        has_more = len(rows) > page.limit
        next_cursor = encode_cursor(items[-1].started_at, items[-1].id) if has_more else None
        return Paged[UsageEvent](items=items, next_cursor=next_cursor)

    def create_project(
        self,
        *,
        name: str,
        slug: str,
        repository_path: str | None = None,
        default_currency: str = "USD",
    ) -> Project:
        project_id = uuid.uuid4().hex
        now = utc_now_z()
        self._conn.execute(
            "INSERT INTO projects (id, name, slug, repository_path, default_currency, "
            "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (project_id, name, slug, repository_path, default_currency, now, now),
        )
        project = self.get_project(project_id)
        assert project is not None
        return project

    def get_project(self, project_id: str) -> Project | None:
        row = self._conn.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        return Project.model_validate(dict(row)) if row is not None else None

    def list_projects(self) -> list[Project]:
        rows = self._conn.execute(
            f"SELECT {_PROJECT_COLUMNS} FROM projects ORDER BY created_at, id"
        ).fetchall()
        return [Project.model_validate(dict(row)) for row in rows]

    def update_project(self, project_id: str, changes: dict[str, Any]) -> Project | None:
        """Apply `changes` (column -> value) and bump `updated_at`; None if no such project."""
        if self.get_project(project_id) is None:
            return None
        columns = [*changes, "updated_at"]
        assignments = ", ".join(f"{column} = ?" for column in columns)
        self._conn.execute(
            f"UPDATE projects SET {assignments} WHERE id = ?",
            [*changes.values(), utc_now_z(), project_id],
        )
        return self.get_project(project_id)
