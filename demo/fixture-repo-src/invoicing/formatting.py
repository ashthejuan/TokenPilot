"""Human-readable formatting for invoice amounts.

Formatting is deliberately kept separate from calculation: every
function here takes integer cents (or an ``InvoiceTotals``) and
returns a string. Nothing in this module changes a value.
"""

from __future__ import annotations

from decimal import Decimal

from invoicing.totals import InvoiceTotals, LineItem


def format_cents(cents: int) -> str:
    """Format integer cents as a dollar string.

    >>> format_cents(0)
    '$0.00'
    >>> format_cents(5)
    '$0.05'
    >>> format_cents(123456)
    '$1,234.56'
    >>> format_cents(-250)
    '-$2.50'
    """
    sign = "-" if cents < 0 else ""
    absolute = abs(cents)
    dollars, remainder = divmod(absolute, 100)
    return f"{sign}${dollars:,}.{remainder:02d}"


def format_percent(percent: int | float | str | Decimal) -> str:
    """Format a percentage value without trailing noise.

    >>> format_percent(10)
    '10%'
    >>> format_percent("8.25")
    '8.25%'
    """
    value = percent if isinstance(percent, Decimal) else Decimal(str(percent))
    text = format(value.normalize(), "f") if value == value.to_integral() else str(value)
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return f"{text}%"


def format_line_item(line_item: LineItem) -> str:
    """Format one ``(description, unit_price_cents, quantity)`` item.

    >>> format_line_item(("Widget", 500, 2))
    'Widget x2 @ $5.00 = $10.00'
    """
    description, unit_price_cents, quantity = line_item
    line_total = unit_price_cents * quantity
    return (
        f"{description} x{quantity} @ {format_cents(unit_price_cents)}"
        f" = {format_cents(line_total)}"
    )


def format_invoice(totals: InvoiceTotals) -> str:
    """Format broken-down invoice totals as a small receipt block.

    The lines always appear in calculation order: subtotal,
    discount, discounted subtotal, tax, levy, then the total.
    """
    lines = [
        f"Subtotal: {format_cents(totals.subtotal_cents)}",
        f"Discount: -{format_cents(totals.discount_amount_cents)}",
        f"Discounted subtotal: {format_cents(totals.discounted_subtotal_cents)}",
        f"Tax: {format_cents(totals.percentage_tax_cents)}",
        f"Levy: {format_cents(totals.levy_cents)}",
        f"Total: {format_cents(totals.total_cents)}",
    ]
    return "\n".join(lines)
