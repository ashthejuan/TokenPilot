"""Validate InvestigationOutput against an EvidenceBundle (IDs + numbers)."""

from __future__ import annotations

import re
from typing import Any

from tokenpilot.investigator.evidence import EvidenceBundle
from tokenpilot.investigator.schema import InvestigationOutput, ValidationIssue

# Q10: numbers in prose; currency symbols ignored by the regex itself.
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*%?")

# Relative tolerance vs allowed_numbers.
_REL_TOL = 0.005

# Skip ID lists for number scanning (validated separately as evidence ids).
_SKIP_NUMBER_KEYS = frozenset({"evidence_ids"})


def validate_output(
    out: InvestigationOutput, bundle: EvidenceBundle
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    allowed_ids = set(bundle.allowed_ids)
    for i, fact in enumerate(out.observed_facts):
        for j, eid in enumerate(fact.evidence_ids):
            if eid not in allowed_ids:
                issues.append(
                    ValidationIssue(
                        code="unknown_evidence_id",
                        message=f"evidence id {eid!r} is not in the evidence bundle",
                        path=f"observed_facts[{i}].evidence_ids[{j}]",
                    )
                )

    payload = out.model_dump()
    for path, text in _string_fields(payload):
        for match in _NUMBER_RE.finditer(text):
            token = match.group(0)
            if _number_allowed(token, bundle.allowed_numbers, bundle.aggregates):
                continue
            issues.append(
                ValidationIssue(
                    code="unsupported_number",
                    message=f"number {token!r} is not supported by bundle measurements",
                    path=path,
                )
            )
    return issues


def _string_fields(value: Any, path: str = "") -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else key
            if key in _SKIP_NUMBER_KEYS:
                continue
            found.extend(_string_fields(child, child_path))
        return found
    if isinstance(value, list):
        for i, child in enumerate(value):
            found.extend(_string_fields(child, f"{path}[{i}]"))
        return found
    if isinstance(value, str):
        found.append((path, value))
    return found


def _number_allowed(
    token: str,
    allowed_numbers: list[float | int],
    aggregates: dict[str, Any],
) -> bool:
    is_percent = token.endswith("%")
    raw = token[:-1] if is_percent else token
    raw = raw.replace(",", "")
    try:
        value = float(raw)
    except ValueError:
        return False

    if not is_percent and _is_exempt_ordinal_or_year(value, raw):
        return True

    if _matches_allowed(value, allowed_numbers):
        return True

    if is_percent:
        # "50%" may correspond to rate 0.5 in allowed_numbers / aggregates.
        if _matches_allowed(value / 100.0, allowed_numbers):
            return True
        if _matches_aggregate_percentage(value, aggregates):
            return True

    return False


def _is_exempt_ordinal_or_year(value: float, raw: str) -> bool:
    # Only whole numbers written without a fractional part qualify.
    if "." in raw:
        return False
    as_int = int(value)
    if value != as_int:
        return False
    if 1 <= as_int <= 10:
        return True
    return 2000 <= as_int <= 2100


def _matches_allowed(value: float, allowed_numbers: list[float | int]) -> bool:
    return any(_within_rel_tol(value, float(allowed)) for allowed in allowed_numbers)


def _within_rel_tol(a: float, b: float) -> bool:
    scale = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / scale <= _REL_TOL


def _matches_aggregate_percentage(percent: float, aggregates: dict[str, Any]) -> bool:
    """Allow percent tokens that equal 100 * a numeric aggregate rate/share."""
    for value in aggregates.values():
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            derived = float(value) * 100.0
            if _within_rel_tol(percent, derived):
                return True
            # Also allow the aggregate itself being the percent (e.g. 12.5).
            if _within_rel_tol(percent, float(value)):
                return True
    return False
