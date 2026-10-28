"""Local access control and secret redaction."""

import os
import re
import secrets
from collections.abc import Iterable, Mapping

from fastapi import HTTPException, Request

REDACTED = "[REDACTED]"

SENSITIVE_HEADERS = frozenset(
    {
        "authorization",
        "proxy-authorization",
        "x-api-key",
        "api-key",
        "x-goog-api-key",
        "cookie",
        "set-cookie",
    }
)

_SECRET_PATTERNS = (
    re.compile(r"sk-[A-Za-z0-9]{16,}"),
    re.compile(r"Bearer\s+\S+", re.IGNORECASE),
)

_ENV_SECRET_NAMES = ("MODEL_API_KEY", "TOKENPILOT_LOCAL_TOKEN")
_MIN_SECRET_LENGTH = 6


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """Return a copy of `headers` with credential values replaced by `[REDACTED]`."""
    return {
        name: REDACTED if name.lower() in SENSITIVE_HEADERS else value
        for name, value in headers.items()
    }


def _known_secrets(extra: Iterable[str] | None) -> tuple[str, ...]:
    values = [value for value in (extra or ()) if value]
    values.extend(value for name in _ENV_SECRET_NAMES if (value := os.environ.get(name)))
    unique = {value for value in values if len(value) >= _MIN_SECRET_LENGTH}
    # Longest first so a secret that contains another secret is masked whole.
    return tuple(sorted(unique, key=len, reverse=True))


def redact_text(text: str, *, secrets_to_mask: Iterable[str] | None = None) -> str:
    """Mask API-key-shaped strings and known secret values inside free text."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    for secret in _known_secrets(secrets_to_mask):
        text = text.replace(secret, REDACTED)
    return text


async def require_local_token(request: Request) -> None:
    """Reject any request that does not carry the configured local bearer token."""
    expected = request.app.state.settings.local_token.get_secret_value()
    authorization = request.headers.get("authorization", "")
    scheme, _, provided = authorization.partition(" ")
    provided = provided.strip()

    authorized = scheme.lower() == "bearer" and bool(provided) and secrets.compare_digest(
        provided.encode(), expected.encode()
    )
    if not authorized:
        raise HTTPException(
            status_code=401,
            detail="missing or invalid local token",
            headers={"WWW-Authenticate": "Bearer"},
        )
