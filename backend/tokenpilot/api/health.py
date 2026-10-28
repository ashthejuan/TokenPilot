"""Local health probe: process up, database reachable, schema version known."""

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request

from tokenpilot.db.connection import connect
from tokenpilot.db.migrate import current_version
from tokenpilot.security import require_local_token

router = APIRouter(
    prefix="/api/v1",
    tags=["health"],
    dependencies=[Depends(require_local_token)],
)


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    settings = request.app.state.settings
    try:
        connection = connect(settings.db_path)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    try:
        connection.execute("SELECT 1")
        schema_version = current_version(connection)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    finally:
        connection.close()

    return {"status": "ok", "db": "ok", "schema_version": schema_version}
