"""Detector D: money spent on work that never succeeded.

The task scope runs first (`failed | abandoned` tasks), then the session scope
(`failure | abandoned` sessions) sums only the events no task finding covered,
so no dollar is counted twice (P13). Either scope fires only when the known
USD sum reaches `unsuccessful_min_cost`; unknown outcomes and non-USD groups
never fire (P8/P9).
"""

from decimal import Decimal

from tokenpilot.detectors.base import EvidenceRef, Finding, Scope
from tokenpilot.detectors.facts import (
    DetectionContext,
    EventFact,
    SessionFact,
    TaskFact,
)
from tokenpilot.detectors.severity import cost_severity, format_money, usd_known_sum
from tokenpilot.detectors.thresholds import THRESHOLD_CURRENCY

RULE_ID = "unsuccessful_task"
RULE_VERSION = 1

_TASK_FAILURE = frozenset({"failed", "abandoned"})
_SESSION_FAILURE = frozenset({"failure", "abandoned"})


class UnsuccessfulTaskDetector:
    """Flags failed or abandoned tasks, then failed or abandoned sessions, over cost."""

    rule_id = RULE_ID
    rule_version = RULE_VERSION
    guidance = (
        "This work ended unsuccessfully after spending real money. Inspect the "
        "evidence to see where the cost went, fix the underlying failure, and "
        "avoid re-running the same expensive path unchanged."
    )

    def detect(self, ctx: DetectionContext) -> list[Finding]:
        """Task findings first, then session findings over the uncovered events."""
        by_task: dict[str, list[EventFact]] = {}
        for event in ctx.events:
            if event.task_id is not None:
                by_task.setdefault(event.task_id, []).append(event)
        findings: list[Finding] = []
        covered: set[str] = set()
        for task_id in sorted(by_task):
            task = ctx.tasks.get(task_id)
            if task is None or task.outcome not in _TASK_FAILURE:
                continue
            ordered = sorted(by_task[task_id], key=lambda e: (e.started_at, e.id))
            total, unknown, comparable = _evaluable_total(
                ordered, ctx.thresholds.unsuccessful_min_cost
            )
            if total is None:
                continue
            findings.append(_task_finding(task, ordered, total, unknown, comparable, ctx))
            covered.update(event.id for event in ordered)
        for session_id in sorted(ctx.sessions):
            session = ctx.sessions[session_id]
            if session.outcome not in _SESSION_FAILURE:
                continue
            ordered = sorted(
                (
                    event
                    for event in ctx.events
                    if event.session_id == session_id and event.id not in covered
                ),
                key=lambda e: (e.started_at, e.id),
            )
            total, unknown, comparable = _evaluable_total(
                ordered, ctx.thresholds.unsuccessful_min_cost
            )
            if total is None:
                continue
            findings.append(
                _session_finding(session, ordered, total, unknown, comparable, ctx)
            )
        findings.sort(key=lambda f: f.anchor)
        return findings


def _evaluable_total(
    ordered: list[EventFact], minimum: Decimal
) -> tuple[Decimal | None, int, bool]:
    """The known USD sum when it clears `minimum`, else `None` (P8/P9)."""
    known, unknown, comparable = usd_known_sum(ordered)
    total = known if comparable else None
    if total is None or total < minimum:
        return None, unknown, comparable
    return total, unknown, comparable


def _event_ref(event: EventFact) -> EvidenceRef:
    return EvidenceRef(
        kind="usage_event",
        id=event.id,
        measurement={
            "est_cost": None if event.est_cost is None else float(event.est_cost),
            "currency": event.currency,
        },
    )


def _unknown_text(unknown: int) -> str:
    return f" ({unknown} with unknown cost)" if unknown else ""


def _task_finding(
    task: TaskFact,
    ordered: list[EventFact],
    total: Decimal,
    unknown: int,
    comparable: bool,
    ctx: DetectionContext,
) -> Finding:
    return Finding(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        anchor=f"task:{task.id}",
        severity=cost_severity(total, ctx.thresholds),
        confidence=0.90 if task.outcome_source == "manual" else 0.70,
        title=f"Unsuccessful task ({task.outcome})",
        summary=(
            f"Task ended '{task.outcome}' after {len(ordered)} requests costing "
            f"${format_money(total)}{_unknown_text(unknown)}."
        ),
        scope=Scope(
            project_id=task.project_id, session_id=task.session_id, task_id=task.id
        ),
        evidence=[_event_ref(event) for event in ordered]
        + [EvidenceRef(kind="task", id=task.id, measurement={"outcome": task.outcome})],
        measurements={
            "total_cost": float(total),
            "unknown_cost_events": unknown,
            "request_count": len(ordered),
            "outcome": task.outcome,
            "outcome_source": task.outcome_source,
            "currency": THRESHOLD_CURRENCY,
            "cost_comparable": comparable,
        },
        estimated_impact=total,
        impact_currency=THRESHOLD_CURRENCY,
    )


def _session_finding(
    session: SessionFact,
    ordered: list[EventFact],
    total: Decimal,
    unknown: int,
    comparable: bool,
    ctx: DetectionContext,
) -> Finding:
    return Finding(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        anchor=f"session:{session.id}",
        severity=cost_severity(total, ctx.thresholds),
        confidence=0.90 if session.outcome_source == "manual" else 0.70,
        title=f"Unsuccessful session ({session.outcome})",
        summary=(
            f"Session ended '{session.outcome}' after {len(ordered)} requests costing "
            f"${format_money(total)}{_unknown_text(unknown)}."
        ),
        scope=Scope(project_id=session.project_id, session_id=session.id),
        evidence=[_event_ref(event) for event in ordered]
        + [
            EvidenceRef(
                kind="session", id=session.id, measurement={"outcome": session.outcome}
            )
        ],
        measurements={
            "total_cost": float(total),
            "unknown_cost_events": unknown,
            "request_count": len(ordered),
            "outcome": session.outcome,
            "outcome_source": session.outcome_source,
            "currency": THRESHOLD_CURRENCY,
            "cost_comparable": comparable,
        },
        estimated_impact=total,
        impact_currency=THRESHOLD_CURRENCY,
    )
