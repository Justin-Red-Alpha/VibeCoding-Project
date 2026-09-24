# History — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
🟡 Partial. Wayback backfill is built and verified live for Amazon (9 prices for
the WH-1000XM5). It does nothing for Lazada and Shopee, by design, and BuyWhere
(the source that would cover them) is unbuilt.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| Wayback lookup, filters, backfill, scheduling | ✅ built | 2026-09-24 |
| politeness (4 s gap, stop on 429/refusal, pause) | ✅ built | added after this IP was blocked during verification |
| product page: note, button, archived marker | ✅ built | |
| Lazada / Shopee history | ⬜ unbuilt | archived copies carry only the list price; needs BuyWhere or similar |
| BuyWhere adapter | ⬜ unbuilt | its API was unreachable on 2026-09-24 |
| archived points marked on the chart | ⬜ unbuilt | shown in the table and note only |

## Needs work
1. Inspect the USD 88.00 (2025-12) capture once the archive unblocks this IP.
   If it's a wrong element, try Amazon's `#corePrice…` selectors first.
2. Retry BuyWhere registration; if its price-history endpoint returns real data,
   add it to `HISTORY_SOURCES`.

## Coherence
No law fails.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- Spec: `openspec/specs/price-history-backfill/spec.md`
- History: `openspec/changes/archive/2026-09-24-archived-price-history/`
