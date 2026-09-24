# Discovery — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
🟡 Partial. The mechanism is built and fast (7.8 s for three shops, measured
2026-09-24), but only Amazon and Lazada actually return results.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| concurrent site search + streaming | ✅ built | 30.0 s → 7.8 s |
| block detection | ✅ built | eBay is reported as refused in ~1 s |
| matching / scoring / outliers | ✅ built | |
| web-search fallback (DuckDuckGo) | ✅ built | throttles after ~15–20 queries |
| Amazon site search | ✅ built | ~48 cards |
| Lazada site search | 🟡 partial | intermittent: sometimes 0 after repeated searches |
| eBay site search | 🟡 partial | blocked by eBay; now reported honestly |
| Shopee / Qoo10 site search | ⬜ unbuilt | no `search_path`/`search_card`; shown as "not searched" |
| keyed providers | ⬜ unbuilt | none exist in code |

## Needs work
1. eBay through the Browse API instead of scraping its search page.
2. Lazada: a retry with backoff, or a documented limit.
3. Shopee/Qoo10 search selectors, or accept them as not searched.

## Coherence
No law fails. Law 4 is mediated by `t_queue`.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- Spec: `openspec/specs/shop-search/spec.md`
- History: `openspec/changes/archive/2026-09-24-faster-shop-search/`
