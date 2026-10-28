"""Map upstream failures to the ledger's `error_category` vocabulary."""

import asyncio

import httpx

# How a cancelled client shows up: `GeneratorExit` when an async generator is
# closed, `CancelledError` when the serving task is cancelled (asyncio backend).
_CLIENT_CANCELLED: tuple[type[BaseException], ...] = (GeneratorExit, asyncio.CancelledError)


def error_category(status: int | None, exc: BaseException | None) -> str | None:
    """Categorize an upstream outcome. 2xx/3xx and clean streams map to `None`."""
    if exc is not None:
        if isinstance(exc, httpx.TimeoutException):
            return "timeout"
        if isinstance(exc, httpx.TransportError):
            return "connection_error"
        if isinstance(exc, _CLIENT_CANCELLED):
            return "client_disconnected"
    if status is None:
        return None
    if status == 400:
        return "bad_request"
    if status in (401, 403):
        return "auth"
    if status == 404:
        return "not_found"
    if status == 408:
        return "timeout"
    if status == 413:
        return "too_large"
    if status == 429:
        return "rate_limited"
    if 400 <= status < 500:
        return "client_error"
    if 500 <= status < 600:
        return "upstream_error"
    return None
