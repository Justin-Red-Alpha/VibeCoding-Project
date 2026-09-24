# Extraction — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built. Shopee's API strategy is 🟡 partial: the code is there, but the shop
answers with 403.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| `Adapter` + registry | ✅ built | adding a shop is one `ADAPTERS` entry |
| strategy chain (selector → JSON-LD → meta → embedded → render) | ✅ built | |
| Lazada sale price via render | ✅ built | verified live 2026-09-24, with images skipped |
| Shopee item API | 🟡 partial | 403 for non-app traffic |
| Amazon product pages over plain HTTP | 🟡 partial | often bot-walled. The render fallback usually recovers them |

## Needs work
1. Shopee: an official API, or accept it as a known gap. There's no in-code fix.

## Coherence
No law fails.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- In flight: none · Reviews: reviews/ · Notes: general/
