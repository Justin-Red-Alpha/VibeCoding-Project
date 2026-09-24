# Browser — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. None are applied; this is a
> backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | §5 one source of truth | "Only `browser` starts Chromium" is enforced by nothing | a test that fails if `playwright.sync_api` is imported anywhere under `app/` | stops the `--reload` bug from coming back via a new call site |

Swept and clean:
- **§5 YAGNI:** four real call sites justify the seam.
