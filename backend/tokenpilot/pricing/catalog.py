"""Versioned price catalogue: YAML seeds plus time-range selection.

A price is never edited in place. A new price for the same (provider, model)
closes the open row (`valid_to` = the new `valid_from`) and inserts a new row,
so old cost records keep pointing at the version that priced them.
"""

import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from tokenpilot.timeutil import to_utc_z, utc_now_z

__all__ = [
    "PricingVersion",
    "PricingVersionConflictError",
    "create_version",
    "current_versions",
    "load_catalog",
    "select_pricing",
]

_VERSION_COLUMNS = (
    "id, provider, model_id, currency, input_price_per_million, "
    "output_price_per_million, cached_input_price, pricing_source, valid_from, "
    "valid_to, created_at"
)
_PRICE_FIELDS = (
    "input_price_per_million",
    "output_price_per_million",
    "cached_input_price",
)


@dataclass(frozen=True)
class PricingVersion:
    id: str
    provider: str
    model_id: str
    currency: str
    input_price_per_million: Decimal | None
    output_price_per_million: Decimal | None
    cached_input_price: Decimal | None
    pricing_source: str | None
    valid_from: str
    valid_to: str | None
    created_at: str


class PricingVersionConflictError(ValueError):
    """The same (provider, model, valid_from) already exists with other content."""


def _decimal_or_none(value: object) -> Decimal | None:
    # `str()` keeps floats on their shortest repr (`0.3`, not the binary expansion).
    return None if value is None else Decimal(str(value))


def _version_from_row(row: sqlite3.Row) -> PricingVersion:
    return PricingVersion(
        id=str(row["id"]),
        provider=str(row["provider"]),
        model_id=str(row["model_id"]),
        currency=str(row["currency"]),
        input_price_per_million=_decimal_or_none(row["input_price_per_million"]),
        output_price_per_million=_decimal_or_none(row["output_price_per_million"]),
        cached_input_price=_decimal_or_none(row["cached_input_price"]),
        pricing_source=row["pricing_source"],
        valid_from=str(row["valid_from"]),
        valid_to=row["valid_to"],
        created_at=str(row["created_at"]),
    )


def _normalize_catalog_timestamp(value: object, *, entry: str) -> str:
    """Format a catalogue `valid_from` as fixed-ms `Z` so range filters compare safely."""
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError as exc:
            raise ValueError(f"{entry}: invalid valid_from {value!r}") from exc
    else:
        raise ValueError(f"{entry}: valid_from must be a string, got {value!r}")
    if parsed.tzinfo is None:
        raise ValueError(f"{entry}: valid_from {value!r} must include a timezone")
    return to_utc_z(parsed)


def _parse_price(value: object, *, entry: str, field: str) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        raise ValueError(f"{entry}: {field} must be a decimal string, got {value!r}")
    try:
        return Decimal(str(value))
    except ArithmeticError as exc:
        raise ValueError(f"{entry}: {field} is not a number: {value!r}") from exc


def _require_text(entry: dict[str, Any], field: str, *, label: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label}: {field} must be a non-empty string")
    return value


