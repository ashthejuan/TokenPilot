"""The write path: normalize, resolve references, insert."""

import sqlite3
import uuid
from dataclasses import dataclass

from tokenpilot.ledger.normalize import normalize
from tokenpilot.ledger.refs import BenchmarkRunRefError, resolve_project_ref
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.usage import UsageEvent, UsageEventIn


@dataclass(frozen=True)
class GatewayDefaults:
    """Project-level defaults a gateway request carries. Used from Task 1.2 on."""

    project_ref: str | None = None


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

    if normalized.benchmark_run_id and not repository.benchmark_run_exists(
        normalized.benchmark_run_id
    ):
        raise BenchmarkRunRefError(f"unknown benchmark_run_id {normalized.benchmark_run_id!r}")

    project_id = (
        resolve_project_ref(conn, normalized.project_id) if normalized.project_id else None
    )
    event, created = repository.insert_event(
        normalized,
        event_id=event_id or uuid.uuid4().hex,
        project_id=project_id,
        session_id=None,
        task_id=None,
        retry_group_id=None,
        retry_source=None,
        attempt=None,
    )
    return IngestResult(event=event, created=created)
