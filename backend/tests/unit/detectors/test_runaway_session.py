"""Detector F: sessions whose size, cost, span or retries ran past every bound."""

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from tests.unit.detectors.conftest import BASE, ctx, event, session
from tokenpilot.detectors.facts import EventFact
from tokenpilot.detectors.runaway_session import RunawaySessionDetector

DETECTOR = RunawaySessionDetector()
NOW = BASE + timedelta(hours=2)


def _burst(
    n: int, *, end: datetime, cost: Decimal = Decimal("0.01"), **overrides: Any
) -> list[EventFact]:
    """`n` requests ending at `end`, one minute apart, in time order."""
    return [
        event(
            id=f"r{i}",
            started_at=end - timedelta(minutes=n - 1 - i),
            est_cost=cost,
            **overrides,
        )
        for i in range(n)
    ]


def test_request_threshold_exceeded_without_success_flagged() -> None:
    end = NOW - timedelta(hours=2)
    findings = DETECTOR.detect(
        ctx(
            _burst(41, end=end),
            sessions=(
                session(
                    outcome="unknown",
                    started_at=end - timedelta(hours=1),
                    ended_at=end,
                ),
            ),
            now=NOW,
        )
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "runaway_session"
    assert finding.anchor == "s1"
    assert finding.dedupe_key == "runaway_session.v1:s1"
    assert finding.severity == "medium"
    assert finding.confidence == 0.80
    assert finding.measurements["tripped"] == ["requests"]
    assert finding.measurements["request_count"] == 41
    assert finding.measurements["possibly_running"] is False
    assert finding.measurements["outcome"] == "unknown"
    assert finding.measurements["cost_comparable"] is True
    assert finding.estimated_impact == Decimal("0.41")
    assert finding.impact_currency == "USD"
    assert finding.evidence[0].kind == "session"
    assert finding.evidence[0].id == "s1"
    assert len(finding.evidence) == 42


def test_exactly_at_threshold_not_flagged() -> None:
    end = NOW - timedelta(hours=2)
    findings = DETECTOR.detect(
        ctx(
            _burst(40, end=end),
            sessions=(
                session(
                    outcome="unknown",
                    started_at=end - timedelta(minutes=30),
                    ended_at=end,
                ),
            ),
            now=NOW,
        )
    )

    assert findings == []


def test_recent_activity_marked_possibly_running() -> None:
    end = NOW - timedelta(minutes=5)
    findings = DETECTOR.detect(
        ctx(
            _burst(41, end=end),
            sessions=(
                session(
                    outcome="failure",
                    started_at=end - timedelta(hours=1),
                    ended_at=end,
                ),
            ),
            now=NOW,
        )
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "informational"
    assert finding.title.startswith("Possibly still running")
    assert finding.severity != "high"
    assert finding.measurements["possibly_running"] is True
    assert finding.confidence == 0.40


def test_successful_session_not_flagged() -> None:
    end = NOW - timedelta(hours=2)
    findings = DETECTOR.detect(
        ctx(
            _burst(100, end=end, cost=Decimal("0.10")),
            sessions=(
                session(
                    outcome="success",
                    started_at=end - timedelta(hours=3),
                    ended_at=end,
                ),
            ),
            now=NOW,
        )
    )

    assert findings == []


def test_failed_runaway_is_high() -> None:
    end = NOW - timedelta(hours=2)
    findings = DETECTOR.detect(
        ctx(
            _burst(41, end=end),
            sessions=(
                session(
                    outcome="failure",
                    started_at=end - timedelta(minutes=30),
                    ended_at=end,
                ),
            ),
            now=NOW,
        )
    )

    assert len(findings) == 1
    assert findings[0].severity == "high"
    assert findings[0].measurements["possibly_running"] is False
    assert findings[0].confidence == 0.80


def test_cost_criterion_not_evaluable_for_mixed_currency() -> None:
    end = NOW - timedelta(hours=2)
    findings = DETECTOR.detect(
        ctx(
            [
                *_burst(40, end=end - timedelta(minutes=1)),
                event(
                    id="eur",
                    started_at=end,
                    est_cost=Decimal("100.00"),
                    currency="EUR",
                ),
            ],
            sessions=(
                session(
                    outcome="unknown",
                    started_at=end - timedelta(minutes=30),
                    ended_at=end,
                ),
            ),
            now=NOW,
        )
    )

    assert len(findings) == 1
    finding = findings[0]
    assert finding.measurements["tripped"] == ["requests"]
    assert finding.measurements["cost_comparable"] is False
    assert finding.measurements["total_cost"] is None
    assert finding.estimated_impact is None
    assert finding.impact_currency is None
