"""Ledger facts: the read-only view detectors reason over.

`load_context` reads the scoped, costed ledger in one SQL pass (plus small
session/task lookups), excluding benchmark traffic (P7). Rules stay pure over
the returned `DetectionContext`, so they unit-test without a database (P4).

Client-supplied `metadata.context_blocks` sizes are untrusted. `_parse_block`
rejects entries whose `chars` or `approx_tokens` exceed physical caps so forged
or buggy values cannot inflate Detector C severity (D-2 Important #2):

- `MAX_CONTEXT_BLOCK_CHARS = 2_000_000`
- `MAX_CONTEXT_BLOCK_APPROX_TOKENS = 500_000`
"""

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, TypeGuard

from tokenpilot.detectors.thresholds import Thresholds
from tokenpilot.pricing.cost import latest_cost_sql
from tokenpilot.timeutil import parse_utc_z

# Physical enough for real prompts; non-physical client forgeries (e.g. 10**12) drop.
MAX_CONTEXT_BLOCK_CHARS = 2_000_000
MAX_CONTEXT_BLOCK_APPROX_TOKENS = 500_000


@dataclass(frozen=True, slots=True)
class ContextBlockFact:
    """One `metadata.context_blocks` entry: a hash plus its size, never its text."""

    hash: str
    chars: int
    approx_tokens: int


@dataclass(frozen=True, slots=True)
class EventFact:
    """A usage event with its latest estimated cost, ready for rule math."""

    id: str
    project_id: str | None
    session_id: str | None
    task_id: str | None
    model_id: str
    status: str
    request_fingerprint: str | None
    retry_group_id: str | None
    retry_source: str | None
    attempt: int | None
    error_category: str | None
    started_at: datetime
    completed_at: datetime | None
    input_tokens: int | None
    output_tokens: int | None
    est_cost: Decimal | None
    currency: str | None
    intentional_repeat: bool
    context_blocks: tuple[ContextBlockFact, ...]


@dataclass(frozen=True, slots=True)
class SessionFact:
    """A session's span and outcome; `unknown` is never failure."""

    id: str
    project_id: str | None
    started_at: datetime
    ended_at: datetime | None
    outcome: str
    outcome_source: str | None


@dataclass(frozen=True, slots=True)
class TaskFact:
    """A task's outcome; `unknown` is never failure."""

    id: str
    project_id: str | None
    session_id: str | None
    outcome: str
    outcome_source: str | None


@dataclass(frozen=True)
class AnalysisScope:
    """Which slice of the ledger to analyze; `None` means unscoped."""

    project_id: str | None = None
    session_id: str | None = None


@dataclass
class DetectionContext:
    """Everything the rules see: facts, thresholds, `now`, and the read connection."""

    events: list[EventFact]
    sessions: dict[str, SessionFact]
    tasks: dict[str, TaskFact]
    thresholds: Thresholds
    now: datetime
    conn: sqlite3.Connection


def _is_count(value: Any) -> TypeGuard[int]:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def _parse_block(item: Any) -> ContextBlockFact | None:
    """Parse one context block; return None when malformed or over size caps."""
    if not isinstance(item, dict):
        return None
    block_hash = item.get("hash")
    chars = item.get("chars")
    approx_tokens = item.get("approx_tokens")
    if not isinstance(block_hash, str) or not block_hash:
        return None
    if not _is_count(chars) or not _is_count(approx_tokens):
        return None
    if chars > MAX_CONTEXT_BLOCK_CHARS or approx_tokens > MAX_CONTEXT_BLOCK_APPROX_TOKENS:
        return None
    return ContextBlockFact(hash=block_hash, chars=chars, approx_tokens=approx_tokens)


def _parse_metadata(raw: str) -> tuple[bool, tuple[ContextBlockFact, ...]]:
    """Only `intentional_repeat` and `context_blocks` are read; bad blocks are skipped."""
    try:
        metadata = json.loads(raw)
    except ValueError:
        return False, ()
    if not isinstance(metadata, dict):
        return False, ()
    intentional = metadata.get("intentional_repeat") is True
    raw_blocks = metadata.get("context_blocks")
    if not isinstance(raw_blocks, list):
        return intentional, ()
    blocks = [block for item in raw_blocks if (block := _parse_block(item)) is not None]
    return intentional, tuple(blocks)