def create_version(
    conn: sqlite3.Connection,
    *,
    provider: str,
    model_id: str,
    currency: str,
    input_price_per_million: Decimal | None,
    output_price_per_million: Decimal | None,
    cached_input_price: Decimal | None,
    pricing_source: str | None,
    valid_from: str,
) -> tuple[PricingVersion, bool]:
    """Insert a new version, closing the open ones. Idempotent on identical content.

    Returns the version and whether a row was written. `valid_from` must already
    be a fixed-ms `Z` string (callers normalize at the boundary).
    """
    existing = conn.execute(
        f"SELECT {_VERSION_COLUMNS} FROM pricing_versions "
        "WHERE provider = ? AND model_id = ? AND valid_from = ?",
        (provider, model_id, valid_from),
    ).fetchone()
    if existing is not None:
        current = _version_from_row(existing)
        identical = (
            current.currency == currency
            and current.input_price_per_million == input_price_per_million
            and current.output_price_per_million == output_price_per_million
            and current.cached_input_price == cached_input_price
            and current.pricing_source == pricing_source
        )
        if identical:
            return current, False
        raise PricingVersionConflictError(
            f"a version for {provider}/{model_id} at {valid_from} already exists "
            "with different content"
        )
    conn.execute(
        "UPDATE pricing_versions SET valid_to = ? "
        "WHERE provider = ? AND model_id = ? AND valid_to IS NULL AND valid_from <= ?",
        (valid_from, provider, model_id, valid_from),
    )
    version = PricingVersion(
        id=uuid.uuid4().hex,
        provider=provider,
        model_id=model_id,
        currency=currency,
        input_price_per_million=input_price_per_million,
        output_price_per_million=output_price_per_million,
        cached_input_price=cached_input_price,
        pricing_source=pricing_source,
        valid_from=valid_from,
        valid_to=None,
        created_at=utc_now_z(),
    )
    conn.execute(
        "INSERT INTO pricing_versions (id, provider, model_id, currency, "
        "input_price_per_million, output_price_per_million, cached_input_price, "
        "pricing_source, valid_from, valid_to, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            version.id,
            version.provider,
            version.model_id,
            version.currency,
            None if version.input_price_per_million is None
            else float(version.input_price_per_million),
            None if version.output_price_per_million is None
            else float(version.output_price_per_million),
            None if version.cached_input_price is None
            else float(version.cached_input_price),
            version.pricing_source,
            version.valid_from,
            version.valid_to,
            version.created_at,
        ),
    )
    return version, True


def load_catalog(conn: sqlite3.Connection, path: Path | str) -> int:
    """Upsert every entry of a catalogue YAML file; returns rows written."""
    resolved = Path(path)
    data = yaml.safe_load(resolved.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"pricing catalog {resolved} must hold a list of entries")
    written = 0
    for index, item in enumerate(data):
        label = f"pricing catalog {resolved} entry {index}"
        if not isinstance(item, dict):
            raise ValueError(f"{label} must be a mapping")
        entry: dict[str, Any] = item
        pricing_source = entry.get("pricing_source")
        if pricing_source is not None and not isinstance(pricing_source, str):
            raise ValueError(f"{label}: pricing_source must be a string")
        _, created = create_version(
            conn,
            provider=_require_text(entry, "provider", label=label),
            model_id=_require_text(entry, "model_id", label=label),
            currency=_require_text(entry, "currency", label=label),
            input_price_per_million=_parse_price(
                entry.get("input_price_per_million"),
                entry=label,
                field="input_price_per_million",
            ),
            output_price_per_million=_parse_price(
                entry.get("output_price_per_million"),
                entry=label,
                field="output_price_per_million",
            ),
            cached_input_price=_parse_price(
                entry.get("cached_input_price"), entry=label, field="cached_input_price"
            ),
            pricing_source=pricing_source,
            valid_from=_normalize_catalog_timestamp(entry.get("valid_from"), entry=label),
        )
        written += created
    return written


def select_pricing(
    conn: sqlite3.Connection, provider: str, model_id: str, at: str
) -> PricingVersion | None:
    """The version in force at `at`: latest `valid_from`, `valid_to` exclusive."""
    row = conn.execute(
        f"SELECT {_VERSION_COLUMNS} FROM pricing_versions "
        "WHERE provider = ? AND model_id = ? AND valid_from <= ? "
        "AND (valid_to IS NULL OR ? < valid_to) "
        "ORDER BY valid_from DESC LIMIT 1",
        (provider, model_id, at, at),
    ).fetchone()
    return _version_from_row(row) if row is not None else None


def current_versions(conn: sqlite3.Connection) -> list[PricingVersion]:
    rows = conn.execute(
        f"SELECT {_VERSION_COLUMNS} FROM pricing_versions "
        "WHERE valid_to IS NULL ORDER BY provider, model_id"
    ).fetchall()
    return [_version_from_row(row) for row in rows]
