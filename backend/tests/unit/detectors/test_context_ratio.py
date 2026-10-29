"""Detector E: input/output token ratios, diagnostic only."""

from datetime import timedelta
from typing import Any

from tests.unit.detectors.conftest import BASE, ctx, event
from tokenpilot.detectors.context_ratio import ContextRatioDetector
from tokenpilot.detectors.facts import EventFact

DETECTOR = ContextRatioDetector()


def _flagged(n: int, **overrides: Any) -> list[EventFact]:
    """`n` successful requests with a 300:1 ratio, in time order."""
    values: dict[str, Any] = {
        "input_tokens": 30000,
        "output_tokens": 100,
    }
    values.update(overrides)
    return [
        event(id=f"e{i}", started_at=BASE + timedelta(seconds=i), **values)
        for i in range(n)
    ]


def test_ratio_flag_is_diagnostic_only() -> None:
    findings = DETECTOR.detect(ctx(_flagged(1)))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.rule_id == "context_ratio"
    assert finding.rule_version == 1
    assert finding.anchor == "session:s1"
    assert finding.dedupe_key == "context_ratio.v1:session:s1"
    assert finding.severity == "informational"
    assert finding.confidence == 0.30
    assert finding.measurements["diagnostic_only"] is True
    assert finding.measurements["flagged_event_count"] == 1
    assert finding.measurements["ratio"] == 300.0
    assert finding.scope.session_id == "s1"


def test_ratio_below_min_input_ignored() -> None:
    events = _flagged(1, input_tokens=10000, output_tokens=10)

    assert DETECTOR.detect(ctx(events)) == []


def test_ratio_skips_null_tokens() -> None:
    events = [
        *_flagged(1, input_tokens=None),
        *_flagged(1, output_tokens=None),
    ]

    assert DETECTOR.detect(ctx(events)) == []


def test_zero_output_flagged_with_null_ratio() -> None:
    findings = DETECTOR.detect(ctx(_flagged(1, output_tokens=0)))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.measurements["ratio"] is None
    assert finding.measurements["zero_output"] is True
    assert finding.measurements["diagnostic_only"] is True


def test_one_insight_per_session() -> None:
    findings = DETECTOR.detect(ctx(_flagged(6)))

    assert len(findings) == 1
    finding = findings[0]
    assert finding.severity == "low"
    assert finding.measurements["flagged_event_count"] == 6
    assert len(finding.evidence) == 6


def test_failed_events_ignored() -> None:
    events = _flagged(6, status="error")

    assert DETECTOR.detect(ctx(events)) == []
