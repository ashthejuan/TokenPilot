"""Investigation structured-output models, prompt packaging, and strict JSON schema."""

from __future__ import annotations

from importlib.resources import files
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

PROMPT_VERSION = "investigate_v1"

VariableToChange = Literal[
    "model_id",
    "prompt_template",
    "context_strategy",
    "agent_config",
    "tool_permissions",
    "retry_policy",
    "temperature",
    "other",
]
ExpectedDirection = Literal[
    "lower_cost",
    "lower_latency",
    "higher_success_rate",
    "mixed",
]
Confidence = Literal["low", "medium", "high"]
Verdict = Literal["supported", "insufficient_evidence"]


class ObservedFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    statement: str
    evidence_ids: list[str]


class ProposedBenchmark(BaseModel):
    model_config = ConfigDict(extra="forbid")

    baseline_change: str
    alternative_change: str


class Recommendation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action: str
    variable_to_change: VariableToChange
    expected_direction: ExpectedDirection
    validation_procedure: str
    proposed_benchmark: ProposedBenchmark | None = None


class InvestigationOutput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str
    summary: str
    observed_facts: list[ObservedFact]
    root_cause_hypothesis: str
    impact_assessment: str
    recommendation: Recommendation
    confidence: Confidence
    limitations: list[str]
    verdict: Verdict


class ValidationIssue(BaseModel):
    """One validation finding; named Issue to avoid clashing with pydantic.ValidationError."""

    code: str
    message: str
    path: str | None = None


def load_system_prompt() -> str:
    return (
        files("tokenpilot.investigator.prompts")
        .joinpath("investigate_v1.md")
        .read_text(encoding="utf-8")
    )


def investigation_json_schema() -> dict[str, Any]:
    """Export a Chat Completions strict-mode JSON schema for InvestigationOutput."""
    raw = InvestigationOutput.model_json_schema()
    return _strictify(raw)


_STRIP_KEYS = frozenset({"title", "default", "description"})


def _strictify(schema: dict[str, Any]) -> dict[str, Any]:
    """Strict-mode JSON schema: required==properties, no extras, strip pydantic noise."""

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for noise in _STRIP_KEYS:
                node.pop(noise, None)
            if "properties" in node and isinstance(node["properties"], dict):
                node["type"] = "object"
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
                for child in node["properties"].values():
                    walk(child)
            if "items" in node:
                walk(node["items"])
            for union_key in ("anyOf", "oneOf", "allOf"):
                branches = node.get(union_key)
                if isinstance(branches, list):
                    for child in branches:
                        walk(child)
            for key in ("$defs", "definitions"):
                defs = node.get(key)
                if isinstance(defs, dict):
                    for defn in defs.values():
                        walk(defn)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(schema)
    if "properties" in schema:
        schema["type"] = "object"
        schema["additionalProperties"] = False
        schema["required"] = list(schema["properties"].keys())
    return schema
