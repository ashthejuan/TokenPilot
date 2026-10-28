"""Shared database handle: one connection, one lock, used by every route."""

import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request

from tokenpilot.db.connection import connect, transaction


class Database:
    """A single SQLite connection guarded by an RLock.

    Sync routes run in a threadpool, so the lock serialises access. `write()`
    adds a `BEGIN IMMEDIATE` transaction that commits on success and rolls
    back on any exception.
    """

    def __init__(self, path: Path) -> None:
        self.path = Path(path)
        self._connection = connect(self.path)
        self._lock = threading.RLock()

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            yield self._connection

    @contextmanager
    def write(self) -> Iterator[sqlite3.Connection]:
        with self._lock, transaction(self._connection) as connection:
            yield connection

    def close(self) -> None:
        with self._lock:
            self._connection.close()


def get_db(request: Request) -> Database:
    db: Database = request.app.state.db
    return db
