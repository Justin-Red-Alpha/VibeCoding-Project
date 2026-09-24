# FX — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. None are applied; this is a
> backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | §5 one source of truth | `DISPLAY_CURRENCIES` does double duty: the display picker *and* validation of target currencies (in `web`) | keep it, but name the dual role in its comment, or split it into `SUPPORTED_CURRENCIES` if the two ever diverge | a future edit to the picker won't silently change validation |

Swept and clean:
- **§5 deduce-don't-store:** cross rates are deduced, and only USD-based rows are
  stored.
