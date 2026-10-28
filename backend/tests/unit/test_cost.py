"""Unit tests for `compute_cost`: formula, bases, reasons, rounding (Task 1.3)."""

from decimal import Decimal
from typing import Any

import pytest

from tokenpilot.pricing.catalog import PricingVersion
from tokenpilot.pricing.cost import compute_cost
from tokenpilot.schemas.usage import UsageEvent


def make_event(**overrides: Any) -> UsageEvent:
    base: dict[str, Any] = {
        "id": "e1",
        "source_event_id": None,
        "idempotency_key": "k1",
        "project_id": None,
        "session_id": None,
        "task_id": None,
        "provider": "acme",
        "model_id": "big",
        "input_tokens": None,
        "output_tokens": None,
        "cached_tokens": None,
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


def make_pricing(**overrides: Any) -> PricingVersion:
    base: dict[str, Any] = {
        "id": "pv1",
        "provider": "acme",
        "model_id": "big",
        "currency": "USD",
        "input_price_per_million": Decimal("2.00"),
        "output_price_per_million": Decimal("8.00"),
        "cached_input_price": None,
        "pricing_source": "https://example.com/pricing",
        "valid_from": "2026-01-01T00:00:00.000Z",
        "valid_to": None,
        "created_at": "2026-10-28T00:00:00.000Z",
    }
    return PricingVersion(**{**base, **overrides})


def test_basic_cost() -> None:
    event = make_event(input_tokens=1_000_000, output_tokens=500_000)

    result = compute_cost(event, make_pricing())

    assert result.estimated_cost == Decimal("6.00")
    assert result.reported_cost is None
    assert result.currency == "USD"
    assert result.pricing_version_id == "pv1"
    assert result.cost_basis == "estimated"
    assert result.reason is None


def test_cached_tokens_not_double_counted() -> None:
    event = make_event(input_tokens=1_000_000, cached_tokens=400_000, output_tokens=0)
    pricing = make_pricing(
        input_price_per_million=Decimal("2.00"), cached_input_price=Decimal("0.50")
    )

    result = compute_cost(event, pricing)

    assert result.estimated_cost == Decimal("1.40")
    assert result.cost_basis == "estimated"


def test_reasoning_tokens_not_added_twice() -> None:
    event = make_event(input_tokens=0, output_tokens=1000, reasoning_tokens=600)
    pricing = make_pricing(output_price_per_million=Decimal("10"))

    result = compute_cost(event, pricing)

    assert result.estimated_cost == Decimal("0.01")


def test_unknown_pricing_is_null_not_zero() -> None:
    event = make_event(input_tokens=100, output_tokens=20)

    result = compute_cost(event, None)

    assert result.estimated_cost is None
    assert result.estimated_cost != 0
    assert result.cost_basis == "unavailable"
    assert result.reason == "no_pricing"
    assert result.pricing_version_id is None
    assert result.currency is None


@pytest.mark.parametrize("missing", ["input_tokens", "output_tokens"])
def test_unknown_tokens_is_null(missing: str) -> None:
    tokens: dict[str, Any] = {"input_tokens": 100, "output_tokens": 20, missing: None}
    event = make_event(**tokens)

    result = compute_cost(event, make_pricing())

    assert result.estimated_cost is None
    assert result.cost_basis == "unavailable"
    assert result.reason == "usage_unavailable"


def test_cached_unknown_bills_full_input() -> None:
    event = make_event(input_tokens=1_000_000, cached_tokens=None, output_tokens=0)

    result = compute_cost(event, make_pricing(input_price_per_million=Decimal("2")))

    assert result.estimated_cost == Decimal("2.00")
    assert result.cost_basis == "estimated"


def test_cached_exceeds_input_is_inconsistent() -> None:
    event = make_event(input_tokens=100, cached_tokens=200, output_tokens=10)

    result = compute_cost(event, make_pricing())

    assert result.estimated_cost is None
    assert result.cost_basis == "unavailable"
    assert result.reason == "inconsistent_usage"


def test_reported_cost_kept_alongside_estimate() -> None:
    event = make_event(
        input_tokens=1_000_000,
        output_tokens=500_000,
        metadata={"reported_cost": 0.5, "reported_currency": "USD"},
    )

    result = compute_cost(event, make_pricing())

    assert result.reported_cost == Decimal("0.5")
    assert result.cost_basis == "reported"
    assert result.estimated_cost == Decimal("6.00")


@pytest.mark.parametrize("field", ["input_price_per_million", "output_price_per_million"])
def test_null_price_entry_is_no_pricing(field: str) -> None:
    event = make_event(input_tokens=100, output_tokens=20)

    result = compute_cost(event, make_pricing(**{field: None}))

    assert result.estimated_cost is None
    assert result.cost_basis == "unavailable"
    assert result.reason == "no_pricing"


def test_cost_rounded_to_10dp() -> None:
    event = make_event(input_tokens=1, output_tokens=0)
    pricing = make_pricing(input_price_per_million=Decimal("0.123456789012"))

    result = compute_cost(event, pricing)

    assert result.estimated_cost == Decimal("0.0000001235")
