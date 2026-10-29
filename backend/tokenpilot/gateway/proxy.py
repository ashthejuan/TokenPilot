"""Capture proxy core: forward bytes unchanged, record usage afterwards.

The request body goes upstream byte-for-byte, with one exception: a
`stream: true` request without `stream_options` gains
`stream_options.include_usage=true` so the final usage chunk exists to record.
The body is otherwise parsed only to compute the request fingerprint and
context-block hashes; message text never reaches the ledger.

Recording always runs after the upstream response completes (or fails) and can
never break the client response: failures are logged redacted and swallowed.
"""

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator, Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from typing import Any

import anyio
import anyio.to_thread
import httpx

from tokenpilot.db.database import Database
from tokenpilot.gateway.errors import error_category
from tokenpilot.gateway.usage_extract import UsageFields, extract_usage, has_any_tokens
from tokenpilot.ledger.fingerprint import context_blocks, request_fingerprint
from tokenpilot.ledger.ingest import GatewayDefaults, ingest_event
from tokenpilot.schemas.usage import EventStatus, UsageEventIn, UsageSource
from tokenpilot.security import redact_text

logger = logging.getLogger("tokenpilot.gateway")

EVENT_ID_HEADER = "X-TokenPilot-Event-Id"

ATTRIBUTION_HEADERS = (
    "x-tokenpilot-project",
    "x-tokenpilot-session",
    "x-tokenpilot-task",
    "x-tokenpilot-retry-of",
    "x-tokenpilot-benchmark-run",
)

# Never forwarded upstream: client credentials (replaced), hop framing
# (recomputed), and TokenPilot attribution (consumed here).
_SKIP_UPSTREAM_HEADERS = frozenset(
    {"authorization", "host", "content-length", "accept-encoding", *ATTRIBUTION_HEADERS}
)

# D14: the gateway takes upstream bodies uncompressed and relays them without
# hop-by-hop or framing headers.
_DROP_RESPONSE_HEADERS = frozenset(
    {
        "connection",
        "keep-alive",
        "proxy-authenticate",
        "proxy-authorization",
        "te",
        "trailer",
        "transfer-encoding",
        "upgrade",
        "content-length",
        "content-encoding",
    }
)


@dataclass(frozen=True)
class PreparedBody:
    """A client body ready to forward, plus what was learned by parsing it."""

    forward: bytes
    parsed: dict[str, Any] | None
    model_id: str
    fingerprint: str | None
    context_metadata: dict[str, Any]
    added_include_usage: bool
    is_stream: bool


def prepare_body(raw: bytes) -> PreparedBody:
    """Parse `raw` for routing metadata. Unparseable bodies forward unchanged."""
    try:
        parsed: Any = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        parsed = None
    if not isinstance(parsed, dict):
        return PreparedBody(raw, None, "unknown", None, {}, False, False)
    model = parsed.get("model")
    model_id = model if isinstance(model, str) and model else "unknown"
    messages = parsed.get("messages")
    message_dicts = (
        [m for m in messages if isinstance(m, dict)] if isinstance(messages, list) else None
    )
    fingerprint: str | None = None
    context_metadata: dict[str, Any] = {}
    if message_dicts is not None:
        tools = parsed.get("tools")
        try:
            fingerprint = request_fingerprint(
                model_id, message_dicts, tools if isinstance(tools, list) else None
            )
        except Exception:
            # Malformed tools (e.g. non-dict items have no .get): the request
            # still relays byte-for-byte; only the best-effort fingerprint is
            # dropped, and the event records with request_fingerprint None.
            fingerprint = None
        blocks = context_blocks(message_dicts)
        if blocks:
            context_metadata = {
                "context_blocks": [asdict(block) for block in blocks],
                "context_blocks_basis": "approximate",
            }
    forward = raw
    added_include_usage = False
    is_stream = parsed.get("stream") is True
    if is_stream and "stream_options" not in parsed:
        parsed["stream_options"] = {"include_usage": True}
        forward = json.dumps(parsed).encode("utf-8")
        added_include_usage = True
    return PreparedBody(
        forward, parsed, model_id, fingerprint, context_metadata, added_include_usage, is_stream
    )


