"""Session shapes. Cost fields stay null until the cost engine fills them (Task 1.5)."""

from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

from tokenpilot.schemas.usage import UsageEvent

SessionOutcome = Literal["success", "failure", "abandoned", "unknown"]


class SessionSummary(BaseModel):
    id: str
    project_id: str | None
    external_session_id: str | None
    source: str
    started_at: str
    ended_at: str | None
    outcome: SessionOutcome
    outcome_source: str | None
    request_count: int
    total_estimated_cost: Decimal | None = None
    currency: str | None = None


class ModelBreakdown(BaseModel):
    model_id: str
    request_count: int
    input_tokens: int | None
    output_tokens: int | None
    estimated_cost: Decimal | None = None


class SessionDetail(BaseModel):
    session: SessionSummary
    events: list[UsageEvent]
    by_model: list[ModelBreakdown]
    outcome: SessionOutcome
    outcome_source: str | None


class SessionUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outcome: SessionOutcome
