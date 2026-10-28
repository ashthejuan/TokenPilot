"""Shared rule math: USD-gated sums, cost severity, evidence caps (P8-P10, P17)."""

from collections.abc import Iterable
from decimal import Decimal

from tokenpilot.detectors.base import MAX_EVIDENCE, EvidenceRef, Severity
from tokenpilot.detectors.facts import EventFact
from tokenpilot.detectors.thresholds import THRESHOLD_CURRENCY, Thresholds


def usd_known_sum(events: Iterable[EventFact]) -> tuple[Decimal | None, int, bool]:
    """`(known_sum, unknown_cost_events, cost_comparable)` over `events` (P8/P9).

    Only known USD costs enter the sum; NULL costs are counted, never imputed.
    `cost_comparable` is False when any known cost is not USD (or has no
    currency at all), in which case callers must not use the sum.
    """
    total = Decimal("0")
    known_usd = 0
    unknown = 0
    comparable = True
    for event in events:
        if event.est_cost is None:
            unknown += 1
        elif event.currency != THRESHOLD_CURRENCY:
            comparable = False
        else:
            total += event.est_cost
            known_usd += 1
    return (total if known_usd else None), unknown, comparable


def cost_severity(impact: Decimal | None, t: Thresholds) -> Severity:
    """Severity bands over a USD impact (P10); NULL impact is `low`, never zero-guessed."""
    if impact is None:
        return "low"
    if impact >= t.severity_high_cost:
        return "high"
    if impact >= t.severity_medium_cost:
        return "medium"
    return "low"


def cap_evidence(refs: list[EvidenceRef]) -> tuple[list[EvidenceRef], int]:
    """The first `MAX_EVIDENCE` refs plus the truncated remainder count (P17)."""
    return refs[:MAX_EVIDENCE], max(0, len(refs) - MAX_EVIDENCE)


def format_money(value: Decimal) -> str:
    """Shortest display form for summaries (`0.22`, not `0.2200000000`). Display only."""
    return repr(float(value))