@dataclass(frozen=True)
class Attribution:
    project: str | None
    session: str | None
    task: str | None
    retry_of: str | None
    benchmark_run: str | None


def read_attribution(headers: Mapping[str, str]) -> Attribution:
    """Read the `X-TokenPilot-*` attribution headers. Empty means absent."""
    lowered = {name.lower(): value for name, value in headers.items()}
    return Attribution(
        project=lowered.get(ATTRIBUTION_HEADERS[0]) or None,
        session=lowered.get(ATTRIBUTION_HEADERS[1]) or None,
        task=lowered.get(ATTRIBUTION_HEADERS[2]) or None,
        retry_of=lowered.get(ATTRIBUTION_HEADERS[3]) or None,
        benchmark_run=lowered.get(ATTRIBUTION_HEADERS[4]) or None,
    )


def is_benchmark_request(headers: Mapping[str, str]) -> bool:
    """True when the benchmark-run attribution header marks worker traffic."""
    return read_attribution(headers).benchmark_run is not None


def build_upstream_headers(headers: Mapping[str, str], api_key: str) -> dict[str, str]:
    """Rewrite client headers for upstream: fresh auth, identity encoding."""
    forwarded = {
        name: value for name, value in headers.items() if name.lower() not in _SKIP_UPSTREAM_HEADERS
    }
    forwarded["Authorization"] = f"Bearer {api_key}"
    forwarded["Accept-Encoding"] = "identity"
    return forwarded


def relay_response_headers(
    upstream: httpx.Headers, event_id: str | None
) -> dict[str, str]:
    """Filter an upstream response's headers for the client.

    `event_id` is `None` only for the models relay, which records no event and
    therefore names none.
    """
    relayed = {
        name: value
        for name, value in upstream.items()
        if name.lower() not in _DROP_RESPONSE_HEADERS
    }
    if event_id is not None:
        relayed[EVENT_ID_HEADER] = event_id
    return relayed


@dataclass
class CaptureContext:
    """Everything needed to record one gatewayed request once it completes."""

    db: Database
    provider: str
    event_id: str
    started_at: datetime
    start_mono: float
    model_id: str
    fingerprint: str | None
    metadata: dict[str, Any]
    project_id: str | None = None
    external_session_id: str | None = None
    task_id: str | None = None
    retry_of: str | None = None
    benchmark_run_id: str | None = None
    defaults: GatewayDefaults | None = None
    http_status: int | None = None
    status: EventStatus = "success"
    error_category: str | None = None
    usage: UsageFields = field(default_factory=UsageFields)
    completed_at: datetime | None = None
    latency_ms: int = 0

    def finish(self, usage: UsageFields | None = None) -> None:
        """Stamp completion. Latency runs from send to last byte, never including
        recording."""
        if usage is not None:
            self.usage = usage
        self.completed_at = datetime.now(UTC)
        self.latency_ms = max(0, int((time.monotonic() - self.start_mono) * 1000))

    def usage_source(self) -> UsageSource:
        return "provider" if has_any_tokens(self.usage) else "unavailable"

    def build_event(self) -> UsageEventIn:
        return UsageEventIn(
            provider=self.provider,
            model_id=self.model_id,
            started_at=self.started_at,
            completed_at=self.completed_at,
            input_tokens=self.usage.input_tokens,
            output_tokens=self.usage.output_tokens,
            cached_tokens=self.usage.cached_tokens,
            reasoning_tokens=self.usage.reasoning_tokens,
            latency_ms=self.latency_ms,
            http_status=self.http_status,
            error_category=self.error_category,
            usage_source=self.usage_source(),
            status=self.status,
            source_event_id=self.usage.source_event_id,
            project_id=self.project_id,
            external_session_id=self.external_session_id,
            task_id=self.task_id,
            retry_of=self.retry_of,
            request_fingerprint=self.fingerprint,
            benchmark_run_id=self.benchmark_run_id,
            metadata=self.metadata,
        )

    async def record(self) -> None:
        """Persist the event. Ledger failures are logged redacted and swallowed:
        the client response is already decided and must not change."""
        try:
            await anyio.to_thread.run_sync(self._write)
        except Exception as exc:
            logger.error(
                "gateway recording failed for event %s: %s",
                self.event_id,
                redact_text(f"{type(exc).__name__}: {exc}"),
            )

    def _write(self) -> None:
        with self.db.write() as conn:
            ingest_event(
                conn,
                self.build_event(),
                source="gateway",
                defaults=self.defaults,
                event_id=self.event_id,
            )


