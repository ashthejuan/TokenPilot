"""Pagination and identifier shapes shared by API schemas."""

import base64
import binascii
import json
from dataclasses import dataclass
from decimal import Decimal
from typing import Annotated

from pydantic import BaseModel, PlainSerializer

SLUG_PATTERN = r"^[a-z0-9][a-z0-9_-]{0,63}$"
DEFAULT_PAGE_LIMIT = 50
MAX_PAGE_LIMIT = 200


# Money is a Decimal in Python (storage and arithmetic) and a JSON number on the wire,
# always paired with a `currency` field.
Money = Annotated[Decimal, PlainSerializer(float, return_type=float, when_used="json")]


class Paged[T](BaseModel):
    items: list[T]
    next_cursor: str | None = None


@dataclass(frozen=True)
class Page:
    limit: int = DEFAULT_PAGE_LIMIT
    cursor: str | None = None


class InvalidCursorError(ValueError):
    """The cursor was not produced by `encode_cursor`."""


def encode_cursor(started_at: str, event_id: str) -> str:
    payload = json.dumps({"s": started_at, "i": event_id}, separators=(",", ":"))
    return base64.urlsafe_b64encode(payload.encode()).decode()


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        payload = json.loads(base64.urlsafe_b64decode(cursor.encode()))
        started_at, event_id = payload["s"], payload["i"]
    except (binascii.Error, ValueError, KeyError, TypeError) as exc:
        raise InvalidCursorError("invalid cursor") from exc
    if not isinstance(started_at, str) or not isinstance(event_id, str):
        raise InvalidCursorError("invalid cursor")
    return started_at, event_id
