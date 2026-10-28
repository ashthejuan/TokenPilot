"""Usage event shapes: the inbound payload, the stored row, and list filters."""

from dataclasses import dataclass
from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, NonNegativeInt

UsageSource = Literal["provider", "gateway_estimate", "import", "unavailable"]
EventStatus = Literal["success", "error", "timeout", "unknown"]


class UsageEventIn(BaseModel):
    """What an integration may send. `extra="forbid"` keeps prompt text out of the ledger."""

    model_config = ConfigDict(extra="forbid")

    provider: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    started_at: AwareDatetime
    completed_at: AwareDatetime | None = None
    input_tokens: NonNegativeInt | None = None
    output_tokens: NonNegativeInt | None = None
    cached_tokens: NonNegativeInt | None = None
    reasoning_tokens: NonNegativeInt | None = None
    latency_ms: NonNegativeInt | None = None
    http_status: int | None = None
    error_category: str | None = None
    usage_source: UsageSource
    status: EventStatus
    source_event_id: str | None = None
    idempotency_key: str | None = None
    project_id: str | None = None
    external_session_id: str | None = None
    task_id: str | None = None
    retry_of: str | None = None
    request_fingerprint: str | None = None
    benchmark_run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class UsageEvent(BaseModel):
    """A stored event as the API returns it. Never carries `raw_event_json`."""

    id: str
    source_event_id: str | None
    idempotency_key: str
    project_id: str | None
    session_id: str | None
    task_id: str | None
    provider: str
    model_id: str
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None
    usage_source: UsageSource
    status: EventStatus
    latency_ms: int | None
    http_status: int | None
    retry_group_id: str | None
    retry_source: str | None
    attempt: int | None
    request_fingerprint: str | None
    started_at: str
    completed_at: str | None
    error_category: str | None
    benchmark_run_id: str | None
    metadata: dict[str, Any]


class IngestItemResult(BaseModel):
    id: str
    duplicate: bool


class IngestResponse(BaseModel):
    results: list[IngestItemResult]


@dataclass(frozen=True)
class EventFilters:
    """`started_from` is inclusive, `started_to` exclusive; both are `Z` strings."""

    project_id: str | None = None
    session_id: str | None = None
    model_id: str | None = None
    provider: str | None = None
    status: EventStatus | None = None
    started_from: str | None = None
    started_to: str | None = None
