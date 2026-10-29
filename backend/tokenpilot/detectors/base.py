"""Shared detector vocabulary: severities, evidence refs, scopes and findings.

Rules are pure functions over a `DetectionContext`; they never write. The
repository turns the `Finding`s they return into `insights` rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal, Protocol

if TYPE_CHECKING:
    from tokenpilot.detectors.facts import DetectionContext

Severity = Literal["informational", "low", "medium", "high"]
SEVERITY_RANK: dict[str, int] = {"informational": 0, "low": 1, "medium": 2, "high": 3}
EvidenceKind = Literal["usage_event", "session", "task", "benchmark_run", "aggregate"]

# P2: `rule_id` is the bare name; display form is `f"{rule_id}.v{rule_version}"`.
RULE_IDS: tuple[str, ...] = (
    "repeated_request",
    "retry_amplification",
    "repeated_context",
    "unsuccessful_task",
    "context_ratio",
    "runaway_session",
    "model_inefficiency",
)

# P17: one insight carries at most this many refs; the rest are counted.
MAX_EVIDENCE = 50

MeasurementValue = float | int | str | bool | None


@dataclass(frozen=True)
class EvidenceRef:
    """One row a finding points at, plus the numbers read from it."""

    kind: EvidenceKind
    id: str
    measurement: dict[str, MeasurementValue] = field(default_factory=dict)


@dataclass(frozen=True)
class Scope:
    """What the finding is about. All three levels are optional."""

    project_id: str | None = None
    session_id: str | None = None
    task_id: str | None = None


@dataclass(frozen=True)
class Finding:
    """A rule's conclusion, before it becomes an insight row."""

    rule_id: str
    rule_version: int
    anchor: str
    severity: Severity
    confidence: float
    title: str
    summary: str
    scope: Scope
    evidence: list[EvidenceRef]
    measurements: dict[str, Any]
    estimated_impact: Decimal | None
    impact_currency: str | None

    @property
    def dedupe_key(self) -> str:
        """P3: a stable per-rule anchor, so a growing session updates one row."""
        return f"{self.rule_id}.v{self.rule_version}:{self.anchor}"


class Detector(Protocol):
    """A pure rule (P4): read the context, return findings. Never writes."""

    rule_id: str
    rule_version: int
    guidance: str

    def detect(self, ctx: DetectionContext) -> list[Finding]:
        """Findings in deterministic order; implementations sort by anchor."""
        ...
