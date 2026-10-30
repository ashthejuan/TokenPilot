"""SQL for the ledger. Callers own the transaction (`Database.write()` / `read()`)."""

import json
import sqlite3
import uuid
from typing import Any

from tokenpilot.analytics.money import (
    COST_CURRENCY,
    GROUP_CURRENCY,
    SCALED_ESTIMATE,
    group_money,
    money_from_scaled,
)
from tokenpilot.ledger.normalize import NormalizedEvent
from tokenpilot.pricing.cost import latest_cost_sql, latest_costs_for, to_cost_summary
from tokenpilot.schemas.common import Page, Paged, decode_cursor, encode_cursor
from tokenpilot.schemas.projects import Project
from tokenpilot.schemas.sessions import ModelBreakdown, SessionOutcome, SessionSummary
from tokenpilot.schemas.usage import EventFilters, UsageEvent
from tokenpilot.timeutil import utc_now_z

_EVENT_COLUMNS = (
    "id, source_event_id, idempotency_key, project_id, session_id, task_id, provider, "
    "model_id, input_tokens, output_tokens, cached_tokens, reasoning_tokens, usage_source, "
    "status, latency_ms, http_status, retry_group_id, retry_source, attempt, "
    "request_fingerprint, started_at, completed_at, error_category, benchmark_run_id, "
    "metadata_json"
)
_SESSION_SUMMARY = (
    "SELECT s.id, s.project_id, s.external_session_id, s.source, s.started_at, s.ended_at, "
    "s.outcome, s.outcome_source, "
    "(SELECT COUNT(*) FROM usage_events u WHERE u.session_id = s.id) AS request_count "
    "FROM sessions s"
)


def _session_costed_events(where: str) -> str:
    """An `ev` CTE: the events matched by `where` (on `usage_events u`) with their latest cost."""
    return (
        f"WITH {latest_cost_sql}, ev AS (SELECT u.session_id, u.model_id, u.input_tokens, "
        f"u.output_tokens, {SCALED_ESTIMATE} AS est, {COST_CURRENCY} AS cur "
        f"FROM usage_events u LEFT JOIN latest_costs lc ON lc.usage_event_id = u.id {where}) "
    )


# Fields a correction may change, mapped to the table that must hold the new id.
ATTRIBUTION_TABLES = {"project_id": "projects", "session_id": "sessions", "task_id": "tasks"}
_PROJECT_COLUMNS = "id, name, slug, repository_path, default_currency, created_at, updated_at"


