# Browser — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built (2026-09-24). The known gap is Chromium's ~7 s cold start on the first
search after a server start.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| `run`, `chromium`, `new_page`, `skip_heavy` | ✅ built | fixed the `--reload` crash |
| startup warm-up | ⬜ unbuilt | the user accepted a ~15 s first search on 2026-09-24 |

## Needs work
1. Optional: in `main.lifespan`, launch and close Chromium once on a daemon
   thread, so the first search after a restart isn't the cold one.

## Coherence
Law 6 is now satisfied by construction. Before this component existed it failed
implicitly.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- History: `openspec/changes/archive/2026-09-24-faster-shop-search/`
