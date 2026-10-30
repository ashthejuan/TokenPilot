"""Project and savings report shapes (Task 5.2, FR-11 / FR-12)."""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tokenpilot.savings.classify import ComparisonStatus
from tokenpilot.schemas.common import Money
from tokenpilot.schemas.summary import CostByOutcome, Coverage, SessionCost, SummaryCostBasis

ReportFormat = Literal["json", "markdown"]

REALIZED_LIMITATION = "Realized savings are not measured in this version"


class ReportPeriod(BaseModel):
    """Inclusive `from`, exclusive `to`; both are `Z` strings when set."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    from_: str | None = Field(
        default=None, validation_alias="from", serialization_alias="from"
    )
    to: str | None = None


class WasteByRule(BaseModel):
    """Non-dismissed insight impact rolled up by detector rule."""

    rule_id: str
    estimated_impact: Money | None
    count: int


class ReportRecommendation(BaseModel):
    """One investigated insight with a stored recommendation."""

    insight_id: str
    rule_id: str
    title: str
    recommendation: dict[str, Any]
    estimated_impact: Money | None
    impact_currency: str | None


class ReportBenchmark(BaseModel):
    """One comparison row for the project report's benchmarks list."""

    name: str
    comparison_status: ComparisonStatus
    cost_delta: Money | None
    cost_delta_pct: Money | None
    methodology: dict[str, Any]


class UnattributedUsage(BaseModel):
    """Events in the window that have no project attribution."""

    events: int
    estimated_cost: Money | None


class SavingsBreakdown(BaseModel):
    """FR-11 ladder amounts. Kinds are never summed; `realized` is always null in MVP."""

    potential: Money | None
    benchmark: Money | None
    verified: Money | None
    realized: Money | None = None


class ProjectReport(BaseModel):
    """Full project report for JSON responses and the Markdown renderer."""

    project_id: str
    project_name: str
    period: ReportPeriod
    cost_basis: SummaryCostBasis
    currency: str | None
    coverage: Coverage
    spend_total: Money | None
    unknown_cost_events: int
    top_sessions: list[SessionCost]
    cost_by_outcome: CostByOutcome
    waste_by_rule: list[WasteByRule]
    top_recommendations: list[ReportRecommendation]
    benchmarks: list[ReportBenchmark]
    savings: SavingsBreakdown
    limitations: list[str]
    unattributed: UnattributedUsage


class SavingsReport(BaseModel):
    """`GET /reports/savings` body: the four kinds separately, never totalled."""

    potential: Money | None
    benchmark: Money | None
    verified: Money | None
    realized: Money | None = None
