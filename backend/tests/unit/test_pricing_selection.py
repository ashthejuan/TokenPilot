"""Unit tests for the pricing catalogue: seeds, selection, versioning (Task 1.3)."""

import copy
import sqlite3
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
import yaml

import tokenpilot.pricing.catalog as catalog_module
from tokenpilot.db.connection import connect
from tokenpilot.db.migrate import migrate
from tokenpilot.pricing.catalog import load_catalog, select_pricing
from tokenpilot.pricing.cost import compute_cost
from tokenpilot.schemas.usage import UsageEvent
from tokenpilot.timeutil import to_utc_z

CATALOG_PATH = Path(catalog_module.__file__).parent / "catalog.yaml"
META_URL = "https://dev.meta.ai/docs/pricing-rate-limits"

# Verbatim from the brief: two fake rows plus six meta rows.
EXPECTED_SEEDS = [
    ("fake", "fake-large", "3.00", "15.00", "0.30", "demo-simulated", "2026-01-01T00:00:00Z"),
    ("fake", "fake-small", "0.25", "1.25", "0.025", "demo-simulated", "2026-01-01T00:00:00Z"),
    ("meta", "muse-wonder-1.0", "4.00", "20.00", "0.20", META_URL, "2026-10-28T00:00:00Z"),
    ("meta", "muse-spark-1.3", "1.25", "4.25", "0.15", META_URL, "2026-10-28T00:00:00Z"),
    ("meta", "muse-spark-1.2", "1.25", "4.25", "0.15", META_URL, "2026-10-28T00:00:00Z"),
    ("meta", "muse-spark-1.1", "1.25", "4.25", "0.15", META_URL, "2026-10-28T00:00:00Z"),
    (
        "meta",
        "muse-spark-1.3-contributor",
        "0.10",
        "0.20",
        "0.002",
        META_URL,
        "2026-10-28T00:00:00Z",
    ),
    (
        "meta",
        "muse-spark-1.2-contributor",
        "0.10",
        "0.20",
        "0.002",
        META_URL,
        "2026-10-28T00:00:00Z",
    ),
]


@pytest.fixture
def conn(tmp_path: Path) -> Iterator[sqlite3.Connection]:
    connection = connect(tmp_path / "pricing.sqlite3")
    migrate(connection)
    yield connection
    connection.close()


def make_event(**overrides: Any) -> UsageEvent:
    base: dict[str, Any] = {
        "id": "e1",
        "source_event_id": None,
        "idempotency_key": "k1",
        "project_id": None,
        "session_id": None,
        "task_id": None,
        "provider": "meta",
        "model_id": "muse-spark-1.3-contributor",
        "input_tokens": 1_000_000,
        "output_tokens": 100_000,
        "cached_tokens": 200_000,
        "reasoning_tokens": None,
        "usage_source": "provider",
        "status": "success",
        "latency_ms": None,
        "http_status": None,
        "retry_group_id": None,
        "retry_source": None,
        "attempt": None,
        "request_fingerprint": None,
        "started_at": "2026-10-29T00:00:00.000Z",
        "completed_at": None,
        "error_category": None,
        "benchmark_run_id": None,
        "metadata": {},
    }
    return UsageEvent.model_validate({**base, **overrides})


def pricing_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM pricing_versions").fetchone()
    return int(row["n"])


def test_seed_catalog_yaml_is_verbatim() -> None:
    """Prices stay YAML strings so they parse straight to Decimal, never via float."""
    entries = yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8"))

    assert isinstance(entries, list)
    assert len(entries) == len(EXPECTED_SEEDS)
    for entry, expected in zip(entries, EXPECTED_SEEDS, strict=True):
        provider, model_id, pi, po, pc, source, valid_from = expected
        assert entry["provider"] == provider
        assert entry["model_id"] == model_id
        assert entry["currency"] == "USD"
        for field, value in (
            ("input_price_per_million", pi),
            ("output_price_per_million", po),
            ("cached_input_price", pc),
        ):
            assert entry[field] == value, (model_id, field)
            assert isinstance(entry[field], str), (model_id, field)
        assert entry["pricing_source"] == source
        assert entry["valid_from"] == valid_from


