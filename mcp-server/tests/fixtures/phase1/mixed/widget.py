# fixtures/phase1/mixed/widget.py
"""total_price: sum of price*qty across line items.

Happy path is correct (spec-checker passes). Intentional review surface:
- Important (backlog-able): no validation of negative/zero qty or price.
- Suggested: `li` is a terse loop name; `total_price` mixes float money.
- Strength: single clear function, easy to test.
"""


def total_price(items):
    t = 0
    for li in items:
        t += li["price"] * li["qty"]
    return t
