"""Evidence-ID and number validation for InvestigationOutput (Task 3.2 / RF3)."""

from __future__ import annotations

from tokenpilot.investigator.evidence import EvidenceBundle
from tokenpilot.investigator.schema import (
    InvestigationOutput,
    ObservedFact,
    ProposedBenchmark,
    Recommendation,
)
from tokenpilot.investigator.validate import validate_output


def _bundle(
    *,
    allowed_ids: list[str] | None = None,
    allowed_numbers: list[float | int] | None = None,
    aggregates: dict | None = None,
) -> EvidenceBundle:
    return EvidenceBundle(
        investigation_id="inv1",
        insight={},
        events=[],
        aggregates=aggregates or {},
        outcomes=[],
        pricing=[],
        excerpts=[],
        coverage={},
        allowed_ids=allowed_ids or [],
        allowed_numbers=allowed_numbers or [],
    )


def _output(
    *,
    summary: str = "ok",
    evidence_ids: list[str] | None = None,
    statement: str = "fact",
) -> InvestigationOutput:
    return InvestigationOutput(
        title="t",
        summary=summary,
        observed_facts=[
            ObservedFact(statement=statement, evidence_ids=evidence_ids or ["e1"]),
        ],
        root_cause_hypothesis="h",
        impact_assessment="i",
        recommendation=Recommendation(
            action="cap retries",
            variable_to_change="retry_policy",
            expected_direction="lower_cost",
            validation_procedure="A/B",
            proposed_benchmark=ProposedBenchmark(
                baseline_change="keep",
                alternative_change="cap",
            ),
        ),
        confidence="medium",
        limitations=["coverage thin"],
        verdict="supported",
    )


def test_unknown_evidence_id_rejected() -> None:
    out = _output(evidence_ids=["e1", "bogus"])
    issues = validate_output(out, _bundle(allowed_ids=["e1"], allowed_numbers=[]))
    assert any(issue.code == "unknown_evidence_id" for issue in issues)
    assert any("bogus" in issue.message for issue in issues)


def test_unsupported_number_rejected() -> None:
    out = _output(summary="costs $4.20")
    issues = validate_output(out, _bundle(allowed_ids=["e1"], allowed_numbers=[0.22]))
    assert any(issue.code == "unsupported_number" for issue in issues)
    assert any("4.20" in issue.message or "4.2" in issue.message for issue in issues)


def test_supported_numbers_pass() -> None:
    out = _output(summary="$0.22 of retry spend")
    issues = validate_output(out, _bundle(allowed_ids=["e1"], allowed_numbers=[0.22]))
    assert issues == []


def test_ordinals_and_years_exempt() -> None:
    out = _output(summary="3 retries in 2026")
    issues = validate_output(out, _bundle(allowed_ids=["e1"], allowed_numbers=[]))
    assert issues == []
