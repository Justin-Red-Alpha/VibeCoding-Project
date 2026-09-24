# Auth — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. None are applied; this is a
> backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | §4.5 Law 2 at the boundary | CSRF defence relies on browser behaviour (SameSite + Origin) rather than a typed token on `t_form` | a per-session CSRF token checked by one dependency, if the app ever leaves localhost | explicit, testable defence independent of browser version |
| 2 | §5 deduce | `product_count` is recomputed per admin page view | fine: it's deduced, not stored. Keep | — |
