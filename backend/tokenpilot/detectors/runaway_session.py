"""Detector F: sessions whose size, cost, span or retries ran past every bound.

A session fires when any criterion is strictly exceeded and its outcome is not
`success` (P14). A cost criterion over mixed or missing currencies is not
evaluable: it neither fires nor suppresses the other criteria (P8). Sessions
active within the grace window are reported as informational "possibly still
running" instead of a verdict.
"""

from datetime import datetime, timedelta

from tokenpilot.detectors.base import EvidenceRef, Finding, Scope, Severity
from tokenpilot.detectors.facts import DetectionContext, EventFact, SessionFact
from tokenpilot.detectors.severity import format_money, usd_known_sum
from tokenpilot.detectors.thresholds import THRESHOLD_CURRENCY

RULE_ID = "runaway_session"
RULE_VERSION = 1


class RunawaySessionDetector:
    """Flags sessions that blew past the runaway bounds without succeeding."""

    rule_id = RULE_ID
    rule_version = RULE_VERSION
    guidance = (
        "This session grew past the runaway bounds. If it is still running, stop "
        "it; otherwise inspect the evidence for loops, runaway retries, or an "
        "over-long task, and split or bound the work before re-running."
    )

    def detect(self, ctx: DetectionContext) -> list[Finding]:
        """One finding per over-bounds non-success session, by anchor."""
        findings: list[Finding] = []
        for session_id in sorted(ctx.sessions):
            session = ctx.sessions[session_id]
            if session.outcome == "success":
                continue
            ordered = sorted(
                (event for event in ctx.events if event.session_id == session_id),
                key=lambda e: (e.started_at, e.id),
            )
            finding = _finding(session, ordered, ctx)
            if finding is not None:
                findings.append(finding)
        findings.sort(key=lambda f: f.anchor)
        return findings


def _last_activity(session: SessionFact, ordered: list[EventFact]) -> datetime | None:
    """The latest known activity: the session end or the last event end."""
    end = session.ended_at
    if ordered:
        last_event = max(event.completed_at or event.started_at for event in ordered)
        end = last_event if end is None else max(end, last_event)
    return end


def _finding(
    session: SessionFact, ordered: list[EventFact], ctx: DetectionContext
) -> Finding | None:
    thresholds = ctx.thresholds
    known, unknown, comparable = usd_known_sum(ordered)
    total = known if comparable else None
    end = _last_activity(session, ordered)
    duration_min = (
        (end - session.started_at).total_seconds() / 60 if end is not None else None
    )
    retry_attempts = sum(
        1 for event in ordered if event.attempt is not None and event.attempt >= 2
    )
    tripped: list[str] = []
    if len(ordered) > thresholds.runaway_max_requests:
        tripped.append("requests")
    if total is not None and total > thresholds.runaway_max_cost:
        tripped.append("cost")
    if duration_min is not None and duration_min > thresholds.runaway_max_duration_min:
        tripped.append("duration")
    if retry_attempts > thresholds.runaway_max_retries:
        tripped.append("retries")
    if not tripped:
        return None
    possibly_running = end is not None and (
        ctx.now - end
    ) < timedelta(minutes=thresholds.open_session_grace_min)
    severity: Severity
    if possibly_running:
        severity = "informational"
    elif session.outcome in ("failure", "abandoned"):
        severity = "high"
    else:
        severity = "medium"
    cost_text = "unknown" if total is None else f"${format_money(total)}"
    duration_text = "unknown" if duration_min is None else f"{duration_min:.1f} min"
    title = (
        f"Possibly still running ({len(ordered)} requests)"
        if possibly_running
        else f"Runaway session ({', '.join(tripped)})"
    )
    currency = THRESHOLD_CURRENCY if total is not None else None
    return Finding(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        anchor=session.id,
        severity=severity,
        confidence=0.40 if possibly_running else 0.80,
        title=title,
        summary=(
            f"Session with {len(ordered)} requests costing {cost_text} over "
            f"{duration_text} ({retry_attempts} retries) exceeded: "
            f"{', '.join(tripped)}."
        ),
        scope=Scope(project_id=session.project_id, session_id=session.id),
        evidence=[
            EvidenceRef(
                kind="session",
                id=session.id,
                measurement={
                    "request_count": len(ordered),
                    "outcome": session.outcome,
                },
            )
        ]
        + [_event_ref(event) for event in ordered],
        measurements={
            "request_count": len(ordered),
            "total_cost": None if total is None else float(total),
            "duration_min": duration_min,
            "retry_attempts": retry_attempts,
            "tripped": tripped,
            "possibly_running": possibly_running,
            "outcome": session.outcome,
            "unknown_cost_events": unknown,
            "currency": currency,
            "cost_comparable": comparable,
        },
        estimated_impact=total,
        impact_currency=currency,
    )


def _event_ref(event: EventFact) -> EvidenceRef:
    return EvidenceRef(
        kind="usage_event",
        id=event.id,
        measurement={
            "est_cost": None if event.est_cost is None else float(event.est_cost),
            "currency": event.currency,
        },
    )
