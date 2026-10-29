"""Insight, analysis-job and threshold shapes returned over HTTP.

`InsightOut` is the wire form of a stored insight. Money stays a Decimal inside
the process and becomes a JSON number here, always next to `impact_currency`.
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from tokenpilot.detectors.base import EvidenceKind, Severity
from tokenpilot.detectors.thresholds import Thresholds
from tokenpilot.schemas.common import Money
from tokenpilot.schemas.sessions import SessionSummary
from tokenpilot.schemas.usage import UsageEvent

InsightStatus = Literal["new", "reviewed", "dismissed", "tested"]
JobStatus = Literal["queued", "running", "succeeded", "failed"]
InvestigationMode = Literal["metadata_only", "with_excerpts"]
InvestigationStatus = Literal["completed", "insufficient_evidence", "failed"]
FeedbackVerdict = Literal["useful", "not_useful", "not_applicable"]
# Keep in sync with `detectors.base.RULE_IDS` (mypy rejects `Literal[*RULE_IDS]`).
RuleId = Literal[
    "repeated_request",
    "retry_amplification",
    "repeated_context",
    "unsuccessful_task",
    "context_ratio",
    "runaway_session",
    "model_inefficiency",
]


class StatusNotSettableError(ValueError):
    """PATCH asked for a status only another phase may write. `code` is the API error code."""

    code = "status_not_settable"
    details: dict[str, str] | None = None

    def __init__(self, status: str) -> None:
        super().__init__(f"status {status!r} cannot be set via PATCH")
        self.details = {"status": status}


class EvidenceRefOut(BaseModel):
    """The wire form of `EvidenceRef`: what an insight points at, and why."""

    kind: EvidenceKind
    id: str
    measurement: dict[str, Any]


class InsightOut(BaseModel):
    """One stored insight. `rule_guidance` is filled by the API, not storage."""

    id: str
    rule_id: str
    rule_version: int
    detector_type: str
    severity: Severity
    status: InsightStatus
    title: str
    summary: str
    confidence: float | None = None
    estimated_impact: Money | None
    impact_currency: str | None
    impact_label: Literal["potential"] = "potential"
    project_id: str | None
    session_id: str | None
    task_id: str | None
    evidence: list[EvidenceRefOut]
    evidence_truncated: int
    measurements: dict[str, Any]
    rule_guidance: str | None = None
    root_cause_hypothesis: str | None
    recommendation: dict[str, Any] | None
    investigator_model: str | None
    created_at: str
    updated_at: str | None = None
    last_detected_at: str | None = None


@dataclass(frozen=True)
class InsightFilters:
    """Every filter is optional; an omitted one is not applied."""

    status: InsightStatus | None = None
    severity: Severity | None = None
    rule_id: str | None = None
    project_id: str | None = None
    session_id: str | None = None


class JobOut(BaseModel):
    """One analysis job. `result` is NULL until the job succeeds."""

    id: str
    kind: str
    status: JobStatus
    params: dict[str, Any]
    result: dict[str, Any] | None
    error: str | None
    created_at: str
    started_at: str | None
    finished_at: str | None


class InvestigationOut(BaseModel):
    """One finished investigation run persisted for an insight."""

    id: str
    insight_id: str
    model: str | None
    prompt_version: str | None
    mode: InvestigationMode
    status: InvestigationStatus
    result: dict[str, Any] | None
    validation_errors: list[str] | None
    request_disclosure: dict[str, Any] | None
    created_at: str


class FeedbackOut(BaseModel):
    """One recommendation-feedback row from a user."""

    id: str
    insight_id: str
    verdict: FeedbackVerdict
    implemented: bool | None
    note: str | None
    created_at: str


class ThresholdsResponse(BaseModel):
    """A saved thresholds object; stored detectors do not re-run on their own."""

    thresholds: Thresholds
    reanalysis_required: bool


class AnalyzeRequest(BaseModel):
    """Scope and optional rule filter for one analysis job."""

    model_config = ConfigDict(extra="forbid")

    project_id: str | None = None
    session_id: str | None = None
    rule_ids: list[RuleId] | None = None


class AnalyzeAccepted(BaseModel):
    """202 body: the job id to poll."""

    job_id: str


class TaskRef(BaseModel):
    """A resolved task row pointed at by evidence."""

    id: str
    project_id: str
    external_task_id: str | None
    outcome: str


class ResolvedEvidence(BaseModel):
    """One evidence ref plus the ledger row it names, when that row still exists."""

    ref: EvidenceRefOut
    resolved: bool
    event: UsageEvent | None = None
    session: SessionSummary | None = None
    task: TaskRef | None = None


class InsightDetail(BaseModel):
    """An insight with every evidence ref resolved (or marked unresolved)."""

    insight: InsightOut
    evidence_rows: list[ResolvedEvidence]


class InsightStatusUpdate(BaseModel):
    """PATCH body. `tested` is accepted by the schema then rejected with status_not_settable."""

    model_config = ConfigDict(extra="forbid")

    status: InsightStatus
