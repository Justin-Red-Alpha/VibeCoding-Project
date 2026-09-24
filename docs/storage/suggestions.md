# Storage — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. Each one cites its rule and names
> the concrete change. None are applied; this is a backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | §2 sum types | `PriceSnapshot` success ⊕ failure is held only by convention | `CHECK ((price IS NULL) <> (error IS NULL))` on `price_snapshots` (a rebuild, so follow invariant 8) | a second writer can't create a row that is neither or both |

Swept and clean:
- **§5 deduce-don't-store:** `products.currency` is a stored copy, but it's
  justified and has a mechanism (write-once).
- **§3 consolidation:** no junction tables, and no parallel objects.
