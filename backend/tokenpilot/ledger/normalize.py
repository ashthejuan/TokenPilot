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

_SECRET_KEY = re.compile(r"authorization|api[_-]?key|token|secret|password|cookie", re.IGNORECASE)


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
    """Drop secret-looking keys at any depth and redact secret-shaped strings."""
    if isinstance(value, dict):
        return {k: sanitize_metadata(v) for k, v in value.items() if not _SECRET_KEY.search(k)}
    if isinstance(value, list):
        return [sanitize_metadata(item) for item in value]
    if isinstance(value, str):
        return redact_text(value)
    return value


def _resolve_idempotency_key(
    raw: UsageEventIn, source: str
) -> tuple[str, Literal["key", "not_possible"]]:
    if raw.idempotency_key:
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


def normalize(raw: UsageEventIn, source: str) -> NormalizedEvent:
    metadata = sanitize_metadata(raw.metadata)
    idempotency_key, dedup = _resolve_idempotency_key(raw, source)
    sanitized_input = {**raw.model_dump(mode="json"), "metadata": metadata}
    return NormalizedEvent(
        provider=raw.provider,
        model_id=raw.model_id,
        started_at=to_utc_z(raw.started_at),
        completed_at=to_utc_z(raw.completed_at) if raw.completed_at else None,
        input_tokens=raw.input_tokens,
        output_tokens=raw.output_tokens,
        cached_tokens=raw.cached_tokens,
        reasoning_tokens=raw.reasoning_tokens,
        latency_ms=raw.latency_ms,
        http_status=raw.http_status,
        error_category=raw.error_category,
        usage_source=raw.usage_source,
        status=raw.status,
        source_event_id=raw.source_event_id,
        idempotency_key=idempotency_key,
        dedup=dedup,
        project_id=raw.project_id,
        external_session_id=raw.external_session_id,
        task_id=raw.task_id,
        retry_of=raw.retry_of,
        request_fingerprint=raw.request_fingerprint,
        benchmark_run_id=raw.benchmark_run_id,
        raw_event_json=json.dumps(sanitized_input, sort_keys=True),
        metadata=metadata,
    )
