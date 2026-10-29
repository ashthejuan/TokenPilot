"""Assemble a bounded, redacted evidence bundle for Meta Muse investigations."""

from __future__ import annotations

import sqlite3
import uuid
from dataclasses import asdict, dataclass, field
from decimal import Decimal
from typing import Any

from tokenpilot.config import Settings
from tokenpilot.insights.repository import InsightRepository
from tokenpilot.ledger.repository import LedgerRepository
from tokenpilot.pricing.catalog import select_pricing
from tokenpilot.schemas.insights import InsightOut, InvestigationMode
from tokenpilot.schemas.usage import UsageEvent
from tokenpilot.security import redact_text

MAX_BUNDLE_EVENTS = 50
MAX_EXCERPTS = 10
MAX_EXCERPT_CHARS = 2000

_EVENT_MISSING_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cached_tokens",
    "latency_ms",
    "cost",
    "error_category",
)


@dataclass
class EventBundleRow:
    id: str
    model_id: str
    provider: str
    status: str
    error_category: str | None
    input_tokens: int | None
    output_tokens: int | None
    cached_tokens: int | None
    latency_ms: int | None
    cost: float | None
    retry_group_id: str | None
    attempt: int | None
    started_at: str
    session_id: str | None = None


@dataclass
class EvidenceBundle:
    investigation_id: str
    insight: dict[str, Any]
    events: list[dict[str, Any]]
    aggregates: dict[str, Any]
    outcomes: list[dict[str, Any]]
    pricing: list[dict[str, Any]]
    excerpts: list[dict[str, Any]]
    coverage: dict[str, Any]
    allowed_ids: list[str] = field(default_factory=list)
    allowed_numbers: list[float | int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _event_cost(event: UsageEvent) -> float | None:
    if event.cost is None or event.cost.estimated_cost is None:
        return None
    return float(event.cost.estimated_cost)


def _to_event_row(event: UsageEvent) -> EventBundleRow:
    error = event.error_category
    return EventBundleRow(
        id=event.id,
        model_id=redact_text(event.model_id),
        provider=redact_text(event.provider),
        status=event.status,
        error_category=None if error is None else redact_text(error),
        input_tokens=event.input_tokens,
        output_tokens=event.output_tokens,
        cached_tokens=event.cached_tokens,
        latency_ms=event.latency_ms,
        cost=_event_cost(event),
        retry_group_id=event.retry_group_id,
        attempt=event.attempt,
        started_at=event.started_at,
        session_id=event.session_id,
    )


def _row_dict(row: EventBundleRow) -> dict[str, Any]:
    data = asdict(row)
    # session_id is used while assembling; keep it in the row for allowed_ids /
    # neighbours but drop it from the model-facing event payload.
    data.pop("session_id", None)
    return data


def _load_events(conn: sqlite3.Connection, event_ids: list[str]) -> dict[str, UsageEvent]:
    if not event_ids:
        return {}
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        "SELECT id, source_event_id, idempotency_key, project_id, session_id, task_id, "
        "provider, model_id, input_tokens, output_tokens, cached_tokens, reasoning_tokens, "
        "usage_source, status, latency_ms, http_status, retry_group_id, retry_source, "
        "attempt, request_fingerprint, started_at, completed_at, error_category, "
        "benchmark_run_id, metadata_json FROM usage_events WHERE id IN "
        f"({placeholders})",
        event_ids,
    ).fetchall()
    loaded = LedgerRepository(conn).with_costs([UsageEvent.from_ledger_row(row) for row in rows])
    return {event.id: event for event in loaded}


def _temporal_neighbours(
    conn: sqlite3.Connection,
    session_ids: set[str],
    already: set[str],
    limit: int,
) -> list[str]:
    if limit <= 0 or not session_ids:
        return []
    placeholders = ", ".join("?" for _ in session_ids)
    rows = conn.execute(
        "SELECT id FROM usage_events WHERE session_id IN "
        f"({placeholders}) ORDER BY started_at ASC, id ASC",
        sorted(session_ids),
    ).fetchall()
    neighbours: list[str] = []
    for row in rows:
        event_id = str(row["id"])
        if event_id in already:
            continue
        neighbours.append(event_id)
        if len(neighbours) >= limit:
            break
    return neighbours


def _aggregates(events: list[EventBundleRow]) -> dict[str, Any]:
    known_costs = [row.cost for row in events if row.cost is not None]
    unknown = sum(1 for row in events if row.cost is None)
    aggregates: dict[str, Any] = {
        "event_count": len(events),
        "known_cost_sum": float(sum(known_costs)) if known_costs else 0.0,
        "unknown_cost_events": unknown,
    }
    if known_costs:
        aggregates["currency"] = "USD"
    return aggregates


def _coverage(events: list[EventBundleRow], truncated: int, unknown_cost: int) -> dict[str, Any]:
    missing: set[str] = set()
    for row in events:
        data = asdict(row)
        for name in _EVENT_MISSING_FIELDS:
            if data.get(name) is None:
                missing.add(name)
    return {
        "missing_fields": sorted(missing),
        "unknown_cost_events": unknown_cost,
        "events_truncated": truncated,
    }


