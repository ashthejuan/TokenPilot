"""Shared rule math: USD-gated sums, cost severity, evidence caps (P8-P10, P17)."""

from decimal import Decimal

from tests.unit.detectors.conftest import event
from tokenpilot.detectors.base import MAX_EVIDENCE, EvidenceRef
from tokenpilot.detectors.severity import cap_evidence, cost_severity, usd_known_sum
from tokenpilot.detectors.thresholds import Thresholds

T = Thresholds()


def test_cost_severity_bands() -> None:
    assert cost_severity(None, T) == "low"
    assert cost_severity(Decimal("0"), T) == "low"
    assert cost_severity(Decimal("0.05"), T) == "low"
    assert cost_severity(Decimal("0.10"), T) == "medium"
    assert cost_severity(Decimal("0.99"), T) == "medium"
    assert cost_severity(Decimal("1.00"), T) == "high"


def test_usd_known_sum_all_usd() -> None:
    events = [event(est_cost=Decimal("0.10")), event(est_cost=Decimal("0.12"))]

    assert usd_known_sum(events) == (Decimal("0.22"), 0, True)


def test_usd_known_sum_skips_unknown_without_imputing() -> None:
    events = [event(est_cost=Decimal("0.40")), event(est_cost=None)]

    assert usd_known_sum(events) == (Decimal("0.40"), 1, True)


def test_usd_known_sum_all_unknown() -> None:
    assert usd_known_sum([event(est_cost=None), event(est_cost=None)]) == (None, 2, True)


def test_usd_known_sum_mixed_currency_not_comparable() -> None:
    events = [event(est_cost=Decimal("0.10")), event(est_cost=Decimal("9.00"), currency="EUR")]

    known_sum, unknown, comparable = usd_known_sum(events)

    assert unknown == 0
    assert comparable is False
    assert known_sum == Decimal("0.10")


def test_cap_evidence_short_list_untouched() -> None:
    refs = [EvidenceRef(kind="usage_event", id=f"e{i}", measurement={}) for i in range(3)]

    assert cap_evidence(refs) == (refs, 0)


def test_cap_evidence_reports_truncation_count() -> None:
    refs = [EvidenceRef(kind="usage_event", id=f"e{i}", measurement={}) for i in range(60)]

    kept, truncated = cap_evidence(refs)

    assert len(kept) == MAX_EVIDENCE == 50
    assert truncated == 10