def finish_buffered(ctx: CaptureContext, status: int, body: bytes) -> None:
    """Complete a non-streaming capture: relay status decides success/error, and
    usage is extracted best-effort (a non-JSON body simply has none)."""
    fields = UsageFields()
    try:
        parsed: Any = json.loads(body.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        parsed = None
    if isinstance(parsed, dict):
        fields = extract_usage(parsed)
    ctx.http_status = status
    ctx.status = "success" if 200 <= status < 300 else "error"
    ctx.error_category = error_category(status, None)
    ctx.finish(fields)


def _scan_sse(data: bytes) -> tuple[bytes, dict[str, Any] | None]:
    """Split complete lines off `data`; return the remainder plus the last
    `data:` payload carrying a `usage` object, if any."""
    found: dict[str, Any] | None = None
    *lines, rest = data.split(b"\n")
    for line in lines:
        text = line.decode("utf-8", errors="replace").strip()
        if not text.startswith("data:"):
            continue
        payload = text[len("data:") :].strip()
        if not payload or payload == "[DONE]":
            continue
        try:
            decoded: Any = json.loads(payload)
        except ValueError:
            continue
        if isinstance(decoded, dict) and isinstance(decoded.get("usage"), dict):
            found = decoded
    return rest, found


async def relay_stream(
    upstream: httpx.Response, ctx: CaptureContext
) -> AsyncIterator[bytes]:
    """Yield each upstream chunk unchanged while watching `data:` lines for usage.

    Usage comes from the last chunk that has it. Recording happens in `finally`
    under a shielded cancel scope, so a cancelled client still leaves an event.
    A mid-stream transport failure ends the relay (headers are already sent, so
    the client keeps the partial stream) and is recorded as an error.
    """
    ctx.http_status = upstream.status_code
    last_with_usage: dict[str, Any] | None = None
    buffer = b""
    try:
        async for chunk in upstream.aiter_bytes():
            buffer, found = _scan_sse(buffer + chunk)
            if found is not None:
                last_with_usage = found
            yield chunk
    except (GeneratorExit, asyncio.CancelledError):
        ctx.status = "error"
        ctx.error_category = "client_disconnected"
        raise
    except httpx.TransportError as exc:
        ctx.status = "error"
        ctx.error_category = error_category(None, exc)
        logger.info(
            "gateway upstream stream failed for event %s: %s",
            ctx.event_id,
            redact_text(f"{type(exc).__name__}: {exc}"),
        )
    except httpx.StreamError as exc:
        # Not a TransportError in httpx, but the same story: the pipe broke.
        ctx.status = "error"
        ctx.error_category = "connection_error"
        logger.info(
            "gateway upstream stream failed for event %s: %s",
            ctx.event_id,
            redact_text(f"{type(exc).__name__}: {exc}"),
        )
    finally:
        _, found = _scan_sse(buffer + b"\n")
        if found is not None:
            last_with_usage = found
        ctx.finish(
            extract_usage(last_with_usage) if last_with_usage is not None else UsageFields()
        )
        with anyio.CancelScope(shield=True):
            await ctx.record()
