"""Cost engine: price one event, record it, reprice after a catalogue change.

`prompt_tokens` includes cached tokens and `completion_tokens` includes reasoning
tokens (OpenAI semantics), so cached tokens are split out of the input price and
reasoning tokens are never added again. A NULL cost always carries a `reason`.
"""

import math
import sqlite3
import uuid
from dataclasses import dataclass
from decimal import ROUND_HALF_EVEN, Decimal
from typing import Any, Literal

from tokenpilot.pricing.catalog import PricingVersion, select_pricing
from tokenpilot.schemas.pricing import CostBasis, CostSummary
from tokenpilot.schemas.usage import UsageEvent
from tokenpilot.timeutil import utc_now_z

__all__ = [
    "CostRecord",
    "CostResult",
    "compute_cost",
    "latest_cost_sql",
    "latest_costs_for",
    "quantize_money",
    "record_cost",
    "reprice_all",
    "to_cost_summary",
]

_MONEY_QUANT = Decimal("1e-10")
_MILLION = Decimal(1_000_000)

CostReason = Literal["no_pricing", "usage_unavailable", "inconsistent_usage"]

# The newest cost record per event. Two records in the same millisecond resolve
# by `rowid`, so repricing twice in a row still picks deterministically.
latest_cost_sql = (
    "latest_costs AS (SELECT * FROM cost_records c WHERE c.rowid = "
    "(SELECT c2.rowid FROM cost_records c2 "
    "WHERE c2.usage_event_id = c.usage_event_id "
    "ORDER BY c2.calculated_at DESC, c2.rowid DESC LIMIT 1))"
)


@dataclass(frozen=True)
class CostResult:
    estimated_cost: Decimal | None
    reported_cost: Decimal | None
    currency: str | None
    pricing_version_id: str | None
    cost_basis: CostBasis
    reason: CostReason | None


@dataclass(frozen=True)
class CostRecord:
    id: str
    usage_event_id: str
    pricing_version_id: str | None
    estimated_cost: Decimal | None
    reported_cost: Decimal | None
    billed_cost: Decimal | None
    currency: str | None
    cost_basis: CostBasis
    reason: str | None
    calculated_at: str


def quantize_money(value: Decimal) -> Decimal:
    return value.quantize(_MONEY_QUANT, rounding=ROUND_HALF_EVEN)


def _reported(metadata: dict[str, Any]) -> tuple[Decimal | None, str | None]:
    """A provider-reported cost from metadata, or `(None, None)` when absent."""
    raw_cost = metadata.get("reported_cost")
    if (
        isinstance(raw_cost, bool)
        or not isinstance(raw_cost, (int, float, Decimal))
        or not math.isfinite(float(raw_cost))
    ):
        return None, None
    raw_currency = metadata.get("reported_currency")
    currency = raw_currency if isinstance(raw_currency, str) and raw_currency else None
    return quantize_money(Decimal(str(raw_cost))), currency


def compute_cost(event: UsageEvent, pricing: PricingVersion | None) -> CostResult:
    reported_cost, reported_currency = _reported(event.metadata)
    currency = pricing.currency if pricing is not None else reported_currency
    pricing_version_id = pricing.id if pricing is not None else None

    estimated: Decimal | None = None
    reason: CostReason | None = None
    if (
        pricing is None
        or pricing.input_price_per_million is None
        or pricing.output_price_per_million is None
    ):
        reason = "no_pricing"
    elif event.input_tokens is None or event.output_tokens is None:
        reason = "usage_unavailable"
    else:
        cached = event.cached_tokens if event.cached_tokens is not None else 0
        if cached > event.input_tokens:
            reason = "inconsistent_usage"
        else:
            input_price = pricing.input_price_per_million
            output_price = pricing.output_price_per_million
            assert input_price is not None and output_price is not None
            cached_price = (
                pricing.cached_input_price
                if pricing.cached_input_price is not None
                else input_price
            )
            estimated = quantize_money(
                (
                    Decimal(event.input_tokens - cached) * input_price
                    + Decimal(cached) * cached_price
                    + Decimal(event.output_tokens) * output_price
                )
                / _MILLION
            )

    if reported_cost is not None:
        basis: CostBasis = "reported"
    elif estimated is not None:
        basis = "estimated"
    else:
        basis = "unavailable"
    return CostResult(
        estimated_cost=estimated,
        reported_cost=reported_cost,
        currency=currency,
        pricing_version_id=pricing_version_id,
        cost_basis=basis,
        reason=reason,
    )


