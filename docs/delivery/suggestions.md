# Delivery — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. None are applied; this is a
> backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | §4.2 placement / Law 6 | `build_image` runs at two sites, so the smoke-tested image and the deployed one are two builds of one recipe | pin the base image by digest (`python:3.14-slim-bookworm@sha256:…`), or deploy the CI-built image if Vercel accepts a prebuilt one | "tested = deployed" byte for byte, not just recipe for recipe |
| 2 | §4.3 composition | per-instance state (the login throttle, the archive cooldown) isn't shared between Vercel instances | keep both in Postgres (a `throttle` table; a cooldown row in `settings`) | the throttle and the archive back-off hold across instances |
| 3 | §6.1 model first | preview deploys are out of scope, since they'd share production's database | Neon branching per preview, with its own `DATABASE_URL` | safe previews of pull requests |
| 4 | §5 define boundaries once | the suite list is repeated three times (two jobs in `ci.yml`, plus CLAUDE.md) | one `tests/run_all.py` that CI and people call | a new suite can't be left out of CI |

Swept and clean:
- **§3:** the hosted database is not a new data object. It's storage's `Dat` at a
  second `Loc`, so there's no "hosted tables" twin.
- **Secrets:** only names appear in docs and the workflow. Values live in Vercel
  and GitHub.
