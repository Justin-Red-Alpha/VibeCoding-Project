# FX — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built. The rates are mid-market only. That's documented, not a defect.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| `convert`, `make_converter`, rate cache | ✅ built | |
| `refresh_rates` with fallback source | ✅ built | untested offline |

## Needs work
None.

## Coherence
No law fails.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
