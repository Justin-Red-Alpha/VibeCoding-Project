# Extraction — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. None are applied; this is a
> backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | §5 one source of truth | The strategy order in §5 lives only as the statement order inside `_extract` and `fetch_price` | Declare the chain as one ordered list of `(name, strategy)` that both functions walk | the order is part of the spec, so it deserves one visible declaration |

Swept and clean:
- **§3 consolidation:** `Adapter` already folds search into partial morphisms.
  `PriceResult` is a `DataLoc` of `PriceSnapshot`, not a twin.
