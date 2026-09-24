# Storage — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built. The only gap is that the success ⊕ failure rule is enforced by
convention in its one writer, not by the schema.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| `Product`, `Source`, `PriceSnapshot`, `Setting`, `FxRate` | ✅ built | |
| `target_currency?` | ✅ built | added 2026-09-24, additive column |
| `origin?`, `origin_ref?`, `history_checked_at?`, `history_note?` | ✅ built | added 2026-09-24 for archived history (additive) |
| `currency?` write-once | ✅ built | no direct test |
| v1 → v2 migration | ✅ built | tested via the upgrade test |
| historical FX rate per snapshot | ⬜ unbuilt | converted history uses today's rate (documented limit) |

## Needs work
1. If a second writer of snapshots ever appears, add a `CHECK ((price IS NULL) <> (error IS NULL))`
   constraint rather than relying on `refresh_source`.

## Coherence
No law fails. Law 6 holds by construction (a connection per call).

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- In flight: none · Reviews: reviews/ · Notes: general/
