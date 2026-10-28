"""FastAPI application factory and the single structured error shape."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from tokenpilot.api.health import router as health_router
from tokenpilot.config import Settings
from tokenpilot.db.connection import connect
from tokenpilot.db.migrate import migrate
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
    503: "unavailable",
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


def create_app(settings: Settings | None = None) -> FastAPI:
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
        yield

    app = FastAPI(title="TokenPilot API", version="0.1.0", lifespan=lifespan)
    app.state.settings = resolved

    app.add_exception_handler(StarletteHTTPException, _handle_http_exception)
    app.add_exception_handler(RequestValidationError, _handle_validation_error)
    app.add_exception_handler(Exception, _handle_unexpected_error)

    # Auth is applied here, not per router, so a new router cannot forget it.
    app.include_router(health_router, dependencies=[Depends(require_local_token)])
    return app
