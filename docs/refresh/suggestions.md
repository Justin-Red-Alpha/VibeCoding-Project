# Refresh — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. None are applied; this is a
> backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | §6.5 status tracks spec | four composition rules and no test | `tests/test_refresh.py` (see STATUS) | the sole writer of price history is pinned |

Swept and clean:
- **§3:** `refresh_product` and `refresh_all` are the same loop over different
  source sets. That's two morphisms over one object, with no parallel object.