def test_seed_catalog_loads_all_rows(conn: sqlite3.Connection) -> None:
    written = load_catalog(conn, CATALOG_PATH)

    assert written == 8
    assert pricing_count(conn) == 8
    for provider, model_id, pi, po, pc, source, valid_from in EXPECTED_SEEDS:
        version = select_pricing(conn, provider, model_id, "2026-11-01T00:00:00.000Z")
        assert version is not None, model_id
        assert version.input_price_per_million == Decimal(pi)
        assert version.output_price_per_million == Decimal(po)
        assert version.cached_input_price == Decimal(pc)
        assert version.currency == "USD"
        assert version.pricing_source == source
        assert version.valid_from == to_utc_z(datetime.fromisoformat(valid_from))
        assert version.valid_to is None


def test_pricing_selected_by_event_time(conn: sqlite3.Connection, tmp_path: Path) -> None:
    catalog = tmp_path / "catalog.yaml"
    catalog.write_text(
        yaml.safe_dump(
            [
                {
                    "provider": "acme",
                    "model_id": "big",
                    "currency": "USD",
                    "input_price_per_million": "1.00",
                    "output_price_per_million": "1.00",
                    "cached_input_price": None,
                    "pricing_source": "https://example.com/v1",
                    "valid_from": "2026-01-01T00:00:00Z",
                },
                {
                    "provider": "acme",
                    "model_id": "big",
                    "currency": "USD",
                    "input_price_per_million": "2.00",
                    "output_price_per_million": "2.00",
                    "cached_input_price": None,
                    "pricing_source": "https://example.com/v2",
                    "valid_from": "2026-10-01T00:00:00Z",
                },
            ]
        ),
        encoding="utf-8",
    )
    load_catalog(conn, catalog)

    before = select_pricing(conn, "acme", "big", "2026-09-30T23:59:59.999Z")
    assert before is not None
    assert before.input_price_per_million == Decimal("1.00")

    # At the exact boundary the new version applies (`valid_to` is exclusive).
    at_cutover = select_pricing(conn, "acme", "big", "2026-10-01T00:00:00.000Z")
    assert at_cutover is not None
    assert at_cutover.input_price_per_million == Decimal("2.00")

    after = select_pricing(conn, "acme", "big", "2026-11-01T00:00:00.000Z")
    assert after is not None
    assert after.id == at_cutover.id


def test_load_catalog_idempotent_and_versions_changes(
    conn: sqlite3.Connection, tmp_path: Path
) -> None:
    assert load_catalog(conn, CATALOG_PATH) == 8

    assert load_catalog(conn, CATALOG_PATH) == 0
    assert pricing_count(conn) == 8

    entries = copy.deepcopy(yaml.safe_load(CATALOG_PATH.read_text(encoding="utf-8")))
    entries[1]["output_price_per_million"] = "2.50"
    entries[1]["valid_from"] = "2026-06-01T00:00:00Z"
    changed = tmp_path / "changed.yaml"
    changed.write_text(yaml.safe_dump(entries), encoding="utf-8")

    assert load_catalog(conn, changed) == 1
    assert pricing_count(conn) == 9

    rows = conn.execute(
        "SELECT output_price_per_million, valid_from, valid_to FROM pricing_versions "
        "WHERE provider = 'fake' AND model_id = 'fake-small' ORDER BY valid_from"
    ).fetchall()
    assert len(rows) == 2
    assert rows[0]["valid_to"] == to_utc_z(datetime.fromisoformat("2026-06-01T00:00:00+00:00"))
    assert Decimal(str(rows[1]["output_price_per_million"])) == Decimal("2.50")
    assert rows[1]["valid_to"] is None


def test_meta_contributor_seed_cost(conn: sqlite3.Connection) -> None:
    load_catalog(conn, CATALOG_PATH)

    pricing = select_pricing(
        conn, "meta", "muse-spark-1.3-contributor", "2026-10-29T00:00:00.000Z"
    )
    assert pricing is not None
    assert pricing.pricing_source == META_URL

    result = compute_cost(make_event(), pricing)

    assert result.estimated_cost == Decimal("0.1004")
    assert result.cost_basis == "estimated"
    assert result.currency == "USD"


def test_meta_event_before_price_date_is_no_pricing(conn: sqlite3.Connection) -> None:
    load_catalog(conn, CATALOG_PATH)

    pricing = select_pricing(
        conn, "meta", "muse-spark-1.3-contributor", "2026-10-01T00:00:00.000Z"
    )

    result = compute_cost(make_event(started_at="2026-10-01T00:00:00.000Z"), pricing)

    assert result.estimated_cost is None
    assert result.reason == "no_pricing"
    assert result.cost_basis == "unavailable"
