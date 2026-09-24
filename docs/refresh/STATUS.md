# Refresh — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built, but 🟡 **untested**: none of its four composition rules has an offline
test.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| `refresh_source` / `refresh_product` / `refresh_all` | ✅ built | untested |
| scheduler | ✅ built | every 6 h by default |

## Needs work
1. Add `tests/test_refresh.py`: stub `fetch_price` (a success, a `ScrapeError`,
   and an unexpected exception) and check against a temp DB that each attempt
   writes exactly one snapshot, stores the quoted currency and pins the product
   currency once.

## Coherence
No law fails.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
