"""FastAPI application factory and the single structured error shape."""

import argparse
import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import httpx
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import SecretStr
from starlette.exceptions import HTTPException as StarletteHTTPException

from tokenpilot.api.gateway import router as gateway_router
from tokenpilot.api.health import router as health_router
from tokenpilot.api.projects import router as projects_router
from tokenpilot.api.sessions import router as sessions_router
from tokenpilot.api.settings import router as settings_router
from tokenpilot.api.usage import router as usage_router
from tokenpilot.config import Settings
from tokenpilot.db.connection import connect
from tokenpilot.db.database import Database
from tokenpilot.db.migrate import migrate
from tokenpilot.insights.jobs import JobRepository
from tokenpilot.ledger.refs import LedgerRefError
from tokenpilot.pricing.catalog import load_catalog
from tokenpilot.security import redact_text, require_local_token

logger = logging.getLogger("tokenpilot")

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    502: "upstream_error",
    503: "unavailable",
    504: "upstream_timeout",
}


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "details": details}}


async def _handle_http_exception(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _STATUS_CODES.get(exc.status_code, "http_error")
    message = exc.detail if isinstance(exc.detail, str) else code
    return JSONResponse(
        status_code=exc.status_code,
        content=error_body(code, message),
        headers=exc.headers,
    )


async def _handle_validation_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    details = [
        {
            "loc": list(error.get("loc", ())),
            "msg": error.get("msg", "invalid value"),
            "type": error.get("type", "value_error"),
        }
        for error in exc.errors()
    ]
    return JSONResponse(
        status_code=422,
        content=error_body("validation_error", "request validation failed", details),
    )


async def _handle_ledger_ref_error(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, LedgerRefError)
    return JSONResponse(status_code=422, content=error_body(exc.code, str(exc), exc.details))


async def _handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
    # The message is the only thing logged, and it is redacted: PRD §9.5 forbids
    # secrets in logs, and upstream exception text can carry headers or keys.
    logger.error(
        "unhandled error on %s %s: %s",
        request.method,
        request.url.path,
        redact_text(f"{type(exc).__name__}: {exc}"),
    )
    return JSONResponse(
        status_code=500,
        content=error_body("internal_error", "internal server error"),
    )


def create_app(
    settings: Settings | None = None,
    *,
    upstream_transport: httpx.AsyncBaseTransport | None = None,
) -> FastAPI:
    resolved = settings if settings is not None else Settings()
    if not resolved.local_token.get_secret_value().strip():
        raise ValueError("TOKENPILOT_LOCAL_TOKEN must be set and non-empty")

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        connection = connect(resolved.db_path)
        try:
            migrate(connection)
        finally:
            connection.close()
        db = Database(resolved.db_path)
        app.state.db = db
        with db.write() as conn:
            load_catalog(conn, resolved.pricing_catalog_path)
            # A job cannot survive its process: fail the leftovers before serving (P6).
            JobRepository(conn).recover_interrupted()
        timeout = httpx.Timeout(connect=10.0, read=300.0, write=30.0, pool=10.0)
        upstream = httpx.AsyncClient(timeout=timeout, transport=upstream_transport)
        app.state.upstream = upstream
        try:
            yield
        finally:
            await upstream.aclose()
            db.close()

    app = FastAPI(title="TokenPilot API", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved

    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(LedgerRefError, _handle_ledger_ref_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)

    # Auth is applied here, not per router, so a new router cannot forget it.
    for router in (
        health_router,
        usage_router,
        projects_router,
        sessions_router,
        settings_router,
        gateway_router,
    ):
        app.include_router(router, dependencies=[Depends(require_local_token)])
    return app


def export_openapi(path: Path) -> None:
    """Write the API schema to `path`. The app is built with a throwaway token and never started."""
    # model_construct skips env and .env loading: exporting must not need or read secrets.
    settings = Settings.model_construct(local_token=SecretStr("openapi-export-placeholder"))
    schema = create_app(settings).openapi()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(schema, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="tokenpilot.main")
    parser.add_argument("--export-openapi", type=Path, metavar="PATH", required=True)
    args = parser.parse_args(argv)
    export_openapi(args.export_openapi)


if __name__ == "__main__":
    main()
