"""Retention delete: drop old usage events (and their cascaded rows) in one write."""

import shutil
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from tokenpilot.db.database import Database, get_db
from tokenpilot.schemas.settings import DataDeleteResponse
from tokenpilot.timeutil import to_utc_z

router = APIRouter(prefix="/api/v1/data", tags=["data"])


def _parse_before(value: str) -> tuple[str, float]:
    """Normalize an ISO 8601 bound to (`to_utc_z` string, epoch seconds)."""
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(
            status_code=422, detail=f"invalid 'before': {value!r}"
        ) from exc
    if parsed.tzinfo is None:
        raise HTTPException(status_code=422, detail=f"invalid 'before': {value!r}")
    aware = parsed.astimezone(UTC)
    return to_utc_z(aware), aware.timestamp()


@router.delete("", status_code=200)
def delete_data(
    before: Annotated[
        str, Query(description="ISO 8601 UTC bound; older events are deleted")
    ],
    request: Request,
    db: Annotated[Database, Depends(get_db)],
) -> DataDeleteResponse:
    bound, bound_epoch = _parse_before(before)
    with db.write() as conn:
        cursor = conn.execute("DELETE FROM usage_events WHERE started_at < ?", (bound,))
        deleted_events = cursor.rowcount or 0

    deleted_worktrees = 0
    benchmarks_dir = request.app.state.settings.data_dir / "benchmarks"
    if benchmarks_dir.is_dir():
        for child in sorted(benchmarks_dir.iterdir()):
            if not child.is_dir():
                continue
            try:
                if child.stat().st_mtime < bound_epoch:
                    shutil.rmtree(child)
                    deleted_worktrees += 1
            except OSError:
                continue

    # Content excerpts live in the database and cascade with their event;
    # there is no excerpt file storage in this phase.
    return DataDeleteResponse(
        deleted_events=deleted_events,
        deleted_excerpt_files=0,
        deleted_worktrees=deleted_worktrees,
    )
