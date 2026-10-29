"""Tests for totals, tax and formatting (all expected to pass)."""

import pytest

from invoicing.formatting import format_cents, format_invoice, format_percent
from invoicing.tax import FLAT_LEVY_CENTS, compute_tax, compute_total_tax
from invoicing.totals import (
    compute_totals,
    invoice_total,
    subtotal_for_line_items,
    total_for_line_items,
)


def test_no_discount_no_tax_still_adds_levy():
    totals = compute_totals(10_000, 0, 0)
    assert totals.discount_amount_cents == 0
    assert totals.discounted_subtotal_cents == 10_000
    assert totals.percentage_tax_cents == 0
    assert totals.levy_cents == FLAT_LEVY_CENTS
    assert totals.total_cents == 10_000 + FLAT_LEVY_CENTS


def test_tax_only_charged_on_full_subtotal_without_discount():
    totals = compute_totals(10_000, 0, 10)
    assert totals.percentage_tax_cents == 1000
    assert totals.total_cents == 10_000 + 1000 + FLAT_LEVY_CENTS


def test_totals_discount_before_tax_reference_calculation():
    # Reference pipeline in totals.py: $100 - 20% = $80,
    # 10% tax on $80 = $8, plus the $12 flat levy = $100 total.
    totals = compute_totals(10_000, 20, 10)
    assert totals.discount_amount_cents == 2000
    assert totals.discounted_subtotal_cents == 8000
    assert totals.percentage_tax_cents == 800
    assert totals.total_cents == 10_000


def test_invoice_total_matches_compute_totals():
    assert invoice_total(25_000, 10, 8) == compute_totals(25_000, 10, 8).total_cents


def test_compute_tax_percentage_only():
    assert compute_tax(10_000, 10) == 1000
    assert compute_tax(8_000, 10) == 800
    assert compute_tax(0, 10) == 0
    assert compute_tax(10_000, 0) == 0


def test_compute_total_tax_includes_flat_levy_in_full():
    assert compute_total_tax(10_000, 10) == 1000 + FLAT_LEVY_CENTS
    assert compute_total_tax(0, 10) == FLAT_LEVY_CENTS


def test_subtotal_for_line_items():
    items = [("Widget", 500, 2), ("Gadget", 250, 4), ("Cable", 100, 1)]
    assert subtotal_for_line_items(items) == 2100
    assert subtotal_for_line_items([]) == 0


def test_total_for_line_items():
    totals = total_for_line_items([("Widget", 500, 2)], 0, 10)
    assert totals.subtotal_cents == 1000
    assert totals.percentage_tax_cents == 100
    assert totals.total_cents == 1000 + 100 + FLAT_LEVY_CENTS


def test_negative_subtotal_rejected():
    with pytest.raises(ValueError):
        compute_totals(-1, 0, 0)


def test_format_cents():
    assert format_cents(0) == "$0.00"
    assert format_cents(5) == "$0.05"
    assert format_cents(100) == "$1.00"
    assert format_cents(123_456) == "$1,234.56"
    assert format_cents(-250) == "-$2.50"


def test_format_percent():
    assert format_percent(10) == "10%"
    assert format_percent("8.25") == "8.25%"
    assert format_percent(0) == "0%"


def test_format_invoice_lists_total():
    rendered = format_invoice(compute_totals(10_000, 0, 10))
    assert "Subtotal: $100.00" in rendered
    assert "Total: $122.00" in rendered