def _outcomes(
    conn: sqlite3.Connection,
    insight: InsightOut,
    events: list[EventBundleRow],
) -> list[dict[str, Any]]:
    session_ids: set[str] = set()
    task_ids: set[str] = set()
    if insight.session_id:
        session_ids.add(insight.session_id)
    if insight.task_id:
        task_ids.add(insight.task_id)
    for ref in insight.evidence:
        if ref.kind == "session":
            session_ids.add(ref.id)
        elif ref.kind == "task":
            task_ids.add(ref.id)
    for row in events:
        if row.session_id:
            session_ids.add(row.session_id)

    outcomes: list[dict[str, Any]] = []
    if session_ids:
        placeholders = ", ".join("?" for _ in session_ids)
        for row in conn.execute(
            f"SELECT id, outcome FROM sessions WHERE id IN ({placeholders})",
            sorted(session_ids),
        ):
            outcomes.append(
                {
                    "kind": "session",
                    "id": str(row["id"]),
                    "outcome": str(row["outcome"]),
                }
            )
    if task_ids:
        placeholders = ", ".join("?" for _ in task_ids)
        for row in conn.execute(
            f"SELECT id, outcome FROM tasks WHERE id IN ({placeholders})",
            sorted(task_ids),
        ):
            outcomes.append(
                {
                    "kind": "task",
                    "id": str(row["id"]),
                    "outcome": str(row["outcome"]),
                }
            )
    return outcomes


