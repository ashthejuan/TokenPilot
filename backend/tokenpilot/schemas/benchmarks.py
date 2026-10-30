"""Benchmark experiment and run shapes (Task 4.3)."""

from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from tokenpilot.schemas.common import Money

ContextStrategy = Literal["full_repo", "targeted"]
RunStatus = Literal["queued", "running", "completed", "failed"]
RunOutcome = Literal["passed", "failed", "timed_out", "cancelled", "inconclusive"]

TERMINAL_STATUSES: tuple[str, str] = ("completed", "failed")


class RetryPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    max_retries: int = Field(default=0, ge=0, le=10)


class RunConfig(BaseModel):
    """One variant's agent configuration, as stored in `benchmark_runs.config_json`."""

    model_config = ConfigDict(extra="forbid")

    model_id: str = Field(min_length=1, max_length=256)
    context_strategy: ContextStrategy = "full_repo"
    max_steps: int = Field(ge=1, le=100)
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    temperature: float | None = Field(default=None, ge=0, le=2)
    prompt_template: str = Field(default="fix_v1", max_length=64)
    context_files: list[str] = Field(default_factory=list)


class AcceptanceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    command: list[str] = Field(min_length=1)
    required_pass: list[str] = Field(default_factory=list)
    min_success_rate: float = Field(default=1.0, ge=0, le=1)


class AlternativeSpec(BaseModel):
    """One alternative variant: a name, baseline changes, and targeted files."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=128)
    changes: dict[str, Any] = Field(default_factory=dict)
    context_files: list[str] = Field(default_factory=list)


class BenchmarkCreate(BaseModel):
    """`POST /api/v1/benchmarks` body: the `benchmark_task.yaml` shape plus project."""

    model_config = ConfigDict(extra="forbid")

    project_id: str = Field(min_length=1)
    repository_path: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    description: str | None = None
    task_prompt: str = Field(min_length=1)
    initial_ref: str = Field(default="main", min_length=1, max_length=256)
    acceptance: AcceptanceConfig
    timeout_s: int = Field(default=300, gt=0, le=3600)
    repeat_count: int = Field(default=1, ge=1, le=20)
    baseline: RunConfig
    alternatives: list[AlternativeSpec] = Field(default_factory=list)


class BenchmarkTaskSpec(BaseModel):
    """`benchmark_task.yaml` as accepted by the insight → benchmark bridge.

    `baseline` and `alternatives` are optional: the bridge replaces them with
    the config observed in the insight's session and one derived alternative.
    """

    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    description: str | None = None
    task_prompt: str = Field(min_length=1)
    initial_ref: str = Field(default="main", min_length=1, max_length=256)
    acceptance: AcceptanceConfig
    timeout_s: int = Field(default=300, gt=0, le=3600)
    repeat_count: int | None = Field(default=None, ge=1, le=20)
    baseline: RunConfig | None = None
    alternatives: list[AlternativeSpec] = Field(default_factory=list)


class InsightBenchmarkCreate(BaseModel):
    """`POST /api/v1/insights/{id}/benchmark` body."""

    model_config = ConfigDict(extra="forbid")

    task_spec_path: str | None = Field(default=None, min_length=1, max_length=2048)
    task_spec: dict[str, Any] | None = None
    repeat_count: int | None = Field(default=None, ge=1, le=20)


class BenchmarkOut(BaseModel):
    id: str
    project_id: str
    task_id: str | None
    insight_id: str | None = None
    name: str
    description: str | None
    initial_git_sha: str | None
    acceptance: AcceptanceConfig
    baseline: RunConfig
    alternatives: list[AlternativeSpec]
    task_prompt: str
    initial_ref: str
    repeat_count: int | None
    timeout_s: int | None
    created_at: str


class BenchmarkRunOut(BaseModel):
    id: str
    benchmark_id: str
    variant_name: str
    model_id: str | None
    config: dict[str, Any]
    run_status: RunStatus
    outcome: RunOutcome | None
    total_cost: Money | None
    currency: str | None
    unknown_cost_events: int
    total_tokens: int | None
    request_count: int
    retry_count: int
    duration_ms: int | None
    test_exit_code: int | None
    test_results: dict[str, Any] | None
    patch_path: str | None
    worktree_path: str | None
    started_at: str | None
    completed_at: str | None
    repeat_index: int | None
    error: str | None
    eligible: bool | None


class BenchmarkDetail(BenchmarkOut):
    runs: list[BenchmarkRunOut] = Field(default_factory=list)


class CreateRunsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variants: list[str] = Field(min_length=1)
    repeat_count: int | None = Field(default=None, ge=1, le=20)


class CancelRunsResponse(BaseModel):
    cancelled_run_ids: list[str]


def merge_variant_config(
    baseline: RunConfig, spec: AlternativeSpec | None
) -> dict[str, Any]:
    """Overlay an alternative's `changes` (and `context_files`) onto the baseline."""
    merged: dict[str, Any] = baseline.model_dump(mode="json")
    if spec is not None:
        merged.update(spec.changes)
        if spec.context_files:
            merged["context_files"] = list(spec.context_files)
    # Round-trip through the model so unknown keys and bad types fail here, not mid-run.
    return RunConfig.model_validate(merged).model_dump(mode="json")


def cost_to_decimal(value: float | str | Decimal | None) -> Decimal | None:
    """Lossless float → Decimal for REAL money read back from SQLite."""
    if value is None or isinstance(value, Decimal):
        return value
    return Decimal(str(value))
