"""Fact builders so detector tests need no database.

`event()` builds one `EventFact` with priced, successful defaults; `ctx()`
wraps events (plus optional sessions/tasks) in a `DetectionContext` whose
`conn` is an in-memory dummy the Task 2.1 rules never touch.
"""

import itertools
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from tokenpilot.detectors.facts import DetectionContext, EventFact, SessionFact, TaskFact
from tokenpilot.detectors.thresholds import Thresholds

BASE = datetime(2026, 10, 28, 12, 0, 0, tzinfo=UTC)
_NOW = datetime(2026, 10, 28, 13, 0, 0, tzinfo=UTC)

_ids = itertools.count(1)


def event(**overrides: Any) -> EventFact:
    """One successful, priced event; every field is overridable by keyword."""
    values: dict[str, Any] = {
        "id": f"e{next(_ids)}",
        "project_id": "p1",
        "session_id": "s1",
        "task_id": None,
        "model_id": "fake-small",
        "status": "success",
        "request_fingerprint": "fp",
        "retry_group_id": None,
        "retry_source": None,
        "attempt": None,
        "error_category": None,
        "started_at": BASE,
        "completed_at": None,
        "input_tokens": 100,
        "output_tokens": 20,
        "est_cost": Decimal("0.10"),
        "currency": "USD",
        "intentional_repeat": False,
        "context_blocks": (),
    }
    values.update(overrides)
    if values["est_cost"] is None and "currency" not in overrides:
        # An unpriced event carries no currency (money is always paired).
        values["currency"] = None
    return EventFact(**values)


def session(**overrides: Any) -> SessionFact:
    """One session fact; every field is overridable by keyword."""
    values: dict[str, Any] = {
        "id": "s1",
        "project_id": "p1",
        "started_at": BASE,
        "ended_at": BASE,
        "outcome": "unknown",
        "outcome_source": None,
    }
    values.update(overrides)
    return SessionFact(**values)


def task(**overrides: Any) -> TaskFact:
    """One task fact; every field is overridable by keyword."""
    values: dict[str, Any] = {
        "id": "t1",
        "project_id": "p1",
        "session_id": "s1",
        "outcome": "unknown",
        "outcome_source": None,
    }
    values.update(overrides)
    return TaskFact(**values)


def ctx(
    events: list[EventFact],
    sessions: tuple[SessionFact, ...] = (),
    tasks: tuple[TaskFact, ...] = (),
    now: datetime = _NOW,
    **threshold_overrides: Any,
) -> DetectionContext:
    """A context over `events`; threshold knobs pass straight to `Thresholds`."""
    return DetectionContext(
        events=list(events),
        sessions={s.id: s for s in sessions},
        tasks={t.id: t for t in tasks},
        thresholds=Thresholds(**threshold_overrides),
        now=now,
        conn=sqlite3.connect(":memory:"),
    )
