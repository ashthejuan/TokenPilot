"""Group attempts at the same request into retry groups (explicit, then inferred)."""

import sqlite3
import uuid
from datetime import timedelta
from typing import Literal

from tokenpilot.ledger.normalize import NormalizedEvent
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.timeutil import parse_utc_z

RetrySource = Literal["explicit", "inferred"]
INFERRED_RETRY_WINDOW = timedelta(seconds=120)
_FAILED = frozenset({"error", "timeout"})


def assign_retry_group(
    conn: sqlite3.Connection, e: NormalizedEvent, session_id: str | None
) -> tuple[str | None, RetrySource | None, int | None]:
    """Return `(retry_group_id, retry_source, attempt)` for a new event.

    Joining a group backfills the earlier event with `attempt = 1` when it had
    no group yet. Call before inserting `e`.
    """
    repository = LedgerRepository(conn)

    if e.retry_of:
        parent = repository.find_event_by_ref(e.retry_of)
        if parent is not None:
            return _join(repository, parent["id"], parent["retry_group_id"], "explicit")

    if session_id is not None and e.request_fingerprint is not None:
        earliest = parse_utc_z(e.started_at) - INFERRED_RETRY_WINDOW
        prior = repository.latest_session_event_with_fingerprint(
            session_id, e.request_fingerprint, e.started_at
        )
        if (
            prior is not None
            and prior["status"] in _FAILED
            and parse_utc_z(prior["started_at"]) >= earliest
        ):
            return _join(repository, prior["id"], prior["retry_group_id"], "inferred")

    return None, None, None


def _join(
    repository: LedgerRepository, parent_id: str, group_id: str | None, source: RetrySource
) -> tuple[str, RetrySource, int]:
    if group_id is None:
        group_id = uuid.uuid4().hex
        repository.set_retry_group(parent_id, group_id=group_id, retry_source=source, attempt=1)
    return group_id, source, repository.max_attempt(group_id) + 1
