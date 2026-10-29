"""Direct Meta Muse client for structured investigation completions (not via /gateway)."""

from __future__ import annotations

import json
from typing import Any, TypedDict

import httpx
from openai import OpenAI

from tokenpilot.config import Settings


class UsageFields(TypedDict):
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None


class MetaClient:
    """Call upstream Chat Completions with a strict json_schema response_format."""

    def __init__(
        self,
        settings: Settings,
        *,
        http_client: httpx.Client | None = None,
    ) -> None:
        api_key = ""
        if settings.upstream_api_key is not None:
            api_key = settings.upstream_api_key.get_secret_value()
        kwargs: dict[str, Any] = {
            "base_url": settings.upstream_base_url,
            "api_key": api_key,
        }
        if http_client is not None:
            kwargs["http_client"] = http_client
        self._client = OpenAI(**kwargs)

    def complete_structured(
        self,
        *,
        system: str,
        user: str,
        schema: dict[str, Any],
        model: str,
    ) -> tuple[dict[str, Any], UsageFields]:
        # Do not pass stop / n / logit_bias (gateway-forbidden params for Muse).
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "investigation",
                    "schema": schema,
                    "strict": True,
                },
            },
            reasoning_effort="low",
        )
        content = response.choices[0].message.content
        if not content:
            raise ValueError("empty investigation completion content")
        parsed = json.loads(content)
        if not isinstance(parsed, dict):
            raise ValueError("investigation completion must be a JSON object")
        return parsed, _usage_fields(response.usage)


def _usage_fields(usage: Any) -> UsageFields:
    if usage is None:
        return {"input_tokens": None, "output_tokens": None, "cached_tokens": None}

    input_tokens = getattr(usage, "prompt_tokens", None)
    if input_tokens is None:
        input_tokens = getattr(usage, "input_tokens", None)

    output_tokens = getattr(usage, "completion_tokens", None)
    if output_tokens is None:
        output_tokens = getattr(usage, "output_tokens", None)

    cached_tokens: int | None = getattr(usage, "cached_tokens", None)
    if cached_tokens is None:
        details = getattr(usage, "prompt_tokens_details", None)
        if details is not None:
            cached_tokens = getattr(details, "cached_tokens", None)
        if cached_tokens is None and isinstance(usage, dict):
            nested = usage.get("prompt_tokens_details") or {}
            if isinstance(nested, dict):
                cached = nested.get("cached_tokens")
                cached_tokens = cached if isinstance(cached, int) else None

    return {
        "input_tokens": input_tokens if isinstance(input_tokens, int) else None,
        "output_tokens": output_tokens if isinstance(output_tokens, int) else None,
        "cached_tokens": cached_tokens if isinstance(cached_tokens, int) else None,
    }
