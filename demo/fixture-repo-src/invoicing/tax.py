"""Sales-tax calculations for the invoicing fixture.

All money is integer cents. Percentages may be given as ``int``,
``float`` or ``Decimal``; internally they are converted to
``Decimal`` so results are deterministic and rounded half-up to
the nearest cent.

Tax model
---------
The amount a customer owes in tax has two parts:

* a percentage part, charged on the *taxable* amount passed to
  :func:`compute_tax`, and
* a flat per-invoice levy (:data:`FLAT_LEVY_CENTS`), charged in
  full on every invoice.

The levy is not a percentage of anything. It is therefore never
scaled by a discount: a discount reduces the price of the goods,
and the percentage tax is then charged on that reduced price,
but the flat levy is added afterwards in full. Discounting the
levy (for example by discounting a total that already includes
it) undercharges the customer.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

#: Flat per-invoice levy in cents ($12.00), added in full after
#: any discount and after the percentage tax has been worked out
#: on the discounted subtotal.
FLAT_LEVY_CENTS: int = 1200

#: Tax rate used when a caller does not supply one (10%).
DEFAULT_TAX_RATE_PERCENT: Decimal = Decimal("10")


def _to_decimal(value: int | float | str | Decimal) -> Decimal:
    """Convert a percentage value to ``Decimal`` via ``str``.

    Going through ``str`` avoids binary float artefacts such as
    ``Decimal(8.25)`` becoming ``8.250000000000000444...``.
    """
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _percent_of(amount_cents: int, percent: int | float | str | Decimal) -> int:
    """Return ``percent`` percent of ``amount_cents``, rounded half-up."""
    rate = _to_decimal(percent)
    exact = (Decimal(amount_cents) * rate) / Decimal("100")
    return int(exact.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _validate_amount(amount_cents: int) -> None:
    if amount_cents < 0:
        raise ValueError("amount_cents must be non-negative")


def _validate_rate(percent: int | float | str | Decimal) -> Decimal:
    rate = _to_decimal(percent)
    if rate < 0 or rate > 100:
        raise ValueError("tax rate percent must be between 0 and 100")
    return rate


def compute_tax(
    taxable_cents: int,
    tax_rate_percent: int | float | str | Decimal = DEFAULT_TAX_RATE_PERCENT,
) -> int:
    """Return the percentage tax on ``taxable_cents``, in cents.

    This is only the percentage part of the tax. It does not
    include the flat levy; use :func:`compute_total_tax` for the
    full amount added to an invoice.

    >>> compute_tax(10_000, 10)
    1000
    >>> compute_tax(8_000, 10)
    800
    >>> compute_tax(0, 10)
    0
    """
    _validate_amount(taxable_cents)
    _validate_rate(tax_rate_percent)
    return _percent_of(taxable_cents, tax_rate_percent)


def compute_total_tax(
    taxable_cents: int,
    tax_rate_percent: int | float | str | Decimal = DEFAULT_TAX_RATE_PERCENT,
) -> int:
    """Return percentage tax plus the flat levy, in cents.

    The levy is added in full regardless of ``taxable_cents``,
    including when the taxable amount is zero.

    >>> compute_total_tax(10_000, 10)
    2200
    >>> compute_total_tax(0, 10)
    1200
    """
    return compute_tax(taxable_cents, tax_rate_percent) + FLAT_LEVY_CENTS


def tax_breakdown(
    taxable_cents: int,
    tax_rate_percent: int | float | str | Decimal = DEFAULT_TAX_RATE_PERCENT,
) -> dict[str, int]:
    """Return the tax split as ``{"percentage_tax": ..., "levy": ...}``."""
    percentage_tax = compute_tax(taxable_cents, tax_rate_percent)
    return {"percentage_tax": percentage_tax, "levy": FLAT_LEVY_CENTS}
