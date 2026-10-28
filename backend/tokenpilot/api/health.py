"""Health endpoint. Phase 0 reads `PRAGMA user_version`; Phase 0 task 0.2 swaps in migrations."""

import sqlite3
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from tokenpilot.security import require_local_token

router = APIRouter(
    prefix="/api/v1",
    tags=["health"],
    dependencies=[Depends(require_local_token)],
)


def _probe(path: Path) -> tuple[str, int]:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(path)
        try:
            connection.execute("SELECT 1")
            row = connection.execute("PRAGMA user_version").fetchone()
        finally:
            connection.close()
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    return "ok", int(row[0] if row else 0)


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    db_status, schema_version = _probe(request.app.state.settings.db_path)
    return {"status": "ok", "db": db_status, "schema_version": schema_version}
