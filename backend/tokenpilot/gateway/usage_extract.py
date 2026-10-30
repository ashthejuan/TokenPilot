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


def _first_count(usage: dict[str, Any], *keys: str) -> int | None:
    for key in keys:
        value = _count(usage.get(key))
        if value is not None:
            return value
    return None


def usage_body_for_extract(decoded: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the JSON object that carries token usage for `extract_usage`.

    Chat Completions and non-stream Responses put `usage` on the top-level
    body. Meta Responses SSE ends with `response.completed` whose usage sits
    on the nested `response` object (`response.usage`).
    """
    if isinstance(decoded.get("usage"), dict):
        return decoded
    nested = decoded.get("response")
    if isinstance(nested, dict) and isinstance(nested.get("usage"), dict):
        return nested
    return None


def extract_usage(body: dict[str, Any]) -> UsageFields:
    """Read `usage.*` and `id` from a provider response body."""
    carrier = usage_body_for_extract(body) or body
    usage = _section(carrier.get("usage"))
    input_details = _section(usage.get("input_tokens_details"))
    prompt_details = _section(usage.get("prompt_tokens_details"))
    output_details = _section(usage.get("output_tokens_details"))
    completion_details = _section(usage.get("completion_tokens_details"))
    source_id = carrier.get("id")
    cached = _count(input_details.get("cached_tokens"))
    if cached is None:
        cached = _count(prompt_details.get("cached_tokens"))
    reasoning = _count(output_details.get("reasoning_tokens"))
    if reasoning is None:
        reasoning = _count(completion_details.get("reasoning_tokens"))
    return UsageFields(
        input_tokens=_first_count(usage, "input_tokens", "prompt_tokens"),
        output_tokens=_first_count(usage, "output_tokens", "completion_tokens"),
        cached_tokens=cached,
        reasoning_tokens=reasoning,
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
