"""Labeled trace dataset and detector precision evaluation (PRD §15.4)."""

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import tokenpilot.pricing.catalog as catalog_module
from tokenpilot.db.connection import connect, transaction
from tokenpilot.db.database import Database
from tokenpilot.db.migrate import migrate
from tokenpilot.detectors.base import RULE_IDS, SEVERITY_RANK
from tokenpilot.detectors.facts import AnalysisScope
from tokenpilot.detectors.runner import run_detectors
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.ledger.ingest import ingest_event
from tokenpilot.ledger.refs import resolve_project_ref
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.pricing.catalog import load_catalog
from tokenpilot.schemas.common import Page
from tokenpilot.schemas.insights import InsightFilters, InsightOut
from tokenpilot.schemas.usage import UsageEventIn
from tokenpilot.timeutil import parse_utc_z

CATALOG_PATH = Path(catalog_module.__file__).parent / "catalog.yaml"
FIXTURES_DIR = Path(__file__).resolve().parent.parent / "fixtures" / "labeled_traces"
EXPECTED_FIXTURE_NAMES = (
    "clear_retry_waste",
    "legit_repeats",
    "necessary_large_context",
    "expensive_success",
    "expensive_failure",
    "ambiguous_incomplete",
)
FIXTURE_PATHS = [FIXTURES_DIR / f"{name}.json" for name in EXPECTED_FIXTURE_NAMES]


@dataclass(frozen=True)
class EvaluatedInsight:
    """An insight resolved back to the fixture's external session/task identifiers."""

    insight: InsightOut
    external_session_id: str | None
    external_task_id: str | None


@dataclass(frozen=True)
class FixtureEvaluation:
    """Result of loading a labeled fixture, running all detectors, and matching."""

    fixture_name: str
    raw: dict[str, Any]
    insights: list[EvaluatedInsight]
    matched_indices: set[int]
    unmatched_expected: list[dict[str, Any]]


def _matches_expected(item: EvaluatedInsight, expected: dict[str, Any]) -> bool:
    if item.insight.rule_id != expected["rule_id"]:
        return False
    if item.external_session_id != expected.get("session"):
        return False
    if item.external_task_id != expected.get("task"):
        return False
    max_severity = expected.get("max_severity")
    if max_severity is not None:
        return SEVERITY_RANK[item.insight.severity] <= SEVERITY_RANK[max_severity]
    return True


def _evaluate_fixture(fixture_path: Path, db_path: Path) -> FixtureEvaluation:
    raw: dict[str, Any] = json.loads(fixture_path.read_text(encoding="utf-8"))
    events = raw["events"]
    assert 5 <= len(events) <= 15, f"{fixture_path.name}: expected 5-15 events, got {len(events)}"
    for ev in events:
        assert ev["provider"] == "fake", f"{fixture_path.name}: events must use provider 'fake'"

    setup = connect(db_path)
    migrate(setup)
    with transaction(setup):
        load_catalog(setup, CATALOG_PATH)
    setup.close()

    db = Database(db_path)
    read_conn = connect(db_path)
    try:
        session_sources = {
            s["external_session_id"]: s["source"] for s in raw.get("sessions", [])
        }
        with db.write() as conn:
            for raw_event in events:
                ext_sess = raw_event.get("external_session_id")
                source = session_sources.get(ext_sess, "api") if ext_sess else "api"
                res = ingest_event(conn, UsageEventIn.model_validate(raw_event), source)
                assert res.created, f"{fixture_path.name}: duplicate event in fixture"

            repo = LedgerRepository(conn)
            for s in raw.get("sessions", []):
                row = repo.find_session(s["source"], s["external_session_id"])
                assert row is not None, (
                    f"{fixture_path.name}: session {s['external_session_id']!r} not created"
                )
                updated = repo.set_session_outcome(str(row["id"]), s["outcome"], "manual")
                assert updated

            for t in raw.get("tasks", []):
                project_id = resolve_project_ref(conn, t["project_id"])
                cursor = conn.execute(
                    "UPDATE tasks SET outcome = ?, outcome_source = 'manual' "
                    "WHERE project_id = ? AND external_task_id = ?",
                    (t["outcome"], project_id, t["external_task_id"]),
                )
                assert cursor.rowcount == 1, (
                    f"{fixture_path.name}: task {t['external_task_id']!r} not found"
                )

        now = parse_utc_z(raw["now"])
        run_detectors(read_conn, db, AnalysisScope(), None, now)

        with db.read() as conn:
            stored = InsightRepository(conn).list(InsightFilters(), Page(limit=200)).items
            sess_rows = conn.execute(
                "SELECT id, external_session_id FROM sessions"
            ).fetchall()
            task_rows = conn.execute(
                "SELECT id, external_task_id FROM tasks"
            ).fetchall()

        sess_ext = {str(r["id"]): r["external_session_id"] for r in sess_rows}
        task_ext = {str(r["id"]): r["external_task_id"] for r in task_rows}
        evaluated = [
            EvaluatedInsight(
                insight=ins,
                external_session_id=(
                    sess_ext.get(ins.session_id) if ins.session_id is not None else None
                ),
                external_task_id=(
                    task_ext.get(ins.task_id) if ins.task_id is not None else None
                ),
            )
            for ins in stored
        ]
    finally:
        read_conn.close()
        db.close()

    matched_indices: set[int] = set()
    unmatched_expected: list[dict[str, Any]] = []
    for exp in raw.get("expected", []):
        match_idx = next(
            (
                idx
                for idx, item in enumerate(evaluated)
                if idx not in matched_indices and _matches_expected(item, exp)
            ),
            None,
        )
        if match_idx is None:
            unmatched_expected.append(exp)
        else:
            matched_indices.add(match_idx)

    return FixtureEvaluation(
        fixture_name=fixture_path.stem,
        raw=raw,
        insights=evaluated,
        matched_indices=matched_indices,
        unmatched_expected=unmatched_expected,
    )