_EVENT_COLUMNS = (
    "u.id, u.project_id, u.session_id, u.task_id, u.model_id, u.status, "
    "u.request_fingerprint, u.retry_group_id, u.retry_source, u.attempt, "
    "u.error_category, u.started_at, u.completed_at, u.input_tokens, "
    "u.output_tokens, u.metadata_json, lc.estimated_cost, lc.currency"
)


def _event_from_row(row: sqlite3.Row) -> EventFact:
    raw_cost = row["estimated_cost"]
    est_cost = None if raw_cost is None else Decimal(str(raw_cost))
    intentional, blocks = _parse_metadata(row["metadata_json"])
    completed = row["completed_at"]
    return EventFact(
        id=row["id"],
        project_id=row["project_id"],
        session_id=row["session_id"],
        task_id=row["task_id"],
        model_id=row["model_id"],
        status=row["status"],
        request_fingerprint=row["request_fingerprint"],
        retry_group_id=row["retry_group_id"],
        retry_source=row["retry_source"],
        attempt=row["attempt"],
        error_category=row["error_category"],
        started_at=parse_utc_z(row["started_at"]),
        completed_at=None if completed is None else parse_utc_z(completed),
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        est_cost=est_cost,
        # Money is always paired: an unpriced event carries no currency.
        currency=row["currency"] if est_cost is not None else None,
        intentional_repeat=intentional,
        context_blocks=blocks,
    )


def _scoped_rows(
    conn: sqlite3.Connection, table: str, columns: str, scope: AnalysisScope
) -> list[sqlite3.Row]:
    """Session/task rows matching the scope; `table` is a fixed caller constant."""
    if scope.session_id is not None and table == "sessions":
        return conn.execute(
            f"SELECT {columns} FROM sessions WHERE id = ? ORDER BY started_at, id",
            (scope.session_id,),
        ).fetchall()
    clauses: list[str] = []
    params: list[str] = []
    if scope.session_id is not None:
        clauses.append("session_id = ?")
        params.append(scope.session_id)
    if scope.project_id is not None:
        clauses.append("project_id = ?")
        params.append(scope.project_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    order = "ORDER BY started_at, id" if table == "sessions" else "ORDER BY id"
    return conn.execute(f"SELECT {columns} FROM {table} {where} {order}", params).fetchall()


def _load_sessions(conn: sqlite3.Connection, scope: AnalysisScope) -> dict[str, SessionFact]:
    rows = _scoped_rows(
        conn, "sessions", "id, project_id, started_at, ended_at, outcome, outcome_source", scope
    )
    sessions: dict[str, SessionFact] = {}
    for row in rows:
        ended = row["ended_at"]
        sessions[row["id"]] = SessionFact(
            id=row["id"],
            project_id=row["project_id"],
            started_at=parse_utc_z(row["started_at"]),
            ended_at=None if ended is None else parse_utc_z(ended),
            outcome=row["outcome"],
            outcome_source=row["outcome_source"],
        )
    return sessions


def _load_tasks(conn: sqlite3.Connection, scope: AnalysisScope) -> dict[str, TaskFact]:
    rows = _scoped_rows(
        conn, "tasks", "id, project_id, session_id, outcome, outcome_source", scope
    )
    return {
        row["id"]: TaskFact(
            id=row["id"],
            project_id=row["project_id"],
            session_id=row["session_id"],
            outcome=row["outcome"],
            outcome_source=row["outcome_source"],
        )
        for row in rows
    }


def load_context(
    conn: sqlite3.Connection, scope: AnalysisScope, thresholds: Thresholds, now: datetime
) -> DetectionContext:
    """The scoped facts with latest costs, in time order; benchmark traffic excluded (P7)."""
    clauses = ["u.benchmark_run_id IS NULL"]
    params: list[str] = []
    if scope.project_id is not None:
        clauses.append("u.project_id = ?")
        params.append(scope.project_id)
    if scope.session_id is not None:
        clauses.append("u.session_id = ?")
        params.append(scope.session_id)
    rows = conn.execute(
        f"WITH {latest_cost_sql} SELECT {_EVENT_COLUMNS} FROM usage_events u "
        "LEFT JOIN latest_costs lc ON lc.usage_event_id = u.id "
        f"WHERE {' AND '.join(clauses)} ORDER BY u.started_at, u.id",
        params,
    ).fetchall()
    return DetectionContext(
        events=[_event_from_row(row) for row in rows],
        sessions=_load_sessions(conn, scope),
        tasks=_load_tasks(conn, scope),
        thresholds=thresholds,
        now=now,
        conn=conn,
    )
