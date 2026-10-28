"""Detector B: retries multiplying one request's cost.

Every retry group with at least `retry_min_attempts` events fires. The impact
is the known USD cost of the attempts after the first (P8/P9); the finding
also reports the error mix, the final status and the group's source.
"""

from tokenpilot.detectors.base import EvidenceRef, Finding, Scope
from tokenpilot.detectors.facts import DetectionContext, EventFact
from tokenpilot.detectors.severity import cost_severity, format_money, usd_known_sum

RULE_ID = "retry_amplification"
RULE_VERSION = 1


class RetryAmplificationDetector:
    """Flags retry groups; explicit links carry more confidence than inferred ones."""

    rule_id = RULE_ID
    rule_version = RULE_VERSION
    guidance = (
        "Retries multiplied this request's cost. Inspect the error categories: back "
        "off and retry rate limits, and fix persistent upstream or client errors "
        "instead of retrying them."
    )

    def detect(self, ctx: DetectionContext) -> list[Finding]:
        """One finding per group at or above the attempt threshold, by anchor."""
        groups: dict[str, list[EventFact]] = {}
        for event in ctx.events:
            if event.retry_group_id is not None:
                groups.setdefault(event.retry_group_id, []).append(event)
        findings: list[Finding] = []
        for group_id, members in groups.items():
            if len(members) < ctx.thresholds.retry_min_attempts:
                continue
            ordered = sorted(members, key=lambda e: (e.started_at, e.id))
            findings.append(_finding(group_id, ordered, ctx))
        findings.sort(key=lambda f: f.anchor)
        return findings


def _ref(event: EventFact) -> EvidenceRef:
    return EvidenceRef(
        kind="usage_event",
        id=event.id,
        measurement={
            "attempt": event.attempt,
            "est_cost": None if event.est_cost is None else float(event.est_cost),
            "currency": event.currency,
        },
    )


def _finding(group_id: str, ordered: list[EventFact], ctx: DetectionContext) -> Finding:
    first = ordered[0]
    known_sum, unknown, comparable = usd_known_sum(ordered[1:])
    retry_cost = known_sum if comparable else None
    currency = "USD" if retry_cost is not None else None
    error_categories: dict[str, int] = {}
    for event in ordered:
        if event.error_category is not None:
            error_categories[event.error_category] = error_categories.get(
                event.error_category, 0
            ) + 1
    source = next(
        (event.retry_source for event in ordered if event.retry_source is not None),
        "inferred",
    )
    retry_n = len(ordered) - 1
    retries_word = "retry" if retry_n == 1 else "retries"
    errors_text = (
        ", ".join(f"{name} x{count}" for name, count in error_categories.items())
        or "no recorded errors"
    )
    cost_text = "unknown" if retry_cost is None else f"${format_money(retry_cost)}"
    return Finding(
        rule_id=RULE_ID,
        rule_version=RULE_VERSION,
        anchor=group_id,
        severity=cost_severity(retry_cost, ctx.thresholds),
        confidence=0.95 if source == "explicit" else 0.75,
        title=f"Retry amplification ({len(ordered)} attempts)",
        summary=(
            f"{retry_n} {retries_word} of one request ({source} group); "
            f"errors: {errors_text}; retry cost {cost_text}."
        ),
        scope=Scope(
            project_id=first.project_id, session_id=first.session_id, task_id=first.task_id
        ),
        evidence=[_ref(event) for event in ordered],
        measurements={
            "attempts": len(ordered),
            "retry_attempts": retry_n,
            "error_categories": error_categories,
            "final_status": ordered[-1].status,
            "retry_cost": None if retry_cost is None else float(retry_cost),
            "unknown_cost_attempts": unknown,
            "currency": currency,
            "retry_source": source,
            "cost_comparable": comparable,
        },
        estimated_impact=retry_cost,
        impact_currency=currency,
    )