def _pricing_rows(conn: sqlite3.Connection, events: list[EventBundleRow]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    rows: list[dict[str, Any]] = []
    for event in events:
        # Provider is redacted on the row; look up from the raw event table.
        raw = conn.execute(
            "SELECT provider, model_id, started_at FROM usage_events WHERE id = ?",
            (event.id,),
        ).fetchone()
        if raw is None:
            continue
        key = (str(raw["provider"]), str(raw["model_id"]))
        if key in seen:
            continue
        seen.add(key)
        version = select_pricing(conn, key[0], key[1], str(raw["started_at"]))
        if version is None:
            rows.append(
                {
                    "model_id": redact_text(key[1]),
                    "input_price_per_million": None,
                    "output_price_per_million": None,
                    "pricing_source": None,
                }
            )
            continue
        rows.append(
            {
                "model_id": redact_text(version.model_id),
                "input_price_per_million": (
                    None
                    if version.input_price_per_million is None
                    else float(version.input_price_per_million)
                ),
                "output_price_per_million": (
                    None
                    if version.output_price_per_million is None
                    else float(version.output_price_per_million)
                ),
                "pricing_source": version.pricing_source,
            }
        )
    return rows


def _load_excerpts(conn: sqlite3.Connection, event_ids: list[str]) -> list[dict[str, Any]]:
    if not event_ids:
        return []
    placeholders = ", ".join("?" for _ in event_ids)
    rows = conn.execute(
        "SELECT id, usage_event_id, role, text FROM content_excerpts "
        f"WHERE usage_event_id IN ({placeholders}) ORDER BY created_at ASC, id ASC "
        f"LIMIT {MAX_EXCERPTS}",
        event_ids,
    ).fetchall()
    excerpts: list[dict[str, Any]] = []
    for row in rows:
        text = redact_text(str(row["text"]))[:MAX_EXCERPT_CHARS]
        excerpts.append(
            {
                "id": str(row["id"]),
                "usage_event_id": str(row["usage_event_id"]),
                "role": row["role"],
                "text": text,
            }
        )
    return excerpts


def _collect_ids(
    insight: InsightOut,
    event_rows: list[EventBundleRow],
    outcomes: list[dict[str, Any]],
    aggregates: dict[str, Any],
) -> list[str]:
    ids: list[str] = [insight.id]
    for row in event_rows:
        ids.append(row.id)
        if row.session_id:
            ids.append(row.session_id)
    if insight.session_id:
        ids.append(insight.session_id)
    if insight.task_id:
        ids.append(insight.task_id)
    for ref in insight.evidence:
        if ref.kind in ("session", "task", "aggregate", "benchmark_run"):
            ids.append(ref.id)
    for outcome in outcomes:
        ids.append(str(outcome["id"]))
    # Aggregate label ids: string values under aggregates that look like labels.
    for key, value in aggregates.items():
        if isinstance(value, str) and value and key.endswith("_id"):
            ids.append(value)
    # Deduplicate while preserving order.
    seen: set[str] = set()
    ordered: list[str] = []
    for item in ids:
        if item not in seen:
            seen.add(item)
            ordered.append(item)
    return ordered


def _walk_numbers(value: Any, out: list[float | int]) -> None:
    if isinstance(value, bool):
        return
    if isinstance(value, Decimal):
        out.append(float(value))
        return
    if isinstance(value, int):
        out.append(value)
        return
    if isinstance(value, float):
        out.append(value)
        return
    if isinstance(value, dict):
        for child in value.values():
            _walk_numbers(child, out)
        return
    if isinstance(value, list):
        out.append(len(value))
        for child in value:
            _walk_numbers(child, out)


def _allowed_numbers(payload: dict[str, Any]) -> list[float | int]:
    found: list[float | int] = []
    _walk_numbers(payload, found)
    # Deduplicate while preserving first-seen order (float equality for 0.22).
    ordered: list[float | int] = []
    seen: set[float | int] = set()
    for number in found:
        if number not in seen:
            seen.add(number)
            ordered.append(number)
    return ordered


def build_bundle(
    conn: sqlite3.Connection,
    insight_id: str,
    mode: InvestigationMode,
    *,
    settings: Settings,
    investigation_id: str | None = None,
) -> EvidenceBundle:
    """Build a disclosure-ready evidence bundle for one insight.

    Raises `LookupError` when the insight is missing, and `PermissionError` when
    `mode == "with_excerpts"` but content transmission/store is disabled.
    Missing insight is always preferred over permission failure so the API can
    return 404 rather than 403 for unknown ids.
    """
    insight = InsightRepository(conn).get(insight_id)
    if insight is None:
        raise LookupError(f"insight {insight_id!r} not found")

    if mode == "with_excerpts" and not (
        settings.allow_content_transmission and settings.store_content
    ):
        raise PermissionError("content transmission or storage is disabled")

    evidence_event_ids = [ref.id for ref in insight.evidence if ref.kind == "usage_event"]
    selected_ids = evidence_event_ids[:MAX_BUNDLE_EVENTS]
    remaining_slots = MAX_BUNDLE_EVENTS - len(selected_ids)

    loaded = _load_events(conn, evidence_event_ids)
    session_ids = {
        event.session_id
        for event_id in selected_ids
        if (event := loaded.get(event_id)) is not None and event.session_id
    }
    sessions = {sid for sid in session_ids if sid}
    if len(evidence_event_ids) > MAX_BUNDLE_EVENTS:
        truncated = len(evidence_event_ids) - MAX_BUNDLE_EVENTS
        neighbour_ids: list[str] = []
    else:
        all_neighbour_ids = _temporal_neighbours(conn, sessions, set(evidence_event_ids), 10_000)
        truncated = max(0, len(evidence_event_ids) + len(all_neighbour_ids) - MAX_BUNDLE_EVENTS)
        neighbour_ids = all_neighbour_ids[:remaining_slots]
    selected_ids = selected_ids + neighbour_ids

    all_loaded = {**loaded, **_load_events(conn, neighbour_ids)}
    event_rows: list[EventBundleRow] = []
    for event_id in selected_ids:
        event = all_loaded.get(event_id)
        if event is None:
            continue
        event_rows.append(_to_event_row(event))

    insight_slice = {
        "rule_id": insight.rule_id,
        "rule_version": insight.rule_version,
        "title": redact_text(insight.title),
        "summary": redact_text(insight.summary),
        "measurements": insight.measurements,
        "severity": insight.severity,
        "confidence": insight.confidence,
    }
    aggregates = _aggregates(event_rows)
    outcomes = _outcomes(conn, insight, event_rows)
    pricing = _pricing_rows(conn, event_rows)
    excerpts = (
        _load_excerpts(conn, [row.id for row in event_rows]) if mode == "with_excerpts" else []
    )
    coverage = _coverage(event_rows, truncated, aggregates["unknown_cost_events"])

    event_dicts = [_row_dict(row) for row in event_rows]
    allowed_ids = _collect_ids(insight, event_rows, outcomes, aggregates)
    inv_id = investigation_id or uuid.uuid4().hex

    walk_payload = {
        "insight": insight_slice,
        "events": event_dicts,
        "aggregates": aggregates,
        "outcomes": outcomes,
        "pricing": pricing,
        "excerpts": excerpts,
        "coverage": coverage,
    }
    allowed_numbers = _allowed_numbers(walk_payload)

    return EvidenceBundle(
        investigation_id=inv_id,
        insight=insight_slice,
        events=event_dicts,
        aggregates=aggregates,
        outcomes=outcomes,
        pricing=pricing,
        excerpts=excerpts,
        coverage=coverage,
        allowed_ids=allowed_ids,
        allowed_numbers=allowed_numbers,
    )


def disclosure_lines(
    *,
    destination: str,
    model: str,
    contains_content: bool,
    contributor_training: bool,
) -> list[str]:
    """Build the human-readable disclosure lines for the preview response (Q8)."""
    lines = [
        destination,
        model,
        "includes request excerpts" if contains_content else "metadata only",
    ]
    if contributor_training:
        lines.append(
            "Contributor mode: Meta may use the content you send to train future models."
        )
    return lines


def is_contributor_model(model: str) -> bool:
    return "contributor" in model.lower()
