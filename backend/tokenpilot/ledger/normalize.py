"""Turn an inbound `UsageEventIn` into the form the ledger stores."""

import hashlib
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from typing import Any, Literal

from tokenpilot.schemas.usage import EventStatus, UsageEventIn, UsageSource
from tokenpilot.security import redact_text
from tokenpilot.timeutil import to_utc_z

logger = logging.getLogger("tokenpilot.ledger")

# `token` alone is a credential; `max_tokens`, `token_count`, `tokenizer` are not.
_SECRET_KEY = re.compile(
    r"authorization|api[_-]?key|secret|passw(or)?d|cookie|bearer|token(?!s|_?counts?|izer)",
    re.IGNORECASE,
)
# Request/response bodies must never enter the ledger, whatever the caller nests them under.
_CONTENT_KEYS = frozenset({"messages", "content", "prompt", "completion", "response", "choices"})


@dataclass(frozen=True)
class NormalizedEvent:
    provider: str
    model_id: str
    started_at: str
    completed_at: str | None
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    reasoning_tokens: int | None
    latency_ms: int | None
    http_status: int | None
    error_category: str | None
    usage_source: UsageSource
    status: EventStatus
    source_event_id: str | None
    idempotency_key: str
    dedup: Literal["key", "not_possible"]
    project_id: str | None
    external_session_id: str | None
    task_id: str | None
    retry_of: str | None
    request_fingerprint: str | None
    benchmark_run_id: str | None
    raw_event_json: str
    metadata: dict[str, Any] = field(default_factory=dict)


def sanitize_metadata(value: Any) -> Any:
    """Drop secret and content keys at any depth and redact secret-shaped strings."""
    if isinstance(value, dict):
        return {
            k: sanitize_metadata(v)
            for k, v in value.items()
            if not _SECRET_KEY.search(k) and k.lower() not in _CONTENT_KEYS
        }
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _resolve_idempotency_key(
    raw: UsageEventIn, source: str
) -> tuple[str, Literal["key", "not_possible"]]:
    """Dedup is decided on the original values; redaction would merge distinct secrets."""
    if raw.idempotency_key:
        if redact_text(raw.idempotency_key) != raw.idempotency_key:
            # Secret-shaped key: store a stable digest rather than the key itself.
            return hashlib.sha256(f"key:{raw.idempotency_key}".encode()).hexdigest(), "key"
        return raw.idempotency_key, "key"
    if raw.source_event_id:
        digest = hashlib.sha256(f"{source}:{raw.provider}:{raw.source_event_id}".encode())
        return digest.hexdigest(), "key"
    logger.info(
        "usage event has no idempotency_key or source_event_id; duplicates cannot be detected "
        "(source=%s, provider=%s)",
        source,
        raw.provider,
    )
    return uuid.uuid4().hex, "not_possible"


def _redact_optional(value: str | None) -> str | None:
    return redact_text(value) if value is not None else None


def normalize(raw: UsageEventIn, source: str) -> NormalizedEvent:
    metadata = sanitize_metadata(raw.metadata)
    idempotency_key, dedup = _resolve_idempotency_key(raw, source)
    provider = redact_text(raw.provider)
    model_id = redact_text(raw.model_id)
    source_event_id = _redact_optional(raw.source_event_id)
    error_category = _redact_optional(raw.error_category)
    request_fingerprint = _redact_optional(raw.request_fingerprint)
    external_session_id = _redact_optional(raw.external_session_id)
    task_id = _redact_optional(raw.task_id)
    retry_of = _redact_optional(raw.retry_of)
    # raw_event_json holds the redacted copy of every free-text field, never the original.
    sanitized_input = {
        **raw.model_dump(mode="json"),
        "provider": provider,
        "model_id": model_id,
        "source_event_id": source_event_id,
        "idempotency_key": _redact_optional(raw.idempotency_key),
        "error_category": error_category,
        "request_fingerprint": request_fingerprint,
        "external_session_id": external_session_id,
        "task_id": task_id,
        "retry_of": retry_of,
        "metadata": metadata,
    }
    return NormalizedEvent(
        provider=provider,
        model_id=model_id,
        started_at=to_utc_z(raw.started_at),
        completed_at=to_utc_z(raw.completed_at) if raw.completed_at else None,
        input_tokens=raw.input_tokens,
        output_tokens=raw.output_tokens,
        cached_tokens=raw.cached_tokens,
        reasoning_tokens=raw.reasoning_tokens,
        latency_ms=raw.latency_ms,
        http_status=raw.http_status,
        error_category=error_category,
        usage_source=raw.usage_source,
        status=raw.status,
        source_event_id=source_event_id,
        idempotency_key=idempotency_key,
        dedup=dedup,
        project_id=raw.project_id,
        external_session_id=external_session_id,
        task_id=task_id,
        retry_of=retry_of,
        request_fingerprint=request_fingerprint,
        benchmark_run_id=raw.benchmark_run_id,
        raw_event_json=json.dumps(sanitized_input, sort_keys=True),
        metadata=metadata,
    )
