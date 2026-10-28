"""Pricing catalogue and cost shapes for the settings API and event responses."""

from decimal import Decimal
from typing import Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from tokenpilot.schemas.common import Money

CostBasis = Literal["estimated", "reported", "billed", "unavailable"]


class CostSummary(BaseModel):
    """An event's latest cost. Every money field sits next to `currency`."""

    estimated_cost: Money | None = None
    reported_cost: Money | None = None
    currency: str | None = None
    cost_basis: CostBasis
    reason: str | None = None
    pricing_version_id: str | None = None


class PricingVersionOut(BaseModel):
    id: str
    provider: str
    model_id: str
    currency: str
    input_price_per_million: Money | None
    output_price_per_million: Money | None
    cached_input_price: Money | None
    pricing_source: str | None
    valid_from: str
    valid_to: str | None
    created_at: str


class PricingVersionCreate(BaseModel):
    """One catalogue entry. A PUT never edits in place; it versions."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1, max_length=256)
    model_id: str = Field(min_length=1, max_length=256)
    currency: str = Field(default="USD", min_length=1, max_length=16)
    input_price_per_million: Decimal | None = Field(default=None, ge=0)
    output_price_per_million: Decimal | None = Field(default=None, ge=0)
    cached_input_price: Decimal | None = Field(default=None, ge=0)
    pricing_source: str | None = Field(default=None, max_length=2048)
    valid_from: AwareDatetime | None = None


class RepriceResponse(BaseModel):
    version: PricingVersionOut
    repriced: int
