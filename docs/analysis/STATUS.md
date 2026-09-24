# Analysis — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built. The only open item is historical FX: converted history uses today's
rate.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| `compare_sources` + eligibility rules | ✅ built | pinned by `test_currency` since 2026-09-24 |
| `best_price_series`, `analyze` | ✅ built | |
| `target_in` | ✅ built | added 2026-09-24 |
| per-snapshot historical FX rate | ⬜ unbuilt | documented limit |

## Needs work
1. Only if cross-currency history matters: store the rate with each snapshot.
   Invariant 1 still holds, because the rate is stored, not the converted price.

## Coherence
No law fails. This component is the §7.1 degenerate case.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- Specs: `openspec/specs/currency-comparison/spec.md`, `openspec/specs/target-price/spec.md`
