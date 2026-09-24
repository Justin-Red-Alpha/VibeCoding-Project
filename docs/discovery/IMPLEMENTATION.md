# Discovery — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| `Candidate` | dataclass: title, url, retailer, provider, price?, currency?, score, flags, index, price_suspect | `app/search/base.py:Candidate` | built |
| `ShopOutcome` | tuple `(domain, retailer, Candidate*, error?)` | `app/search/site_search.py:_gather_shops` | built |
| card extraction script | JS run inside Chromium | `app/search/site_search.py:EXTRACT_JS` | built |
| block threshold | `20 000` chars | `app/search/site_search.py:BLOCKED_PAGE_MAX_CHARS` | built |
| `ShopRefused` | exception | `app/search/site_search.py:ShopRefused` | built |
| `SearchUnavailable` | exception (throttled or blocked) | `app/search/providers.py:SearchUnavailable` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `search_all` | `Query × Domain* → ShopOutcome*` | `app/search/site_search.py:search_all` | built |
| concurrent fan-out | `(Adapter × Domain)* → ShopOutcome*` | `app/search/site_search.py:_gather_shops` | built |
| `t_queue` (thread bridge) | `async job → sync stream` | `app/search/site_search.py:_stream` | built |
| `search_shop?` | `Page × Adapter × Domain × Query → Candidate*` | `app/search/site_search.py:search_shop` | built |
| rows → candidates | `Row* → Candidate*` | `app/search/site_search.py:_to_candidates` | built |
| `looks_blocked` | `Html × ℕ → 𝔹` | `app/search/site_search.py:looks_blocked` | built |
| searchable shops | `Domain* → (Adapter × Domain)*` | `app/search/site_search.py:shops_for` | built |
| browser present? | `() → 𝔹` | `app/search/site_search.py:playwright_available` | built |
| `score` | `Query × Title → ℝ × Flag*` | `app/search/matching.py:score_candidate` | built |
| model tokens | `𝕊 → Token*` | `app/search/matching.py:model_tokens` | built |
| `price_suspect` | `Candidate* → Candidate*` | `app/search/matching.py:flag_price_outliers` | built |
| `confidence` (deduced) | `Candidate → {high, medium, low}` | `app/search/base.py:Candidate::confidence` | built |
| `discover?` (fallback) | `Query → Candidate*` | `app/search/providers.py:discover` | built |
| throttle detection | `Html → 𝔹` | `app/search/providers.py:_looks_throttled` | built |
| configured domains | `() → Domain*` | `app/search/providers.py:search_domains` | built |
| keyed providers (SerpAPI, Brave, eBay Browse) | `Query → Candidate*` | none yet: would extend `available_providers` | planned |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. block ≠ empty (site search) | `app/search/site_search.py:ShopRefused` | `tests/test_shop_search.py:test_one_shop_failing` |
| 1. block ≠ empty (web search) | `app/search/providers.py:_looks_throttled` | `tests/test_search.py:test_throttle_detection` |
| 2. positive block signal only | `app/search/site_search.py:looks_blocked` | `tests/test_shop_search.py:test_looks_blocked` |
| 3. independence, completion order | `app/search/site_search.py:_gather_shops` | `tests/test_shop_search.py:test_shops_arrive_as_they_finish` |
| 3. browser failure surfaces | `app/search/site_search.py:_stream` | `tests/test_shop_search.py:test_browser_failure_surfaces` |
| 4. accessories capped at 0.30 | `app/search/matching.py:score_candidate` | `tests/test_search.py:test_scoring` |
| 4. outliers flagged | `app/search/matching.py:flag_price_outliers` | `tests/test_search.py:test_outliers` |
| 5. per-word model tokens | `app/search/matching.py:model_tokens` | `tests/test_search.py:test_model_tokens` |
| product URLs only | `app/adapters.py:Adapter::is_product_url` | `tests/test_search.py:test_product_url_filter` |

## Notes / divergences
- **Keyed providers are planned, not partial.** Before 2026-09-24, CLAUDE.md
  called them "scaffolded but unverified", but `available_providers` returns only
  `duckduckgo` and no keyed code exists. That line has been corrected.
- `ShopOutcome` is a plain tuple, with no named type. See suggestions.
