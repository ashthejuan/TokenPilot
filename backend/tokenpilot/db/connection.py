"""SQLite connection factory and transaction helper."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path


def connect(path: Path) -> sqlite3.Connection:
    """Open a connection with WAL, enforced foreign keys, and dict-like rows."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, isolation_level=None, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    return connection


@contextmanager
def transaction(connection: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Run a unit of work atomically; roll back on any exception, COMMIT included."""
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield connection
        connection.execute("COMMIT")
    except BaseException:
        # A failed COMMIT (SQLITE_BUSY/FULL/IOERR) leaves the shared connection
        # inside the transaction; roll back so later writes still work.
        if connection.in_transaction:
            connection.execute("ROLLBACK")
        raise
