"""Detector E: input/output token ratios, diagnostic only.

Only successful events with both token counts known and enough input are
considered (P15). An event is flagged when it produced no output or its
input/output ratio reaches `ratio_threshold`. Findings are capped at `low`
and carry `diagnostic_only`: a high ratio is a signal to inspect, never a
verdict of waste.
"""

from typing import Any

from tokenpilot.detectors.base import EvidenceRef, Finding, Scope, Severity
from tokenpilot.detectors.facts import DetectionContext, EventFact

RULE_ID = "context_ratio"
RULE_VERSION = 1


class ContextRatioDetector:
    """Flags sessions whose requests carry large inputs for small outputs."""

    rule_id = RULE_ID
    rule_version = RULE_VERSION
    guidance = (
        "Some requests carried a large input for a small output. This is "
        "diagnostic only: inspect whether the input was necessary context or "
        "could be trimmed, cached, or retrieved in smaller pieces."
    )

    def detect(self, ctx: DetectionContext) -> list[Finding]:
        """One finding per session with flagged events, by anchor."""
        flagged = [event for event in ctx.events if _flagged(event, ctx)]
        by_session: dict[str | None, list[EventFact]] = {}
        for event in flagged:
            by_session.setdefault(event.session_id, []).append(event)
        findings: list[Finding] = []
        for session_id in sorted(by_session, key=lambda s: s or ""):
            ordered = sorted(by_session[session_id], key=lambda e: (e.started_at, e.id))
            if session_id is None:
                findings.extend(_finding_single(event, ctx) for event in ordered)
            else:
                findings.append(_finding_session(session_id, ordered, ctx))
        findings.sort(key=lambda f: f.anchor)
        return findings


def _flagged(event: EventFact, ctx: DetectionContext) -> bool:
    """Whether the event is a candidate whose ratio (or zero output) flags it."""
    if event.status != "success":
        return False
    if event.input_tokens is None or event.output_tokens is None:
        return False
    if event.input_tokens < ctx.thresholds.ratio_min_input_tokens:
        return False
    if event.output_tokens == 0:
        return True
    return event.input_tokens / event.output_tokens >= ctx.thresholds.ratio_threshold


def _event_ratio(event: EventFact) -> float | None:
    """The finite ratio, or `None` for zero output (already flagged)."""
    if event.output_tokens in (None, 0) or event.input_tokens is None:
        return None
    return event.input_tokens / event.output_tokens


def _group_measurements(
    ordered: list[EventFact], ctx: DetectionContext
) -> dict[str, Any]:
    finite = [ratio for event in ordered if (ratio := _event_ratio(event)) is not None]
    return {
        "diagnostic_only": True,
        "flagged_event_count": len(ordered),
        "ratio": max(finite) if finite else None,
        "zero_output": any(event.output_tokens == 0 for event in ordered),
        "ratio_threshold": ctx.thresholds.ratio_threshold,
        "min_input_tokens": ctx.thresholds.ratio_min_input_tokens,
    }


def _event_ref(event: EventFact) -> EvidenceRef:
    return EvidenceRef(
        kind="usage_event",
        id=event.id,
        measurement={
            "input_tokens": event.input_tokens,
            "output_tokens": event.output_tokens,
            "ratio": _event_ratio(event),
        },
    )


def _severity(count: int, ctx: DetectionContext) -> Severity:
    return "low" if count >= ctx.thresholds.ratio_low_min_events else "informational"


def _summary(ordered: list[EventFact], where: str) -> str:
    if len(ordered) == 1 and ordered[0].output_tokens == 0:
        return (
            f"1 request {where} used {ordered[0].input_tokens} input tokens and "
            "produced no output (diagnostic only)."
        )
    return (
        f"{len(ordered)} requests {where} had a high input/output ratio "
        "(diagnostic only)."
    )


def _finding_session(
    session_id: str, ordered: list[EventFact], ctx: DetectionContext
) -> Finding:
    session = ctx.sessions.get(session_id)
    return Finding(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        anchor=f"session:{session_id}",
        severity=_severity(len(ordered), ctx),
        confidence=0.30,
        title=f"High context ratio ({len(ordered)} requests)",
        summary=_summary(ordered, "in this session"),
        scope=Scope(
            project_id=session.project_id if session else ordered[0].project_id,
            session_id=session_id,
        ),
        evidence=[_event_ref(event) for event in ordered],
        measurements=_group_measurements(ordered, ctx),
        estimated_impact=None,
        impact_currency=None,
    )


def _finding_single(event: EventFact, ctx: DetectionContext) -> Finding:
    return Finding(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        anchor=f"event:{event.id}",
        severity="informational",
        confidence=0.30,
        title="High context ratio (1 request)",
        summary=_summary([event], "outside any session"),
        scope=Scope(project_id=event.project_id),
        evidence=[_event_ref(event)],
        measurements=_group_measurements([event], ctx),
        estimated_impact=None,
        impact_currency=None,
    )
