"""SQL fragments for summing costs from the `latest_costs` CTE (aliased `lc`).

Costs are summed as integers scaled by 1e10, the storage quantum, so sums are
exact. `cur` is set only for events that carry a cost, with '' for a cost that
has no currency. A group gets money only when all its costs share one known
currency (D11); otherwise both the amount and the currency are NULL.
"""

from decimal import Decimal

from tokenpilot.pricing.cost import quantize_money

__all__ = [
    "COST_CURRENCY",
    "GROUP_CURRENCY",
    "MIXED_CURRENCY",
    "SCALED_ESTIMATE",
    "SCALED_REPORTED",
    "group_money",
    "money_from_scaled",
]

_SCALE = Decimal(10_000_000_000)

SCALED_ESTIMATE = "CAST(ROUND(lc.estimated_cost * 10000000000) AS INTEGER)"
SCALED_REPORTED = "CAST(ROUND(lc.reported_cost * 10000000000) AS INTEGER)"
COST_CURRENCY = (
    "CASE WHEN lc.estimated_cost IS NOT NULL OR lc.reported_cost IS NOT NULL "
    "THEN COALESCE(lc.currency, '') END"
)

# MIN/MAX skip NULLs, so they agree exactly when every costed event shares one
# currency; with no costed event both are NULL and the CASE falls through.
_SINGLE_CURRENCY = "(MIN(cur) = MAX(cur) AND MIN(cur) <> '')"
GROUP_CURRENCY = f"CASE WHEN {_SINGLE_CURRENCY} THEN MAX(cur) END"
# True when costed events disagree on currency, or any costed event has none
# (cur = ''). All-unlabelled is mixed for coverage even though MIN=MAX=''.
MIXED_CURRENCY = "COALESCE(MIN(cur) <> MAX(cur) OR MIN(cur) = '', 0)"


def group_money(scaled_expression: str) -> str:
    """An aggregate: the scaled sum of `scaled_expression`, or NULL across currencies."""
    return f"CASE WHEN {_SINGLE_CURRENCY} THEN SUM({scaled_expression}) END"


def money_from_scaled(scaled: int | None) -> Decimal | None:
    return None if scaled is None else quantize_money(Decimal(scaled) / _SCALE)