def _to_real(value: Decimal | None) -> float | None:
    return None if value is None else float(value)


def _decimal_or_none(value: object) -> Decimal | None:
    return None if value is None else Decimal(str(value))


def _record_from_row(row: sqlite3.Row) -> CostRecord:
    basis = row["cost_basis"]
    assert basis in ("estimated", "reported", "billed", "unavailable")
    return CostRecord(
        id=str(row["id"]),
        usage_event_id=str(row["usage_event_id"]),
        pricing_version_id=row["pricing_version_id"],
        estimated_cost=_decimal_or_none(row["estimated_cost"]),
        reported_cost=_decimal_or_none(row["reported_cost"]),
        billed_cost=_decimal_or_none(row["billed_cost"]),
        currency=row["currency"],
        cost_basis=basis,
        reason=row["reason"],
        calculated_at=str(row["calculated_at"]),
    )


def to_cost_summary(record: CostRecord) -> CostSummary:
    return CostSummary(
        estimated_cost=record.estimated_cost,
        reported_cost=record.reported_cost,
        currency=record.currency,
        cost_basis=record.cost_basis,
        reason=record.reason,
        pricing_version_id=record.pricing_version_id,
    )


def record_cost(conn: sqlite3.Connection, event_id: str) -> CostRecord:
    """Price one event and append the record. History rows are never updated."""
    row = conn.execute("SELECT * FROM usage_events WHERE id = ?", (event_id,)).fetchone()
    if row is None:
        raise ValueError(f"unknown usage event {event_id!r}")
    event = UsageEvent.from_ledger_row(dict(row))
    pricing = select_pricing(conn, event.provider, event.model_id, event.started_at)
    result = compute_cost(event, pricing)
    record = CostRecord(
        id=uuid.uuid4().hex,
        usage_event_id=event_id,
        pricing_version_id=result.pricing_version_id,
        estimated_cost=result.estimated_cost,
        reported_cost=result.reported_cost,
        billed_cost=None,
        currency=result.currency,
        cost_basis=result.cost_basis,
        reason=result.reason,
        calculated_at=utc_now_z(),
    )
    conn.execute(
        "INSERT INTO cost_records (id, usage_event_id, pricing_version_id, estimated_cost, "
        "reported_cost, billed_cost, currency, cost_basis, reason, calculated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            record.id,
            record.usage_event_id,
            record.pricing_version_id,
            _to_real(record.estimated_cost),
            _to_real(record.reported_cost),
            _to_real(record.billed_cost),
            record.currency,
            record.cost_basis,
            record.reason,
            record.calculated_at,
        ),
    )
    return record


def reprice_all(
    conn: sqlite3.Connection,
    provider: str | None = None,
    model_id: str | None = None,
) -> int:
    """Append a fresh cost record for every matching event; returns the count."""
    clauses: list[str] = []
    params: list[str] = []
    for column, value in (("provider", provider), ("model_id", model_id)):
        if value is not None:
            clauses.append(f"{column} = ?")
            params.append(value)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = conn.execute(
        f"SELECT id FROM usage_events {where} ORDER BY started_at, id", params
    ).fetchall()
    for row in rows:
        record_cost(conn, row["id"])
    return len(rows)


def latest_costs_for(
    conn: sqlite3.Connection, event_ids: list[str]
) -> dict[str, CostRecord]:
    """The newest cost record per event id, via the shared `latest_costs` CTE."""
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        f"WITH {latest_cost_sql} SELECT * FROM latest_costs "
        f"WHERE usage_event_id IN ({placeholders})",
        event_ids,
    ).fetchall()
    return {str(row["usage_event_id"]): _record_from_row(row) for row in rows}