def _event_from_row(row: sqlite3.Row) -> UsageEvent:
    return UsageEvent.from_ledger_row(dict(row))


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

    def find_event_by_idempotency_key(self, key: str) -> UsageEvent | None:
        row = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM usage_events WHERE idempotency_key = ?", (key,)
        ).fetchone()
        return _event_from_row(row) if row is not None else None

    def get_event(self, event_id: str) -> UsageEvent | None:
        row = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM usage_events WHERE id = ?", (event_id,)
        ).fetchone()
        if row is None:
            return None
        return self.with_costs([_event_from_row(row)])[0]

    def with_costs(self, events: list[UsageEvent]) -> list[UsageEvent]:
        """Attach each event's latest cost record; unpriced events keep `cost=None`."""
        if not events:
            return events
        costs = latest_costs_for(self._conn, [event.id for event in events])
        return [
            event.model_copy(update={"cost": to_cost_summary(costs[event.id])})
            if event.id in costs
            else event
            for event in events
        ]

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
        return Paged[UsageEvent](items=self.with_costs(items), next_cursor=next_cursor)

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

    def delete_project(self, project_id: str) -> bool:
        """Delete the project row. FK rules cascade/null related rows. False if missing."""
        cursor = self._conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        return (cursor.rowcount or 0) > 0

    # Tasks

    def task_project(self, task_id: str) -> str | None:
        row = self._conn.execute("SELECT project_id FROM tasks WHERE id = ?", (task_id,)).fetchone()
        return str(row["project_id"]) if row is not None else None

    def find_task_by_external_id(self, project_id: str, external_task_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT id FROM tasks WHERE project_id = ? AND external_task_id = ?",
            (project_id, external_task_id),
        ).fetchone()
        return str(row["id"]) if row is not None else None

    def create_task(self, *, project_id: str, external_task_id: str) -> str:
        task_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO tasks (id, project_id, title, external_task_id, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (task_id, project_id, external_task_id, external_task_id, utc_now_z()),
        )
        return task_id

    # Sessions

    def find_session(self, source: str, external_session_id: str) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT id, project_id, started_at FROM sessions "
            "WHERE source = ? AND external_session_id = ?",
            (source, external_session_id),
        ).fetchone()
        return row

    def create_session(
        self,
        *,
        source: str,
        external_session_id: str,
        project_id: str | None,
        started_at: str,
        ended_at: str,
    ) -> str:
        session_id = uuid.uuid4().hex
        self._conn.execute(
            "INSERT INTO sessions (id, project_id, external_session_id, source, started_at, "
            "ended_at) VALUES (?, ?, ?, ?, ?, ?)",
            (session_id, project_id, external_session_id, source, started_at, ended_at),
        )
        return session_id

    def widen_session_span(self, session_id: str, *, started_at: str, ended_at: str) -> None:
        """Stretch the session so it covers `[started_at, ended_at]`; it never shrinks.

        Fixed-ms `Z` strings compare chronologically, so MIN/MAX work on text.
        """
        self._conn.execute(
            "UPDATE sessions SET started_at = MIN(started_at, ?), "
            "ended_at = MAX(COALESCE(ended_at, ?), ?) WHERE id = ?",
            (started_at, ended_at, ended_at, session_id),
        )

    def update_session_origin(
        self, session_id: str, *, project_id: str | None, started_at: str | None
    ) -> None:
        """Fill in a project the session lacked, or move its start earlier. None means keep."""
        self._conn.execute(
            "UPDATE sessions SET project_id = COALESCE(?, project_id), "
            "started_at = COALESCE(?, started_at) WHERE id = ?",
            (project_id, started_at, session_id),
        )

    def list_sessions(
        self, *, project_id: str | None, outcome: SessionOutcome | None, page: Page
    ) -> Paged[SessionSummary]:
        clauses: list[str] = []
        params: list[Any] = []
        for column, value in (("s.project_id", project_id), ("s.outcome", outcome)):
            if value is not None:
                clauses.append(f"{column} = ?")
                params.append(value)
        if page.cursor is not None:
            cursor_started, cursor_id = decode_cursor(page.cursor)
            clauses.append("(s.started_at < ? OR (s.started_at = ? AND s.id < ?))")
            params.extend([cursor_started, cursor_started, cursor_id])
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        rows = self._conn.execute(
            f"{_SESSION_SUMMARY} {where} ORDER BY s.started_at DESC, s.id DESC LIMIT ?",
            [*params, page.limit + 1],
        ).fetchall()
        items = [SessionSummary.model_validate(dict(row)) for row in rows[: page.limit]]
        has_more = len(rows) > page.limit
        next_cursor = encode_cursor(items[-1].started_at, items[-1].id) if has_more else None
        return Paged[SessionSummary](items=self._with_session_costs(items), next_cursor=next_cursor)

    def get_session(self, session_id: str) -> SessionSummary | None:
        row = self._conn.execute(f"{_SESSION_SUMMARY} WHERE s.id = ?", (session_id,)).fetchone()
        if row is None:
            return None
        return self._with_session_costs([SessionSummary.model_validate(dict(row))])[0]

    def _with_session_costs(self, sessions: list[SessionSummary]) -> list[SessionSummary]:
        """Fill `total_estimated_cost`/`currency`; both stay NULL when unknown or mixed."""
        if not sessions:
            return sessions
        placeholders = ", ".join("?" for _ in sessions)
        rows = self._conn.execute(
            _session_costed_events(f"WHERE u.session_id IN ({placeholders})")
            + f"SELECT session_id, {group_money('est')} AS cost, {GROUP_CURRENCY} AS currency "
            "FROM ev GROUP BY session_id",
            [session.id for session in sessions],
        ).fetchall()
        costs = {row["session_id"]: row for row in rows}
        return [
            session.model_copy(
                update={
                    "total_estimated_cost": money_from_scaled(costs[session.id]["cost"]),
                    "currency": costs[session.id]["currency"],
                }
            )
            if session.id in costs
            else session
            for session in sessions
        ]

    def session_events(self, session_id: str, limit: int) -> list[UsageEvent]:
        rows = self._conn.execute(
            f"SELECT {_EVENT_COLUMNS} FROM usage_events WHERE session_id = ? "
            "ORDER BY started_at ASC, id ASC LIMIT ?",
            (session_id, limit),
        ).fetchall()
        return self.with_costs([_event_from_row(row) for row in rows])

    def session_by_model(self, session_id: str) -> list[ModelBreakdown]:
        """Token sums cover only events that reported them, and stay NULL when none did."""
        rows = self._conn.execute(
            _session_costed_events("WHERE u.session_id = ?")
            + "SELECT model_id, COUNT(*) AS request_count, SUM(input_tokens) AS input_tokens, "
            "SUM(output_tokens) AS output_tokens, "
            "SUM(input_tokens IS NULL OR output_tokens IS NULL) AS events_with_unknown_tokens, "
            f"{group_money('est')} AS cost, {GROUP_CURRENCY} AS currency "
            "FROM ev GROUP BY model_id ORDER BY model_id",
            (session_id,),
        ).fetchall()
        return [
            ModelBreakdown(
                model_id=row["model_id"],
                request_count=row["request_count"],
                input_tokens=row["input_tokens"],
                output_tokens=row["output_tokens"],
                events_with_unknown_tokens=row["events_with_unknown_tokens"],
                estimated_cost=money_from_scaled(row["cost"]),
                currency=row["currency"],
            )
            for row in rows
        ]

    def set_session_outcome(self, session_id: str, outcome: SessionOutcome, source: str) -> bool:
        cursor = self._conn.execute(
            "UPDATE sessions SET outcome = ?, outcome_source = ? WHERE id = ?",
            (outcome, source, session_id),
        )
        return cursor.rowcount == 1

    # Retry groups

    def find_event_by_ref(self, ref: str) -> sqlite3.Row | None:
        """An event named by internal id, else by `source_event_id` (newest wins)."""
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT id, retry_group_id FROM usage_events WHERE id = ? OR source_event_id = ? "
            "ORDER BY id = ? DESC, started_at DESC, id DESC LIMIT 1",
            (ref, ref, ref),
        ).fetchone()
        return row

    def latest_session_event_with_fingerprint(
        self, session_id: str, fingerprint: str, at_or_before: str
    ) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self._conn.execute(
            "SELECT id, status, started_at, retry_group_id FROM usage_events "
            "WHERE session_id = ? AND request_fingerprint = ? AND started_at <= ? "
            "ORDER BY started_at DESC, id DESC LIMIT 1",
            (session_id, fingerprint, at_or_before),
        ).fetchone()
        return row

    def max_attempt(self, group_id: str) -> int:
        row = self._conn.execute(
            "SELECT COALESCE(MAX(attempt), 0) AS n FROM usage_events WHERE retry_group_id = ?",
            (group_id,),
        ).fetchone()
        return int(row["n"])

    def set_retry_group(
        self, event_id: str, *, group_id: str, retry_source: str, attempt: int
    ) -> None:
        self._conn.execute(
            "UPDATE usage_events SET retry_group_id = ?, retry_source = ?, attempt = ? "
            "WHERE id = ?",
            (group_id, retry_source, attempt, event_id),
        )

    # Attribution corrections

    def reference_exists(self, field: str, value: str) -> bool:
        table = ATTRIBUTION_TABLES[field]  # a fixed allow-list, never caller text
        row = self._conn.execute(f"SELECT 1 FROM {table} WHERE id = ?", (value,)).fetchone()
        return row is not None

    def session_project(self, session_id: str) -> str | None:
        row = self._conn.execute(
            "SELECT project_id FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return None if row is None else row["project_id"]

    def apply_attribution_changes(
        self, event: UsageEvent, changes: dict[str, str | None], *, changed_by: str
    ) -> None:
        """Update the event columns and audit each field whose value actually changes."""
        now = utc_now_z()
        for field, new_value in changes.items():
            old_value = getattr(event, field)
            if old_value == new_value:
                continue
            assert field in ATTRIBUTION_TABLES
            self._conn.execute(
                f"UPDATE usage_events SET {field} = ? WHERE id = ?", (new_value, event.id)
            )
            self._conn.execute(
                "INSERT INTO attribution_changes (id, usage_event_id, field, old_value, "
                "new_value, changed_by, changed_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (uuid.uuid4().hex, event.id, field, old_value, new_value, changed_by, now),
            )