@pytest.mark.parametrize("fixture_path", FIXTURE_PATHS, ids=lambda p: p.stem)
def test_detector_precision(fixture_path: Path, tmp_path: Path) -> None:
    """Every expected entry matches an insight and no must_not_fire rule produces anything."""
    evaluation = _evaluate_fixture(fixture_path, tmp_path / f"{fixture_path.stem}.sqlite3")

    must_not_fire = set(evaluation.raw.get("must_not_fire", []))
    forbidden = [
        item.insight.rule_id
        for item in evaluation.insights
        if item.insight.rule_id in must_not_fire
    ]
    assert not forbidden, (
        f"{evaluation.fixture_name}: must_not_fire rule(s) fired: {forbidden}"
    )
    produced_summary = [
        (i.insight.rule_id, i.external_session_id, i.external_task_id, i.insight.severity)
        for i in evaluation.insights
    ]
    assert not evaluation.unmatched_expected, (
        f"{evaluation.fixture_name}: unmatched expected entries: "
        f"{evaluation.unmatched_expected}; produced={produced_summary}"
    )


def test_precision_report(tmp_path: Path) -> None:
    """Aggregate precision per rule across all labeled traces and assert 1.0 when findings exist."""
    matched_by_rule: dict[str, int] = {rule_id: 0 for rule_id in RULE_IDS}
    total_by_rule: dict[str, int] = {rule_id: 0 for rule_id in RULE_IDS}

    for fixture_path in FIXTURE_PATHS:
        evaluation = _evaluate_fixture(fixture_path, tmp_path / f"{fixture_path.stem}.sqlite3")
        for idx, item in enumerate(evaluation.insights):
            rule_id = item.insight.rule_id
            total_by_rule[rule_id] += 1
            if idx in evaluation.matched_indices:
                matched_by_rule[rule_id] += 1

    lines = [
        "",
        "| Rule | Matched | Total | Precision |",
        "| --- | ---: | ---: | ---: |",
    ]
    precisions: dict[str, float] = {}
    for rule_id in RULE_IDS:
        matched = matched_by_rule[rule_id]
        total = total_by_rule[rule_id]
        if total == 0:
            precision_str = "n/a"
        else:
            precision = matched / total
            precisions[rule_id] = precision
            precision_str = f"{precision:.2f}"
        lines.append(f"| `{rule_id}` | {matched} | {total} | {precision_str} |")

    print("\n".join(lines))

    assert precisions, "Expected at least one rule to produce findings across fixtures"
    for rule_id, precision in precisions.items():
        assert precision == 1.0, (
            f"Rule {rule_id!r} precision {precision:.2f} != 1.0 "
            f"({matched_by_rule[rule_id]}/{total_by_rule[rule_id]})"
        )
