# Storage — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built. Since 2026-09-25 it's a port with two adapters: the SQLite file
(default) and Postgres (`DATABASE_URL`, for Neon), with every suite passing on
both. The only gap is that the success ⊕ failure rule is enforced by convention
in its writers, not by the schema.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| `Product`, `Source`, `PriceSnapshot`, `Setting`, `FxRate` | ✅ built | |
| `target_currency?` | ✅ built | added 2026-09-24, additive column |
| `origin?`, `origin_ref?`, `history_checked_at?`, `history_note?` | ✅ built | added 2026-09-24 for archived history (additive) |
| `currency?` write-once | ✅ built | no direct test |
| v1 → v2 migration | ✅ built | tested via the upgrade test |
| historical FX rate per snapshot | ⬜ unbuilt | converted history uses today's rate (documented limit) |
| the port: `Backend`, both adapters, `Row`, `write_transaction`, `translate`, `ping` | ✅ built | 2026-09-25. `tests/test_hosting.py` on both engines |
| Postgres schema (`{pk}`, `{username}`, `DOUBLE PRECISION`, `citext`) | ✅ built | local Postgres 17.11; Neon not yet exercised |
| moving `data/app.db` into Neon | ⬜ not planned | a design non-goal: the hosted site starts empty |

## Needs work
1. If a second writer of snapshots ever appears, add a `CHECK ((price IS NULL) <> (error IS NULL))`
   constraint rather than relying on `refresh_source`.

## Coherence
No law fails. Law 6 holds by construction (a connection per call or checkout).
Law 4 holds through the port: nothing outside `database` imports a driver.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- In flight: none · Reviews: reviews/ · Notes: general/
