"""Usage summary shapes. Every money field sits next to a `currency` (D11: null when mixed)."""

from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel

from tokenpilot.schemas.common import Money
from tokenpilot.schemas.sessions import SessionOutcome

SummaryCostBasis = Literal["estimated", "reported", "mixed", "simulated", "unavailable"]
OutcomeClass = Literal["passed", "failed", "unknown"]
SummaryBucket = Literal["day", "hour"]


@dataclass(frozen=True)
class SummaryFilters:
    """`started_from` is inclusive, `started_to` exclusive; both are `Z` strings."""

    started_from: str | None = None
    started_to: str | None = None
    project_id: str | None = None
    provider: str | None = None
    model_id: str | None = None
    outcome: OutcomeClass | None = None
    bucket: SummaryBucket = "day"


class LatencyStats(BaseModel):
    avg: float
    p50: int
    p95: int


class ProjectCost(BaseModel):
    project_id: str | None
    name: str
    estimated_cost: Money | None
    currency: str | None
    request_count: int


class ModelCost(BaseModel):
    """Token sums cover only events that reported them; `events_with_unknown_tokens` says how
    many did not."""

    provider: str
    model_id: str
    estimated_cost: Money | None
    currency: str | None
    request_count: int
    input_tokens: int | None
    output_tokens: int | None
    events_with_unknown_tokens: int


class TimeseriesPoint(BaseModel):
    bucket_start: str
    estimated_cost: Money | None
    currency: str | None
    request_count: int


class SessionCost(BaseModel):
    session_id: str
    project_id: str | None
    estimated_cost: Money | None
    currency: str | None
    request_count: int
    outcome: SessionOutcome


class CostByOutcome(BaseModel):
    """Amounts in the summary's top-level `currency`."""

    passed: Money | None
    failed: Money | None
    unknown: Money | None


class Coverage(BaseModel):
    attributed_pct: float | None
    priced_pct: float | None
    provider_usage_pct: float | None
    mixed_currency: bool | None


class UsageSummary(BaseModel):
    total_estimated_cost: Money | None
    total_reported_cost: Money | None
    currency: str | None
    cost_basis: SummaryCostBasis
    events_with_unknown_cost: int
    input_tokens: int | None
    output_tokens: int | None
    events_with_unknown_tokens: int
    request_count: int
    failed_count: int
    retry_count: int
    retry_cost: Money | None
    latency_ms: LatencyStats | None
    by_project: list[ProjectCost]
    by_model: list[ModelCost]
    timeseries: list[TimeseriesPoint]
    top_sessions: list[SessionCost]
    cost_by_outcome: CostByOutcome
    cost_concentration_top10_pct: float | None
    coverage: Coverage
