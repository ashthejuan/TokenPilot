# Invoicing fixture

A small, dependency-free invoicing library. It exists as a
benchmarking fixture: it contains one known bug that an agent
is asked to fix, with a test suite that proves the fix.

All money is integer cents. Percentages are plain numbers
(`20` means 20%).

## Layout

| File | Contents |
| --- | --- |
| `invoicing/tax.py` | Percentage tax plus a flat per-invoice levy |
| `invoicing/discounts.py` | Percentage discounts and the final-total helper |
| `invoicing/totals.py` | Reference invoice calculation (`compute_totals`) |
| `invoicing/formatting.py` | Dollar/percent/receipt formatting |
| `tests/test_totals.py` | Totals, tax and formatting tests |
| `tests/test_discounts.py` | Discount tests, including the known failure |

## Running the tests

```bash
python -m pytest -q
```

No installation step is needed: the package is importable from
the repository root.

## Calculation order

An invoice total is worked out in this order:

1. Take the percentage discount off the subtotal.
2. Charge percentage tax on the *discounted* subtotal.
3. Add the flat per-invoice levy (`FLAT_LEVY_CENTS`, $12.00)
   in full.

The levy is not part of the price of the goods, so a discount
must never reduce it. `invoicing.totals.compute_totals`
implements this order and is the reference calculation;
`invoicing.discounts.apply_discount` must agree with it.

## Known bug

`apply_discount` currently works the tax out on the full
subtotal, adds tax and the levy, and only then takes the
percentage discount. The discount therefore also reduces the
tax and the levy, and the final total comes out too low.

`tests/test_discounts.py::test_discount_applied_before_tax`
pins the correct behaviour ($100.00 subtotal, 20% discount,
10% tax -> $100.00 total) and fails until the order is fixed.
Every other test passes. Fix the calculation; do not change
the tests.
