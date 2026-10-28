"""Local health probe: process up, database reachable, schema migrated."""

import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from tokenpilot.db.connection import connect
from tokenpilot.db.migrate import current_version

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health(request: Request) -> dict[str, Any]:
    db_path = request.app.state.settings.db_path
    try:
        connection = connect(db_path)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    try:
        connection.execute("SELECT 1")
        schema_version = current_version(connection)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc
    finally:
        connection.close()

    if schema_version == 0:
        raise HTTPException(status_code=503, detail="database is not migrated")

    return {
        "status": "ok",
        "db": "ok",
        "schema_version": schema_version,
        "db_path": str(db_path.resolve()),
    }
