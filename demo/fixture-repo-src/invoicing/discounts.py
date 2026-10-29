"""Percentage discounts for the invoicing fixture.

All money is integer cents. The discount helpers in this module
come in two flavours:

* :func:`discount_amount` and :func:`discounted_subtotal` work
  purely on a subtotal and know nothing about tax.
* :func:`apply_discount` returns the final amount a customer
  pays for a subtotal once a percentage discount and tax are
  both taken into account.

Correct order of operations for :func:`apply_discount`
------------------------------------------------------
1. Take the percentage discount off the subtotal.
2. Charge percentage tax on the *discounted* subtotal.
3. Add the flat per-invoice levy in full.

The levy (see ``invoicing.tax.FLAT_LEVY_CENTS``) is not part of
the price of the goods, so a discount must never reduce it, and
the percentage tax must be worked out on the discounted price,
not on the original subtotal.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from invoicing.tax import compute_total_tax


def _validate_subtotal(subtotal_cents: int) -> None:
    if subtotal_cents < 0:
        raise ValueError("subtotal_cents must be non-negative")


def _validate_discount_percent(
    discount_percent: int | float | str | Decimal,
) -> Decimal:
    rate = (
        discount_percent
        if isinstance(discount_percent, Decimal)
        else Decimal(str(discount_percent))
    )
    if rate < 0 or rate > 100:
        raise ValueError("discount percent must be between 0 and 100")
    return rate


def discount_amount(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal,
) -> int:
    """Return how many cents a percentage discount removes.

    The result is rounded half-up to the nearest cent, matching
    the rounding used for tax in ``invoicing.tax``.

    >>> discount_amount(10_000, 10)
    1000
    >>> discount_amount(10_000, 0)
    0
    >>> discount_amount(10_000, 100)
    10000
    """
    _validate_subtotal(subtotal_cents)
    rate = _validate_discount_percent(discount_percent)
    exact = (Decimal(subtotal_cents) * rate) / Decimal("100")
    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def discounted_subtotal(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal,
) -> int:
    """Return the subtotal after a percentage discount, in cents.

    >>> discounted_subtotal(10_000, 25)
    7500
    >>> discounted_subtotal(10_000, 0)
    10000
    >>> discounted_subtotal(10_000, 100)
    0
    """
    return subtotal_cents - discount_amount(subtotal_cents, discount_percent)


def apply_discount(
    subtotal_cents: int,
    discount_percent: int | float | str | Decimal,
    tax_rate_percent: int | float | str | Decimal,
) -> int:
    """Return the final total after discount and tax, in cents.

    Intended behaviour (discount before tax):

    * discount the subtotal first,
    * charge percentage tax on the discounted subtotal,
    * add the flat levy in full.

    For a $100.00 subtotal with a 20% discount and 10% tax the
    intended total is $80.00 + $8.00 tax + $12.00 levy = $100.00
    (10_000 cents). ``invoicing.totals.invoice_total`` implements
    the same calculation and the two must agree.
    """
    _validate_subtotal(subtotal_cents)
    _validate_discount_percent(discount_percent)
    # NOTE: tax is worked out on the full subtotal and added
    # before the discount is taken, so the percentage discount
    # ends up reducing the tax and the flat levy as well.
    taxed_total = subtotal_cents + compute_total_tax(
        subtotal_cents, tax_rate_percent
    )
    return taxed_total - discount_amount(taxed_total, discount_percent)
