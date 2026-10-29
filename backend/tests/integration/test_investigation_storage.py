"""Investigation storage, insight apply, feedback, and investigate job kind (Task 3.0)."""

import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest

from tests.integration.test_insights_storage import NOW, PROJECT_ID, make_finding
from tokenpilot.db.connection import connect, transaction
from tokenpilot.db.migrate import migrate
from tokenpilot.insights.jobs import JobRepository
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.investigator.repository import FeedbackRepository, InvestigationRepository
from tokenpilot.schemas.common import Page
from tokenpilot.schemas.insights import InsightFilters


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    """A migrated database with one project and a session for insight scope."""
    connection = connect(tmp_path / "investigation.sqlite3")
    migrate(connection)
    with transaction(connection):
        connection.execute(
            "INSERT INTO projects (id, name, created_at, updated_at) VALUES (?, 'demo', ?, ?)",
            (PROJECT_ID, NOW, NOW),
        )
        connection.execute(
            "INSERT INTO sessions (id, project_id, source, started_at) VALUES (?, ?, 'cli', ?)",
            ("s1", PROJECT_ID, NOW),
        )
    yield connection
    connection.close()


def _insight_id(conn: sqlite3.Connection) -> str:
    insights = InsightRepository(conn)
    insights.upsert(make_finding(), NOW)
    return insights.list(InsightFilters(), Page()).items[0].id


def test_save_and_list_investigations(conn: sqlite3.Connection) -> None:
    insight_id = _insight_id(conn)
    result = {
        "verdict": "supported",
        "root_cause_hypothesis": "Retries amplified cost",
        "recommendation": {"action": "cap retries"},
    }
    repo = InvestigationRepository(conn)
    saved = repo.save(
        id="inv1",
        insight_id=insight_id,
        model="meta-llama/llama-4-scout",
        prompt_version="investigate_v1",
        mode="metadata_only",
        request_disclosure={"contains_content": False},
        status="completed",
        result=result,
        validation_errors=None,
        created_at=NOW,
    )
    assert saved.status == "completed"
    assert saved.result == result

    listed = repo.list_for_insight(insight_id)
    assert len(listed) == 1
    assert listed[0].id == "inv1"
    assert listed[0].result == result
    assert listed[0].mode == "metadata_only"
    assert listed[0].request_disclosure == {"contains_content": False}


def test_apply_investigation_writes_insight_fields(conn: sqlite3.Connection) -> None:
    insights = InsightRepository(conn)
    insight_id = _insight_id(conn)

    recommendation = {
        "action": "Reduce retry count",
        "variable_to_change": "max_retries",
        "expected_direction": "decrease",
    }
    applied = insights.apply_investigation(
        insight_id,
        root_cause_hypothesis="Identical requests were retried unnecessarily",
        recommendation=recommendation,
        investigator_model="meta-llama/llama-4-scout",
        now="2026-10-28T11:00:00.000Z",
    )
    assert applied is not None
    got = insights.get(insight_id)
    assert got is not None
    assert got.root_cause_hypothesis == "Identical requests were retried unnecessarily"
    assert got.recommendation == recommendation
    assert got.investigator_model == "meta-llama/llama-4-scout"
    assert got.updated_at == "2026-10-28T11:00:00.000Z"

    assert (
        insights.upsert(make_finding(title="Repeated identical request (refreshed)"), NOW)
        == "updated"
    )
    after = insights.get(insight_id)
    assert after is not None
    assert after.root_cause_hypothesis == "Identical requests were retried unnecessarily"
    assert after.recommendation == recommendation
    assert after.investigator_model == "meta-llama/llama-4-scout"
    assert after.title == "Repeated identical request (refreshed)"


def test_feedback_insert(conn: sqlite3.Connection) -> None:
    insight_id = _insight_id(conn)

    feedback = FeedbackRepository(conn).add(
        insight_id=insight_id,
        verdict="useful",
        implemented=True,
        note="Helped us cut retries",
    )
    assert feedback.verdict == "useful"
    assert feedback.implemented is True
    assert feedback.note == "Helped us cut retries"
    assert feedback.insight_id == insight_id
    assert feedback.id
    assert feedback.created_at

    row = conn.execute(
        "SELECT verdict, implemented, note FROM recommendation_feedback WHERE id = ?",
        (feedback.id,),
    ).fetchone()
    assert row["verdict"] == "useful"
    assert row["implemented"] == 1
    assert row["note"] == "Helped us cut retries"


def test_job_kind_investigate_accepted(conn: sqlite3.Connection) -> None:
    job = JobRepository(conn).create("investigate", {"insight_id": "abc", "mode": "metadata_only"})
    assert job.kind == "investigate"
    stored = JobRepository(conn).get(job.id)
    assert stored is not None
    assert stored.kind == "investigate"
    assert stored.params == {"insight_id": "abc", "mode": "metadata_only"}
