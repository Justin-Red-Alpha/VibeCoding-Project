# Refresh — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built. Batches take turns, the admin button reuses the scheduled job, "refresh
my prices" runs in the background, and a listing deleted mid-fetch no longer
stops a batch (all tested since the 2026-09-24 code review). Rules 1 and 3 still
have no direct test.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| `refresh_source` / `refresh_product` / `refresh_all` | ✅ built | rules 1 and 3 untested |
| batch turn-taking, deleted-source tolerance | ✅ built | `test_review_refreshes_take_turns` |
| scheduler, "run now" without a second copy | ✅ built | every 6 h by default |

## Needs work
1. Add `tests/test_refresh.py`: stub `fetch_price` (a success, a `ScrapeError`,
   and an unexpected exception) and check against a temp DB that each attempt
   writes exactly one snapshot, stores the quoted currency and pins the product
   currency once.

## Coherence
No law fails.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
