"""Detector A: the same successful request repeated in one session (P12).

Candidates are successes with no retry history (`attempt IS NULL OR attempt = 1`)
that the caller did not mark `intentional_repeat`. They cluster by session,
fingerprint and task; each link in the chain starts within `repeat_window_s`
of the previous one. The impact is the known cost of every cluster event
except the earliest.
"""

from collections.abc import Iterator

from tokenpilot.detectors.base import EvidenceRef, Finding, Scope
from tokenpilot.detectors.facts import DetectionContext, EventFact
from tokenpilot.detectors.severity import cost_severity, format_money, usd_known_sum

RULE_ID = "repeated_request"
RULE_VERSION = 1


class RepeatedRequestDetector:
    """Flags clusters of identical successes; a retry's success belongs to B."""

    rule_id = RULE_ID
    rule_version = RULE_VERSION
    guidance = (
        "The same request succeeded more than once in a short window. Check whether "
        "the caller lacks caching or repeats work unnecessarily; if the repeats are "
        "intentional, record metadata.intentional_repeat so this rule stays quiet."
    )

    def detect(self, ctx: DetectionContext) -> list[Finding]:
        """One finding per cluster of >= 2 chained repeats, ordered by anchor."""
        groups: dict[tuple[str, str, str | None], list[EventFact]] = {}
        for event in ctx.events:
            key = _candidate_key(event)
            if key is not None:
                groups.setdefault(key, []).append(event)
        findings: list[Finding] = []
        for (session_id, fingerprint, task_id), members in groups.items():
            ordered = sorted(members, key=lambda e: (e.started_at, e.id))
            for cluster in _clusters(ordered, ctx.thresholds.repeat_window_s):
                findings.append(_finding(cluster, session_id, fingerprint, task_id, ctx))
        findings.sort(key=lambda f: f.anchor)
        return findings


def _candidate_key(event: EventFact) -> tuple[str, str, str | None] | None:
    """The cluster key, or None when the event can never be a repeat (P12)."""
    if (
        event.status != "success"
        or event.attempt not in (None, 1)
        or event.request_fingerprint is None
        or event.session_id is None
        or event.intentional_repeat
    ):
        return None
    return (event.session_id, event.request_fingerprint, event.task_id)


def _clusters(ordered: list[EventFact], window_s: int) -> Iterator[list[EventFact]]:
    """Split time-ordered candidates wherever the gap exceeds the window."""
    current = [ordered[0]]
    for event in ordered[1:]:
        if (event.started_at - current[-1].started_at).total_seconds() <= window_s:
            current.append(event)
        else:
            if len(current) >= 2:
                yield current
            current = [event]
    if len(current) >= 2:
        yield current


def _ref(event: EventFact) -> EvidenceRef:
    return EvidenceRef(
        kind="usage_event",
        id=event.id,
        measurement={
            "est_cost": None if event.est_cost is None else float(event.est_cost),
            "currency": event.currency,
        },
    )


def _finding(
    cluster: list[EventFact],
    session_id: str,
    fingerprint: str,
    task_id: str | None,
    ctx: DetectionContext,
) -> Finding:
    first = cluster[0]
    known_sum, unknown, comparable = usd_known_sum(cluster[1:])
    impact = known_sum if comparable else None
    currency = "USD" if impact is not None else None
    window_s = ctx.thresholds.repeat_window_s
    cost_text = "an unknown amount" if impact is None else f"${format_money(impact)}"
    return Finding(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        anchor=f"{session_id}:{fingerprint}:{task_id or '-'}:{first.id}",
        severity=cost_severity(impact, ctx.thresholds),
        confidence=0.90,
        title=f"Repeated identical request ({len(cluster)} successes)",
        summary=(
            f"The same request succeeded {len(cluster)} times in session {session_id}, "
            f"each repeat within {window_s}s of the previous one; "
            f"the repeats cost {cost_text}."
        ),
        scope=Scope(project_id=first.project_id, session_id=session_id, task_id=task_id),
        evidence=[_ref(event) for event in cluster],
        measurements={
            "request_count": len(cluster),
            "repeat_cost": None if impact is None else float(impact),
            "unknown_cost_events": unknown,
            "currency": currency,
            "cost_comparable": comparable,
        },
        estimated_impact=impact,
        impact_currency=currency,
    )
