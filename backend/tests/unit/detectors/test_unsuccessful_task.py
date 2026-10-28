"""Detector D: money spent on tasks and sessions that never succeeded."""

from decimal import Decimal

from tests.unit.detectors.conftest import ctx, event, session, task
from tokenpilot.detectors.unsuccessful_task import UnsuccessfulTaskDetector

DETECTOR = UnsuccessfulTaskDetector()


def test_failed_expensive_task_flagged() -> None:
    findings = DETECTOR.detect(
        ctx(
            [
                event(id="e1", task_id="t1", est_cost=Decimal("0.30")),
                event(id="e2", task_id="t1", est_cost=Decimal("0.30")),
            ],
            tasks=(task(id="t1", outcome="failed"),),
        )
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "unsuccessful_task"
    assert finding.anchor == "task:t1"
    assert finding.dedupe_key == "unsuccessful_task.v1:task:t1"
    assert finding.estimated_impact == Decimal("0.60")
    assert finding.impact_currency == "USD"
    assert finding.measurements["total_cost"] == 0.60
    assert finding.measurements["unknown_cost_events"] == 0
    assert finding.measurements["request_count"] == 2
    assert finding.measurements["outcome"] == "failed"
    assert finding.measurements["cost_comparable"] is True
    assert finding.severity == "medium"
    assert finding.confidence == 0.70
    assert [ref.kind for ref in finding.evidence] == ["usage_event", "usage_event", "task"]
    assert finding.evidence[-1].id == "t1"


def test_unknown_outcome_never_flagged() -> None:
    findings = DETECTOR.detect(
        ctx(
            [event(id="e1", task_id="t1", est_cost=Decimal("5.00"))],
            sessions=(session(outcome="unknown"),),
            tasks=(task(id="t1", outcome="unknown"),),
        )
    )

    assert findings == []


def test_expensive_success_not_flagged() -> None:
    findings = DETECTOR.detect(
        ctx(
            [event(id="e1", task_id="t1", est_cost=Decimal("5.00"))],
            sessions=(session(outcome="success"),),
            tasks=(task(id="t1", outcome="passed"),),
        )
    )

    assert findings == []


def test_abandoned_session_flagged() -> None:
    findings = DETECTOR.detect(
        ctx(
            [
                event(id="e1", est_cost=Decimal("0.30")),
                event(id="e2", est_cost=Decimal("0.30")),
            ],
            sessions=(session(outcome="abandoned", outcome_source="manual"),),
        )
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.anchor == "session:s1"
    assert finding.dedupe_key == "unsuccessful_task.v1:session:s1"
    assert finding.estimated_impact == Decimal("0.60")
    assert finding.measurements["outcome"] == "abandoned"
    assert finding.measurements["outcome_source"] == "manual"
    assert finding.confidence == 0.90
    assert [ref.kind for ref in finding.evidence] == ["usage_event", "usage_event", "session"]
    assert finding.evidence[-1].id == "s1"


def test_task_and_session_failure_not_double_counted() -> None:
    findings = DETECTOR.detect(
        ctx(
            [
                event(id="t1e1", task_id="t1", est_cost=Decimal("0.30")),
                event(id="t1e2", task_id="t1", est_cost=Decimal("0.30")),
                event(id="free1", est_cost=Decimal("0.30")),
                event(id="free2", est_cost=Decimal("0.30")),
            ],
            sessions=(session(outcome="failure"),),
            tasks=(task(id="t1", outcome="failed"),),
        )
    )

    assert len(findings) == 2
    by_anchor = {finding.anchor: finding for finding in findings}
    assert by_anchor["task:t1"].estimated_impact == Decimal("0.60")
    assert by_anchor["session:s1"].estimated_impact == Decimal("0.60")
    assert by_anchor["session:s1"].measurements["request_count"] == 2


def test_unknown_cost_never_counts_toward_threshold() -> None:
    findings = DETECTOR.detect(
        ctx(
            [
                event(id="e1", task_id="t1", est_cost=Decimal("0.40")),
                event(id="e2", task_id="t1", est_cost=None),
            ],
            tasks=(task(id="t1", outcome="failed"),),
        )
    )

    assert findings == []


def test_non_usd_cost_not_evaluable() -> None:
    findings = DETECTOR.detect(
        ctx(
            [event(id="e1", task_id="t1", est_cost=Decimal("9.00"), currency="EUR")],
            tasks=(task(id="t1", outcome="failed"),),
        )
    )

    assert findings == []
