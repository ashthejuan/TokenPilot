"""Versioned SQL migrations: `NNNN_name.sql`, applied once, in order."""

import sqlite3
from datetime import UTC, datetime
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).parent / "migrations"

_SCHEMA_MIGRATIONS_TABLE = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
)
"""


def utc_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def applied_versions(connection: sqlite3.Connection) -> set[int]:
    return {
        int(row["version"])
        for row in connection.execute("SELECT version FROM schema_migrations")
    }


def current_version(connection: sqlite3.Connection) -> int:
    """Highest applied migration, or 0 before the first migration."""
    has_table = connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'schema_migrations'"
    ).fetchone()
    if has_table is None:
        return 0
    row = connection.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
    return int(row["version"] or 0)


def migrate(connection: sqlite3.Connection) -> int:
    """Apply every pending migration and return the resulting schema version."""
    connection.execute(_SCHEMA_MIGRATIONS_TABLE)
    applied = applied_versions(connection)
    version = max(applied, default=0)

    for path in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
        number = int(path.name.split("_", 1)[0])
        if number in applied:
            continue
        sql = path.read_text(encoding="utf-8")
        timestamp = utc_now()
        # BEGIN/COMMIT live inside the script because executescript() commits
        # any pending transaction before it runs.
        script = (
            f"BEGIN IMMEDIATE;\n{sql}\n"
            "INSERT INTO schema_migrations (version, applied_at) "
            f"VALUES ({number}, '{timestamp}');\n"
            "COMMIT;"
        )
        try:
            connection.executescript(script)
        except sqlite3.Error:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        applied.add(number)
        version = number

    return version
