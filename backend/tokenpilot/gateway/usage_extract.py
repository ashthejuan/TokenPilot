"""Pull token counts out of provider response bodies.

Anything absent or the wrong type becomes `None`: missing telemetry is NULL,
never 0.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class UsageFields:
    input_tokens: int | None = None
    output_tokens: int | None = None
    cached_tokens: int | None = None
    reasoning_tokens: int | None = None
    source_event_id: str | None = None


def _count(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _section(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def extract_usage(body: dict[str, Any]) -> UsageFields:
    """Read `usage.*` and `id` from a provider response body."""
    usage = _section(body.get("usage"))
    prompt_details = _section(usage.get("prompt_tokens_details"))
    completion_details = _section(usage.get("completion_tokens_details"))
    source_id = body.get("id")
    return UsageFields(
        input_tokens=_count(usage.get("prompt_tokens")),
        output_tokens=_count(usage.get("completion_tokens")),
        cached_tokens=_count(prompt_details.get("cached_tokens")),
        reasoning_tokens=_count(completion_details.get("reasoning_tokens")),
        source_event_id=source_id if isinstance(source_id, str) else None,
    )


def has_any_tokens(fields: UsageFields) -> bool:
    """Whether the provider reported at least one token count."""
    return any(
        value is not None
        for value in (
            fields.input_tokens,
            fields.output_tokens,
            fields.cached_tokens,
            fields.reasoning_tokens,
        )
    )
