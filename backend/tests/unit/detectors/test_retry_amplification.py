"""Detector B: retries multiplying one request's cost."""

from datetime import timedelta
from decimal import Decimal
from typing import Any

from tests.unit.detectors.conftest import BASE, ctx, event
from tokenpilot.detectors.facts import EventFact
from tokenpilot.detectors.retry_amplification import RetryAmplificationDetector

DETECTOR = RetryAmplificationDetector()


def _chain(
    costs: tuple[Decimal | None, ...],
    *,
    group: str = "g1",
    source: str = "explicit",
    statuses: tuple[str, ...] = ("error", "error", "success"),
    categories: tuple[str | None, ...] = ("rate_limited", "rate_limited", None),
    **overrides: Any,
) -> list[EventFact]:
    return [
        event(
            id=f"{group}-a{i + 1}",
            started_at=BASE + timedelta(seconds=10 * i),
            status=statuses[i],
            error_category=categories[i],
            est_cost=cost,
            retry_group_id=group,
            retry_source=source,
            attempt=i + 1,
            **overrides,
        )
        for i, cost in enumerate(costs)
    ]


def test_retry_cost_sums_attempts_after_first() -> None:
    findings = DETECTOR.detect(
        ctx(_chain((Decimal("0.10"), Decimal("0.10"), Decimal("0.12"))))
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "retry_amplification"
    assert finding.anchor == "g1"
    assert finding.dedupe_key == "retry_amplification.v1:g1"
    assert finding.measurements["attempts"] == 3
    assert finding.measurements["retry_attempts"] == 2
    assert finding.measurements["retry_cost"] == 0.22
    assert finding.measurements["unknown_cost_attempts"] == 0
    assert finding.measurements["final_status"] == "success"
    assert finding.measurements["retry_source"] == "explicit"
    assert finding.estimated_impact == Decimal("0.22")
    assert finding.impact_currency == "USD"
    assert finding.severity == "medium"


def test_retry_with_unknown_cost_reports_partial() -> None:
    findings = DETECTOR.detect(ctx(_chain((Decimal("0.10"), None, Decimal("0.12")))))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.measurements["unknown_cost_attempts"] == 1
    assert finding.measurements["retry_cost"] == 0.12
    assert finding.estimated_impact == Decimal("0.12")


def test_retry_reports_error_categories() -> None:
    findings = DETECTOR.detect(
        ctx(_chain((Decimal("0.10"), Decimal("0.10"), Decimal("0.12"))))
    )

    assert findings[0].measurements["error_categories"] == {"rate_limited": 2}


def test_explicit_vs_inferred_confidence() -> None:
    explicit = DETECTOR.detect(ctx(_chain((Decimal("0.10"), Decimal("0.10")))))
    inferred = DETECTOR.detect(
        ctx(_chain((Decimal("0.10"), Decimal("0.10")), group="g2", source="inferred"))
    )

    assert explicit[0].confidence == 0.95
    assert inferred[0].confidence == 0.75


def test_single_attempt_group_below_threshold_not_flagged() -> None:
    lone = event(
        id="solo", retry_group_id="g9", retry_source="explicit", attempt=1, status="error"
    )

    assert DETECTOR.detect(ctx([lone])) == []
    assert DETECTOR.detect(ctx(_chain((Decimal("0.10"),) * 3), retry_min_attempts=4)) == []
