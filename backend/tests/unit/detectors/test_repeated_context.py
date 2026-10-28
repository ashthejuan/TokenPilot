"""Detector C: the same context block hashed across requests in one session."""

from datetime import timedelta
from typing import Any

from tests.unit.detectors.conftest import BASE, ctx, event
from tokenpilot.detectors.facts import ContextBlockFact, EventFact
from tokenpilot.detectors.repeated_context import RepeatedContextDetector

DETECTOR = RepeatedContextDetector()
BLOCK = ContextBlockFact(hash="abc123", chars=8000, approx_tokens=2000)


def _repeat(n: int, **overrides: Any) -> list[EventFact]:
    """`n` requests in one session carrying the same block, in time order."""
    return [
        event(
            id=f"c{i}",
            started_at=BASE + timedelta(seconds=i),
            context_blocks=(BLOCK,),
            **overrides,
        )
        for i in range(n)
    ]


def test_block_repeated_three_times_flagged_hash_only() -> None:
    findings = DETECTOR.detect(ctx(_repeat(3)))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "repeated_context"
    assert finding.rule_version == 1
    assert finding.anchor == "s1:abc123"
    assert finding.dedupe_key == "repeated_context.v1:s1:abc123"
    assert finding.severity == "low"
    assert finding.confidence == 0.50
    assert finding.measurements["repeated_chars"] == 16000
    assert finding.measurements["approx_repeated_tokens"] == 4000
    assert finding.measurements["observation"] == "hash_only"
    assert finding.measurements["occurrence_count"] == 3
    assert "not necessarily avoidable" in finding.summary
    assert finding.estimated_impact is None
    assert finding.impact_currency is None
    assert finding.scope.session_id == "s1"
    assert len(finding.evidence) == 3


def test_two_occurrences_not_flagged() -> None:
    assert DETECTOR.detect(ctx(_repeat(2))) == []


def test_repeated_context_never_high_severity() -> None:
    huge = ContextBlockFact(hash="huge", chars=400000, approx_tokens=100000)
    events = [
        event(
            id=f"h{i}",
            started_at=BASE + timedelta(seconds=i),
            context_blocks=(huge,),
        )
        for i in range(200)
    ]

    findings = DETECTOR.detect(ctx(events))

    assert len(findings) == 1
    assert findings[0].severity == "medium"
    assert findings[0].measurements["approx_repeated_tokens"] == 100000 * 199


def test_blocks_in_different_sessions_not_combined() -> None:
    events = [
        *_repeat(2, session_id="s1"),
        *[
            event(
                id=f"d{i}",
                session_id="s2",
                started_at=BASE + timedelta(seconds=i),
                context_blocks=(BLOCK,),
            )
            for i in range(2)
        ],
    ]

    assert DETECTOR.detect(ctx(events)) == []
