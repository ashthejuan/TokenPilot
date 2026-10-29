"""Detector thresholds: code defaults plus a stored override (P20).

The cost criteria are always USD (P8); `THRESHOLD_CURRENCY` names that once so
the API and the UI cannot disagree. Every number must be positive, and the
money fields are Decimals so a saved threshold never drifts.
"""

import sqlite3
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from tokenpilot.schemas.common import Money
from tokenpilot.timeutil import utc_now_z

__all__ = [
    "THRESHOLDS_KEY",
    "THRESHOLD_CURRENCY",
    "Thresholds",
    "load_thresholds",
    "save_thresholds",
]

THRESHOLD_CURRENCY = "USD"
THRESHOLDS_KEY = "detector_thresholds"


class Thresholds(BaseModel):
    """Every knob a detector reads. A PUT replaces the whole object."""

    model_config = ConfigDict(extra="forbid")

    repeat_window_s: int = Field(default=300, gt=0)
    retry_min_attempts: int = Field(default=2, gt=0)
    unsuccessful_min_cost: Money = Field(default=Decimal("0.50"), gt=0)
    runaway_max_requests: int = Field(default=40, gt=0)
    runaway_max_cost: Money = Field(default=Decimal("2.00"), gt=0)
    runaway_max_duration_min: int = Field(default=60, gt=0)
    runaway_max_retries: int = Field(default=5, gt=0)
    open_session_grace_min: int = Field(default=15, gt=0)
    context_min_chars: int = Field(default=2000, gt=0)
    ratio_threshold: float = Field(default=50.0, gt=0)
    ratio_min_input_tokens: int = Field(default=20000, gt=0)
    context_repeat_min_occurrences: int = Field(default=3, gt=0)
    context_medium_repeated_tokens: int = Field(default=50000, gt=0)
    ratio_low_min_events: int = Field(default=5, gt=0)
    severity_high_cost: Money = Field(default=Decimal("1.00"), gt=0)
    severity_medium_cost: Money = Field(default=Decimal("0.10"), gt=0)


def load_thresholds(conn: sqlite3.Connection) -> Thresholds:
    """The stored thresholds, or the defaults when nothing was saved yet."""
    row = conn.execute(
        "SELECT value_json FROM app_settings WHERE key = ?", (THRESHOLDS_KEY,)
    ).fetchone()
    if row is None:
        return Thresholds()
    return Thresholds.model_validate_json(row["value_json"])


def save_thresholds(conn: sqlite3.Connection, t: Thresholds) -> None:
    """Replace the stored object. Callers own the transaction."""
    conn.execute(
        "INSERT INTO app_settings (key, value_json, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT (key) DO UPDATE SET value_json = excluded.value_json, "
        "updated_at = excluded.updated_at",
        (THRESHOLDS_KEY, t.model_dump_json(), utc_now_z()),
    )
