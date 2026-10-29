"""A small invoicing library used as a benchmarking fixture.

All money is integer cents. The public calculation pipeline is:

1. take a percentage discount off the subtotal
   (``invoicing.discounts``),
2. charge percentage tax on the discounted subtotal and add
   the flat per-invoice levy in full (``invoicing.tax``),
3. combine the pieces with ``invoicing.totals`` and render
   them with ``invoicing.formatting``.
"""

from invoicing.discounts import (
    apply_discount,
    discount_amount,
    discounted_subtotal,
)
from invoicing.formatting import format_cents, format_invoice, format_percent
from invoicing.tax import FLAT_LEVY_CENTS, compute_tax, compute_total_tax
from invoicing.totals import InvoiceTotals, compute_totals, invoice_total

__all__ = [
    "FLAT_LEVY_CENTS",
    "InvoiceTotals",
    "apply_discount",
    "compute_tax",
    "compute_totals",
    "compute_total_tax",
    "discount_amount",
    "discounted_subtotal",
    "format_cents",
    "format_invoice",
    "format_percent",
    "invoice_total",
]
