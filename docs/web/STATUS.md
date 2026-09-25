# Web — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built. The gaps are that a target can't be edited after creation, and that the
SSE event types aren't declared in one place.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| dashboard, product page, discovery page + stream | ✅ built | |
| target currency picker + validation | ✅ built | 2026-09-24 |
| concurrent missing-price lookups | ✅ built | 2026-09-24 |
| no-stuck-spinner page states | ✅ built | 2026-09-24 |
| outage page, `/healthz`, `/cron/daily`, forwarded-host guard | ✅ built | 2026-09-25, `tests/test_hosting.py`. Vercel's real headers are confirmed at the first deploy |
| edit target after creation | ⬜ unbuilt | there's no edit form |
| single `SseEvent` declaration | ⬜ unbuilt | advisory under Law 2 |

## Needs work
1. An edit form for the target amount and currency on the product page.
2. Declare the SSE event variants once (see suggestions #1).
3. Cosmetic: the target placeholder is truncated at a 390 px width.

## Coherence
Law 2 is **advisory** (untyped SSE variants). Everything else holds.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- Specs: `openspec/specs/target-price/spec.md`, `openspec/specs/shop-search/spec.md`
