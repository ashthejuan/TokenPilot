"""Insight, analysis-job and threshold shapes returned over HTTP.

`InsightOut` is the wire form of a stored insight. Money stays a Decimal inside
the process and becomes a JSON number here, always next to `impact_currency`.
"""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import BaseModel

from tokenpilot.detectors.base import EvidenceKind, Severity
from tokenpilot.detectors.thresholds import Thresholds
from tokenpilot.schemas.common import Money

InsightStatus = Literal["new", "reviewed", "dismissed", "tested"]
JobStatus = Literal["queued", "running", "succeeded", "failed"]


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


class ThresholdsResponse(BaseModel):
    """A saved thresholds object; stored detectors do not re-run on their own."""

    thresholds: Thresholds
    reanalysis_required: bool
