"""OpenAI-compatible capture proxy: relay bytes, record attributed usage."""

import time
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, Response, StreamingResponse

from tokenpilot.config import Settings
from tokenpilot.db.database import Database, get_db
from tokenpilot.gateway.errors import error_category
from tokenpilot.gateway.proxy import (
    EVENT_ID_HEADER,
    CaptureContext,
    PreparedBody,
    build_upstream_headers,
    finish_buffered,
    is_benchmark_request,
    prepare_body,
    read_attribution,
    relay_response_headers,
    relay_stream,
)
from tokenpilot.ledger.ingest import GatewayDefaults

router = APIRouter(prefix="/gateway", tags=["gateway"])


def _error_content(code: str, message: str) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": None}}


def _chat_url(base_url: str) -> str:
    return base_url.rstrip("/") + "/chat/completions"


def _models_url(base_url: str, query: str) -> str:
    url = base_url.rstrip("/") + "/models"
    return f"{url}?{query}" if query else url


def _settings(request: Request) -> Settings:
    settings: Settings = request.app.state.settings
    return settings


def _upstream_client(request: Request) -> httpx.AsyncClient:
    if is_benchmark_request(request.headers):
        dedicated: httpx.AsyncClient = request.app.state.benchmark_upstream
        return dedicated
    client: httpx.AsyncClient = request.app.state.upstream
    return client


def _upstream_key(settings: Settings) -> str:
    if settings.upstream_api_key is None:
        return ""
    return settings.upstream_api_key.get_secret_value()


async def _timeout_response(ctx: CaptureContext, exc: BaseException) -> JSONResponse:
    ctx.status = "timeout"
    ctx.error_category = error_category(None, exc)
    ctx.finish()
    await ctx.record()
    return JSONResponse(
        status_code=504,
        content=_error_content("upstream_timeout", "upstream request timed out"),
        headers={EVENT_ID_HEADER: ctx.event_id},
    )


async def _transport_error_response(ctx: CaptureContext, exc: BaseException) -> JSONResponse:
    ctx.status = "error"
    ctx.error_category = error_category(None, exc)
    ctx.finish()
    await ctx.record()
    return JSONResponse(
        status_code=502,
        content=_error_content("upstream_error", "upstream request failed"),
        headers={EVENT_ID_HEADER: ctx.event_id},
    )


async def _chat(
    request: Request, db: Database, project_slug: str | None
) -> Response:
    settings = _settings(request)
    api_key = _upstream_key(settings)
    if not api_key.strip():
        # D13: nothing was sent upstream, so nothing is recorded.
        return JSONResponse(
            status_code=503,
            content=_error_content("upstream_not_configured", "upstream API key is not configured"),
        )
    event_id = uuid.uuid4().hex
    prepared = prepare_body(await request.body())
    attribution = read_attribution(request.headers)
    metadata = dict(prepared.context_metadata)
    if prepared.added_include_usage:
        metadata["gateway_added_include_usage"] = True
    ctx = CaptureContext(
        db=db,
        provider=settings.upstream_provider,
        event_id=event_id,
        started_at=datetime.now(UTC),
        start_mono=time.monotonic(),
        model_id=prepared.model_id,
        fingerprint=prepared.fingerprint,
        metadata=metadata,
        project_id=attribution.project,
        external_session_id=attribution.session,
        task_id=attribution.task,
        retry_of=attribution.retry_of,
        benchmark_run_id=attribution.benchmark_run,
        defaults=GatewayDefaults(project_ref=project_slug),
    )
    headers = build_upstream_headers(request.headers, api_key)
    client = _upstream_client(request)
    if prepared.is_stream:
        url = _chat_url(settings.upstream_base_url)
        return await _stream_request(client, url, prepared, headers, ctx)
    try:
        upstream = await client.post(
            _chat_url(settings.upstream_base_url), content=prepared.forward, headers=headers
        )
    except httpx.TimeoutException as exc:
        return await _timeout_response(ctx, exc)
    except httpx.TransportError as exc:
        return await _transport_error_response(ctx, exc)
    finish_buffered(ctx, upstream.status_code, upstream.content)
    await ctx.record()
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=relay_response_headers(upstream.headers, event_id),
    )


async def _stream_request(
    client: httpx.AsyncClient,
    url: str,
    prepared: PreparedBody,
    headers: dict[str, str],
    ctx: CaptureContext,
) -> Response:
    stream_cm = client.stream("POST", url, content=prepared.forward, headers=headers)
    try:
        upstream = await stream_cm.__aenter__()
    except httpx.TimeoutException as exc:
        return await _timeout_response(ctx, exc)
    except httpx.TransportError as exc:
        return await _transport_error_response(ctx, exc)
    if upstream.status_code >= 400:
        # A stream request can still fail fast with a JSON error: relay it whole.
        try:
            body = await upstream.aread()
        except httpx.TimeoutException as exc:
            await stream_cm.__aexit__(None, None, None)
            return await _timeout_response(ctx, exc)
        except httpx.TransportError as exc:
            await stream_cm.__aexit__(None, None, None)
            return await _transport_error_response(ctx, exc)
        await stream_cm.__aexit__(None, None, None)
        finish_buffered(ctx, upstream.status_code, body)
        await ctx.record()
        return Response(
            content=body,
            status_code=upstream.status_code,
            headers=relay_response_headers(upstream.headers, ctx.event_id),
        )

    async def _generate() -> AsyncIterator[bytes]:
        try:
            async for chunk in relay_stream(upstream, ctx):
                yield chunk
        finally:
            await stream_cm.__aexit__(None, None, None)

    return StreamingResponse(
        _generate(),
        status_code=upstream.status_code,
        headers=relay_response_headers(upstream.headers, ctx.event_id),
    )


@router.post("/v1/chat/completions")
async def chat_completions(
    request: Request, db: Annotated[Database, Depends(get_db)]
) -> Response:
    return await _chat(request, db, None)


@router.post("/p/{project_slug}/v1/chat/completions")
async def chat_completions_for_project(
    request: Request, db: Annotated[Database, Depends(get_db)], project_slug: str
) -> Response:
    return await _chat(request, db, project_slug)


async def _models(request: Request) -> Response:
    """A plain relay: a model listing is not usage, so no event is recorded."""
    settings = _settings(request)
    api_key = _upstream_key(settings)
    if not api_key.strip():
        return JSONResponse(
            status_code=503,
            content=_error_content("upstream_not_configured", "upstream API key is not configured"),
        )
    headers = build_upstream_headers(request.headers, api_key)
    try:
        upstream = await _upstream_client(request).get(
            _models_url(settings.upstream_base_url, request.url.query), headers=headers
        )
    except httpx.TimeoutException:
        return JSONResponse(
            status_code=504,
            content=_error_content("upstream_timeout", "upstream request timed out"),
        )
    except httpx.TransportError:
        return JSONResponse(
            status_code=502, content=_error_content("upstream_error", "upstream request failed")
        )
    return Response(
        content=upstream.content,
        status_code=upstream.status_code,
        headers=relay_response_headers(upstream.headers, None),
    )


@router.get("/v1/models")
async def list_models(request: Request) -> Response:
    return await _models(request)


@router.get("/p/{project_slug}/v1/models")
async def list_models_for_project(request: Request, project_slug: str) -> Response:
    _ = project_slug
    return await _models(request)
