"""Resolve insight evidence refs to ledger rows (or mark them unresolved)."""

import sqlite3

from tokenpilot.detectors.base import EvidenceRef
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.insights import EvidenceRefOut, ResolvedEvidence, TaskRef
from tokenpilot.schemas.sessions import SessionSummary
from tokenpilot.schemas.usage import UsageEvent


def _ref_out(ref: EvidenceRef) -> EvidenceRefOut:
    return EvidenceRefOut(kind=ref.kind, id=ref.id, measurement=dict(ref.measurement))


def resolve_evidence(conn: sqlite3.Connection, refs: list[EvidenceRef]) -> list[ResolvedEvidence]:
    """Resolve each ref with one query per kind. Missing rows stay `resolved: false`."""
    if not refs:
        return []

    event_ids = sorted({ref.id for ref in refs if ref.kind == "usage_event"})
    session_ids = sorted({ref.id for ref in refs if ref.kind == "session"})
    task_ids = sorted({ref.id for ref in refs if ref.kind == "task"})
    benchmark_ids = sorted({ref.id for ref in refs if ref.kind == "benchmark_run"})
    repository = LedgerRepository(conn)

    events_by_id: dict[str, UsageEvent] = {}
    if event_ids:
        placeholders = ", ".join("?" for _ in event_ids)
        rows = conn.execute(
            "SELECT id, source_event_id, idempotency_key, project_id, session_id, task_id, "
            "provider, model_id, input_tokens, output_tokens, cached_tokens, reasoning_tokens, "
            "usage_source, status, latency_ms, http_status, retry_group_id, retry_source, "
            "attempt, request_fingerprint, started_at, completed_at, error_category, "
            "benchmark_run_id, metadata_json FROM usage_events WHERE id IN "
            f"({placeholders})",
            event_ids,
        ).fetchall()
        loaded = repository.with_costs([UsageEvent.from_ledger_row(row) for row in rows])
        events_by_id = {event.id: event for event in loaded}

    # Sessions go through get_session so costs match the sessions API (typically ≤1 id).
    sessions_by_id: dict[str, SessionSummary] = {}
    for session_id in session_ids:
        session = repository.get_session(session_id)
        if session is not None:
            sessions_by_id[session_id] = session

    tasks_by_id: dict[str, TaskRef] = {}
    if task_ids:
        placeholders = ", ".join("?" for _ in task_ids)
        rows = conn.execute(
            "SELECT id, project_id, external_task_id, outcome FROM tasks WHERE id IN "
            f"({placeholders})",
            task_ids,
        ).fetchall()
        tasks_by_id = {
            str(row["id"]): TaskRef(
                id=str(row["id"]),
                project_id=str(row["project_id"]),
                external_task_id=row["external_task_id"],
                outcome=str(row["outcome"]),
            )
            for row in rows
        }

    benchmarks_present: set[str] = set()
    if benchmark_ids:
        placeholders = ", ".join("?" for _ in benchmark_ids)
        rows = conn.execute(
            f"SELECT id FROM benchmark_runs WHERE id IN ({placeholders})", benchmark_ids
        ).fetchall()
        benchmarks_present = {str(row["id"]) for row in rows}

    resolved_rows: list[ResolvedEvidence] = []
    for ref in refs:
        out = _ref_out(ref)
        if ref.kind == "aggregate":
            resolved_rows.append(ResolvedEvidence(ref=out, resolved=True))
            continue
        if ref.kind == "usage_event":
            event = events_by_id.get(ref.id)
            resolved_rows.append(
                ResolvedEvidence(ref=out, resolved=event is not None, event=event)
            )
            continue
        if ref.kind == "session":
            session = sessions_by_id.get(ref.id)
            resolved_rows.append(
                ResolvedEvidence(ref=out, resolved=session is not None, session=session)
            )
            continue
        if ref.kind == "task":
            task = tasks_by_id.get(ref.id)
            resolved_rows.append(
                ResolvedEvidence(ref=out, resolved=task is not None, task=task)
            )
            continue
        if ref.kind == "benchmark_run":
            resolved_rows.append(
                ResolvedEvidence(ref=out, resolved=ref.id in benchmarks_present)
            )
            continue
        resolved_rows.append(ResolvedEvidence(ref=out, resolved=False))
    return resolved_rows
