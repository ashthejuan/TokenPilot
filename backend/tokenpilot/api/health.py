"""Local health probe: process up, database reachable, schema migrated."""

import sqlite3
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException

from tokenpilot.db.database import Database, get_db
from tokenpilot.db.migrate import current_version

router = APIRouter(prefix="/api/v1", tags=["health"])


@router.get("/health")
def health(db: Annotated[Database, Depends(get_db)]) -> dict[str, Any]:
    try:
        with db.read() as connection:
            connection.execute("SELECT 1")
            schema_version = current_version(connection)
    except sqlite3.Error as exc:
        raise HTTPException(status_code=503, detail="database unavailable") from exc

    if schema_version == 0:
        raise HTTPException(status_code=503, detail="database is not migrated")

    return {
        "status": "ok",
        "db": "ok",
        "schema_version": schema_version,
        "db_path": str(db.path.resolve()),
    }
