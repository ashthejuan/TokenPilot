"""Detector G stub: no comparable runs, no finding."""

from decimal import Decimal

from tests.unit.detectors.conftest import ctx, event, task
from tokenpilot.detectors.base import RULE_IDS
from tokenpilot.detectors.model_inefficiency import ModelInefficiencyDetector
from tokenpilot.detectors.runner import REGISTRY

DETECTOR = ModelInefficiencyDetector()


def test_model_inefficiency_needs_comparable_runs() -> None:
    detection_ctx = ctx(
        [
            event(
                id="cheap",
                model_id="fake-small",
                task_id="t1",
                est_cost=Decimal("0.10"),
            ),
            event(
                id="pricey",
                model_id="fake-large",
                task_id="t2",
                est_cost=Decimal("1.00"),
            ),
        ],
        tasks=(task(id="t1"), task(id="t2", session_id="s2")),
    )
    detection_ctx.conn.execute(
        "CREATE TABLE benchmark_comparisons (id TEXT PRIMARY KEY)"
    )

    assert DETECTOR.detect(detection_ctx) == []


def test_registry_has_all_seven_rules() -> None:
    assert set(REGISTRY) == set(RULE_IDS)
    assert len(REGISTRY) == 7
