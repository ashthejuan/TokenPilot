"""Resolve caller-supplied references (project id or slug) to stored rows."""

import re
import sqlite3

from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.schemas.common import SLUG_PATTERN

_SLUG = re.compile(SLUG_PATTERN)


class LedgerRefError(ValueError):
    """A reference the caller supplied cannot be honoured. `code` is the API error code."""

    code = "invalid_reference"


class ProjectRefError(LedgerRefError):
    code = "invalid_project_ref"


class BenchmarkRunRefError(LedgerRefError):
    code = "unknown_benchmark_run"


def resolve_project_ref(conn: sqlite3.Connection, ref: str) -> str:
    """Return a project id for an id or slug, creating `{name: ref, slug: ref}` if new.

    An explicit identifier is the strongest attribution signal (FR-02), so an
    unknown but well-formed ref creates the project instead of being dropped.
    """
    row = conn.execute(
        "SELECT id FROM projects WHERE id = ? OR slug = ? ORDER BY id = ? DESC LIMIT 1",
        (ref, ref, ref),
    ).fetchone()
    if row is not None:
        return str(row["id"])
    if not _SLUG.match(ref):
        raise ProjectRefError(f"project reference {ref!r} is not a project id or a valid slug")
    return LedgerRepository(conn).create_project(name=ref, slug=ref).id
