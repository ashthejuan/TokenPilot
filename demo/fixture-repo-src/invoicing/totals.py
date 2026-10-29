"""Invoice totals: combine subtotal, discount and tax.

All money is integer cents. :func:`compute_totals` is the
reference calculation for an invoice:

1. Take the percentage discount off the subtotal.
2. Charge percentage tax on the *discounted* subtotal.
3. Add the flat per-invoice levy in full.

``invoicing.discounts.apply_discount`` is a convenience wrapper
around the same calculation for a single subtotal, and its
result must agree with :func:`invoice_total` here.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Iterable, Tuple

from invoicing.discounts import discount_amount, discounted_subtotal
from invoicing.tax import FLAT_LEVY_CENTS, compute_tax

# A line item is (description, unit_price_cents, quantity).
LineItem = Tuple[str, int, int]


@dataclass(frozen=True)
class InvoiceTotals:
    """Broken-down totals for one invoice, all in cents."""

    subtotal_cents: int
    discount_amount_cents: int
    discounted_subtotal_cents: int
    percentage_tax_cents: int
    levy_cents: int
    total_cents: int

    @property
    def tax_cents(self) -> int:
        """Total tax charged: percentage tax plus the flat levy."""
        return self.percentage_tax_cents + self.levy_cents


def _validate_inputs(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal,
    tax_rate_percent: int | float | str | Decimal,
) -> None:
    if subtotal_cents < 0:
        raise ValueError("subtotal_cents must be non-negative")
    for name, value in (
        ("discount_percent", discount_percent),
        ("tax_rate_percent", tax_rate_percent),
    ):
        rate = value if isinstance(value, Decimal) else Decimal(str(value))
        if rate < 0 or rate > 100:
            raise ValueError(f"{name} must be between 0 and 100")


def compute_totals(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal = 0,
    tax_rate_percent: int | float | str | Decimal = 0,
) -> InvoiceTotals:
    """Return the broken-down totals for ``subtotal_cents``.

    The discount is applied before tax: percentage tax is
    charged on the discounted subtotal, and the flat levy is
    added in full at the end.

    >>> totals = compute_totals(10_000, 20, 10)
    >>> totals.discounted_subtotal_cents
    8000
    >>> totals.percentage_tax_cents
    800
    >>> totals.total_cents
    10000
    """
    _validate_inputs(subtotal_cents, discount_percent, tax_rate_percent)
    discount = discount_amount(subtotal_cents, discount_percent)
    discounted = discounted_subtotal(subtotal_cents, discount_percent)
    percentage_tax = compute_tax(discounted, tax_rate_percent)
    total = discounted + percentage_tax + FLAT_LEVY_CENTS
    return InvoiceTotals(
        subtotal_cents=subtotal_cents,
        discount_amount_cents=discount,
        discounted_subtotal_cents=discounted,
        percentage_tax_cents=percentage_tax,
        levy_cents=FLAT_LEVY_CENTS,
        total_cents=total,
    )


def invoice_total(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal = 0,
    tax_rate_percent: int | float | str | Decimal = 0,
) -> int:
    """Return only the final total for ``subtotal_cents``, in cents."""
    return compute_totals(
        subtotal_cents, discount_percent, tax_rate_percent
    ).total_cents


def subtotal_for_line_items(line_items: Iterable[LineItem]) -> int:
    """Return the pre-discount subtotal for ``line_items``, in cents.

    Each item is ``(description, unit_price_cents, quantity)``.
    Quantities and unit prices must be non-negative.

    >>> subtotal_for_line_items([("Widget", 500, 2), ("Gadget", 250, 4)])
    2000
    """
    subtotal = 0
    for description, unit_price_cents, quantity in line_items:
        if unit_price_cents < 0:
            raise ValueError(f"unit price for {description!r} must be non-negative")
        if quantity < 0:
            raise ValueError(f"quantity for {description!r} must be non-negative")
        subtotal += unit_price_cents * quantity
    return subtotal


def total_for_line_items(
    line_items: Iterable[LineItem],
    discount_percent: int | float | str | Decimal = 0,
    tax_rate_percent: int | float | str | Decimal = 0,
) -> InvoiceTotals:
    """Return broken-down totals for a list of line items."""
    return compute_totals(
        subtotal_for_line_items(line_items), discount_percent, tax_rate_percent
    )
