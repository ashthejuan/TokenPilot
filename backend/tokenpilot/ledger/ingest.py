"""The write path: normalize, attribute, group retries, insert."""

import sqlite3
import uuid
from dataclasses import dataclass, replace

from tokenpilot.ledger.attribution import GatewayDefaults, resolve_attribution
from tokenpilot.ledger.normalize import normalize
from tokenpilot.ledger.refs import BenchmarkRunRefError, get_or_create_session
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.ledger.retry_grouping import assign_retry_group
from tokenpilot.schemas.usage import UsageEvent, UsageEventIn

__all__ = ["GatewayDefaults", "IngestResult", "ingest_event"]

# Set by the pipeline only: a caller's metadata cannot claim an attribution outcome.
_PIPELINE_METADATA_KEYS = ("attribution_basis", "unresolved_task_ref", "unresolved_project_ref")


@dataclass(frozen=True)
class IngestResult:
    event: UsageEvent
    created: bool


def ingest_event(
    conn: sqlite3.Connection,
    raw: UsageEventIn,
    source: str,
    defaults: GatewayDefaults | None = None,
    *,
    event_id: str | None = None,
) -> IngestResult:
    """Store one event. Call inside `Database.write()` so a batch commits as one unit."""
    normalized = normalize(raw, source)
    repository = LedgerRepository(conn)

    # A duplicate returns the stored row untouched: no new project, task, session or group.
    existing = repository.find_event_by_idempotency_key(normalized.idempotency_key)
    if existing is not None:
        return IngestResult(event=existing, created=False)

    if normalized.benchmark_run_id and not repository.benchmark_run_exists(
        normalized.benchmark_run_id
    ):
        raise BenchmarkRunRefError(f"unknown benchmark_run_id {normalized.benchmark_run_id!r}")

    attribution = resolve_attribution(conn, normalized, source, defaults)
    session_id = (
        get_or_create_session(
            conn,
            normalized.external_session_id,
            source,
            attribution.project_id,
            started_at=normalized.started_at,
        )
        if normalized.external_session_id
        else None
    )
    retry_group_id, retry_source, attempt = assign_retry_group(conn, normalized, session_id)

    metadata = {k: v for k, v in normalized.metadata.items() if k not in _PIPELINE_METADATA_KEYS}
    metadata["attribution_basis"] = attribution.basis
    if attribution.unresolved_task_ref:
        metadata["unresolved_task_ref"] = attribution.unresolved_task_ref
    if attribution.unresolved_project_ref:
        metadata["unresolved_project_ref"] = attribution.unresolved_project_ref

    event, created = repository.insert_event(
        replace(normalized, metadata=metadata),
        event_id=event_id or uuid.uuid4().hex,
        project_id=attribution.project_id,
        session_id=session_id,
        task_id=attribution.task_id,
        retry_group_id=retry_group_id,
        retry_source=retry_source,
        attempt=attempt,
    )
    return IngestResult(event=event, created=created)
