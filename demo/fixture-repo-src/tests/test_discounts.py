"""Tests for discount helpers and the final-total calculation."""

import pytest

from invoicing.discounts import (
    apply_discount,
    discount_amount,
    discounted_subtotal,
)
from invoicing.totals import invoice_total


def test_discount_amount_percentage():
    assert discount_amount(10_000, 10) == 1000
    assert discount_amount(10_000, 25) == 2500
    assert discount_amount(20_000, 50) == 10_000


def test_discount_amount_zero_percent():
    assert discount_amount(10_000, 0) == 0
    assert discounted_subtotal(10_000, 0) == 10_000


def test_discount_amount_hundred_percent():
    assert discount_amount(10_000, 100) == 10_000
    assert discounted_subtotal(10_000, 100) == 0


def test_discounted_subtotal_partial():
    assert discounted_subtotal(10_000, 20) == 8000
    assert discounted_subtotal(999, 0) == 999


def test_apply_discount_with_no_discount_matches_invoice_total():
    # With a 0% discount the order of operations cannot matter:
    # subtotal + percentage tax on it + flat levy in full.
    assert apply_discount(10_000, 0, 10) == invoice_total(10_000, 0, 10)
    assert apply_discount(10_000, 0, 10) == 12_200


def test_apply_discount_with_no_tax_and_no_discount():
    assert apply_discount(5_000, 0, 0) == invoice_total(5_000, 0, 0)


def test_discount_percent_out_of_range_rejected():
    with pytest.raises(ValueError):
        discount_amount(10_000, 101)
    with pytest.raises(ValueError):
        discounted_subtotal(10_000, -5)


def test_negative_subtotal_rejected():
    with pytest.raises(ValueError):
        discount_amount(-100, 10)


def test_discount_applied_before_tax():
    # Correct order: discount BEFORE tax.
    #   $100.00 subtotal, 20% discount -> $80.00
    #   10% tax on the discounted $80.00 -> $8.00
    #   flat $12.00 levy added in full -> $100.00 total
    # Discounting a total that already includes tax and the
    # levy would also discount the $8/$12 tax parts and give
    # $97.60 instead, so this test pins the order.
    assert apply_discount(10_000, 20, 10) == 10_000
    assert apply_discount(10_000, 20, 10) == invoice_total(10_000, 20, 10)
