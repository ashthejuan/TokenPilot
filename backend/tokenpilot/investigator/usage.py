"""Record investigator Meta spend on the local ledger (Q6)."""

from __future__ import annotations

import logging
import sqlite3
import uuid

from tokenpilot.investigator.client import UsageFields
from tokenpilot.pricing.cost import record_cost
from tokenpilot.security import redact_text
from tokenpilot.timeutil import utc_now_z

logger = logging.getLogger("tokenpilot.investigator")

INTERNAL_PROJECT_ID = "tokenpilot-internal"
INTERNAL_PROJECT_NAME = "TokenPilot internal"


def record_investigator_usage(
    conn: sqlite3.Connection,
    *,
    investigation_id: str,
    model: str,
    usage: UsageFields,
    provider: str = "meta",
) -> None:
    """Insert one usage_events row for an investigator call; never raise to callers.

    Uses ``project_id="tokenpilot-internal"`` and ``session_id=investigation_id``.
    Does not store content. Costing uses the normal cost engine.
    """
    try:
        _ensure_internal_project(conn)
        now = utc_now_z()
        _ensure_investigation_session(conn, investigation_id, now)
        event_id = uuid.uuid4().hex
        idempotency_key = f"investigator:{investigation_id}:{event_id}"
        conn.execute(
            "INSERT INTO usage_events ("
            "id, source_event_id, idempotency_key, project_id, session_id, task_id, "
            "provider, model_id, input_tokens, output_tokens, cached_tokens, "
            "reasoning_tokens, usage_source, status, latency_ms, http_status, "
            "retry_group_id, retry_source, attempt, request_fingerprint, started_at, "
            "completed_at, metadata_json, error_category, benchmark_run_id, raw_event_json"
            ") VALUES (?, NULL, ?, ?, ?, NULL, ?, ?, ?, ?, ?, NULL, 'provider', 'success', "
            "NULL, NULL, NULL, NULL, NULL, NULL, ?, ?, '{}', NULL, NULL, NULL)",
            (
                event_id,
                idempotency_key,
                INTERNAL_PROJECT_ID,
                investigation_id,
                provider,
                model,
                usage.get("input_tokens"),
                usage.get("output_tokens"),
                usage.get("cached_tokens"),
                now,
                now,
            ),
        )
        record_cost(conn, event_id)
    except Exception as exc:
        logger.warning(
            "failed to record investigator usage for %s: %s",
            investigation_id,
            redact_text(f"{type(exc).__name__}: {exc}"),
        )


def _ensure_internal_project(conn: sqlite3.Connection) -> None:
    row = conn.execute(
        "SELECT id FROM projects WHERE id = ?", (INTERNAL_PROJECT_ID,)
    ).fetchone()
    if row is not None:
        return
    now = utc_now_z()
    conn.execute(
        "INSERT INTO projects (id, name, slug, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (INTERNAL_PROJECT_ID, INTERNAL_PROJECT_NAME, INTERNAL_PROJECT_ID, now, now),
    )


def _ensure_investigation_session(
    conn: sqlite3.Connection, investigation_id: str, started_at: str
) -> None:
    row = conn.execute(
        "SELECT id FROM sessions WHERE id = ?", (investigation_id,)
    ).fetchone()
    if row is not None:
        return
    conn.execute(
        "INSERT INTO sessions (id, project_id, external_session_id, source, started_at) "
        "VALUES (?, ?, ?, 'investigator', ?)",
        (investigation_id, INTERNAL_PROJECT_ID, investigation_id, started_at),
    )
