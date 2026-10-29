"""Detector A: the same successful request repeated in one session (P12)."""

from datetime import timedelta
from decimal import Decimal

from tests.unit.detectors.conftest import BASE, ctx, event
from tokenpilot.detectors.repeated_request import RepeatedRequestDetector

DETECTOR = RepeatedRequestDetector()


def test_two_identical_successes_in_window_flagged() -> None:
    first = event(id="e1", started_at=BASE, est_cost=Decimal("0.10"))
    second = event(id="e2", started_at=BASE + timedelta(seconds=60), est_cost=Decimal("0.12"))

    findings = DETECTOR.detect(ctx([first, second]))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "repeated_request"
    assert finding.rule_version == 1
    assert finding.anchor == "s1:fp:-:e1"
    assert finding.dedupe_key == "repeated_request.v1:s1:fp:-:e1"
    assert [ref.id for ref in finding.evidence] == ["e1", "e2"]
    assert all(ref.kind == "usage_event" for ref in finding.evidence)
    assert finding.estimated_impact == Decimal("0.12")
    assert finding.impact_currency == "USD"
    assert finding.severity == "medium"
    assert finding.confidence == 0.90
    assert finding.measurements["request_count"] == 2
    assert finding.scope.session_id == "s1"


def test_identical_after_failure_not_flagged_by_A() -> None:
    # The second success is attempt 2 of a retry: B's territory, never A's.
    first = event(id="e1", started_at=BASE)
    failed = event(
        id="e2",
        started_at=BASE + timedelta(seconds=60),
        status="error",
        error_category="upstream_error",
        est_cost=None,
    )
    retried = event(
        id="e3",
        started_at=BASE + timedelta(seconds=120),
        attempt=2,
        retry_group_id="g1",
        retry_source="explicit",
    )

    assert DETECTOR.detect(ctx([first, failed, retried])) == []


def test_different_task_ids_not_flagged() -> None:
    first = event(id="e1", started_at=BASE, task_id="t1")
    second = event(id="e2", started_at=BASE + timedelta(seconds=60), task_id="t2")

    assert DETECTOR.detect(ctx([first, second])) == []


def test_outside_window_not_flagged() -> None:
    first = event(id="e1", started_at=BASE)
    second = event(id="e2", started_at=BASE + timedelta(seconds=301))

    assert DETECTOR.detect(ctx([first, second])) == []


def test_intentional_repeat_not_flagged() -> None:
    first = event(id="e1", started_at=BASE)
    second = event(id="e2", started_at=BASE + timedelta(seconds=60), intentional_repeat=True)

    assert DETECTOR.detect(ctx([first, second])) == []


def test_chain_extends_cluster() -> None:
    # Each hop is within the window, so all three form one cluster.
    events = [
        event(id=f"c{i}", started_at=BASE + timedelta(seconds=200 * i)) for i in range(3)
    ]

    findings = DETECTOR.detect(ctx(events))

    assert len(findings) == 1
    assert [ref.id for ref in findings[0].evidence] == ["c0", "c1", "c2"]
    assert findings[0].estimated_impact == Decimal("0.20")
