# Extraction — implementation map

> The functor ARCHITECTURE.md → code. Each object and morphism maps to the
> file:symbol that realises it. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| `Adapter` | dataclass: name, domains, selectors, currency_by_domain, needs_js, search_* | `app/adapters.py:Adapter` | built |
| shop registry | `Adapter*` | `app/adapters.py:ADAPTERS` | built |
| unknown shop | `Adapter` | `app/adapters.py:GENERIC` | built |
| `PriceResult` | `{price, currency?, strategy}` | `app/scraper.py:PriceResult` | built |
| `ScrapeError` | exception with a readable reason | `app/scraper.py:ScrapeError` | built |
| browser headers | shared UA + headers | `app/scraper.py:BROWSER_HEADERS` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `adapter_for` | `Url → Adapter` | `app/adapters.py:adapter_for` | built |
| `retailer_label` | `Url → 𝕊` | `app/adapters.py:retailer_label` | built |
| `currency_for?` | `Adapter × host → Currency` | `app/adapters.py:Adapter::currency_for` | built |
| `supports_site_search` | `Adapter → 𝔹` | `app/adapters.py:Adapter::supports_site_search` | built |
| `search_url` | `Adapter × domain × query → Url` | `app/adapters.py:Adapter::search_url` | built |
| `is_product_url` | `Adapter × Url → 𝔹` | `app/adapters.py:Adapter::is_product_url` | built |
| `shopee_ids` | `Url → (shop, item)?` | `app/adapters.py:shopee_ids` | built |
| `fetch_price?` | `Url → PriceResult` ⊸ | `app/scraper.py:fetch_price` | built |
| `extract?` | `Html → PriceResult?` | `app/scraper.py:_extract` | built |
| never-render entry (archived HTML) | `Html × Url → PriceResult?` | `app/scraper.py:extract_from_html` | built |
| item id + canonical path | `Adapter × Url → Url?` | `app/adapters.py:item_id_re` | built |
| strategy: user selector | `Html → 𝕊?` | `app/scraper.py:_from_selector` | built |
| strategy: JSON-LD | `Html → (𝕊, Currency?)?` | `app/scraper.py:_from_json_ld` | built |
| strategy: meta tags | `Html → (𝕊, Currency?)?` | `app/scraper.py:_from_meta` | built |
| strategy: embedded JSON | `Html → 𝕊?` | `app/scraper.py:_from_embedded_json` | built |
| strategy: Shopee API | `Url → PriceResult` ⊸ | `app/scraper.py:_shopee_api` | partial |
| strategy: render | `Url → Html` ⊸ | `app/scraper.py:_render_with_playwright` | built |
| render body | `Url → Html` (async) | `app/scraper.py:_render` | built |
| `parse_price_number` | `𝕊 → ℝ` | `app/scraper.py:parse_price_number` | built |
| `detect_currency` | `𝕊 × Url → Currency?` | `app/scraper.py:detect_currency` | built |
| `looks_like_bot_wall` | `Html → 𝔹` | `app/scraper.py:looks_like_bot_wall` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. first number wins, fixed order | `app/scraper.py:_extract` | `tests/test_extraction.py:test_extraction` |
| 2. never a list price | `app/scraper.py:EMBEDDED_PRICE_PATTERNS` | `tests/test_extraction.py:test_extraction` |
| 3. a block is not "no price" | `app/scraper.py:looks_like_bot_wall` | `tests/test_extraction.py:test_bot_wall` |
| 4. money parsing | `app/scraper.py:parse_price_number` | `tests/test_extraction.py:test_numbers` |
| currency detection | `app/scraper.py:detect_currency` | `tests/test_extraction.py:test_currency` |
| Shopee ids from URL | `app/adapters.py:shopee_ids` | `tests/test_extraction.py:test_shopee_ids` |

## Notes / divergences
- The Shopee API strategy is **partial**. Its code path exists, but live traffic
  gets HTTP 403 (see CLAUDE.md, per-shop reality).
- Rule 2 is verified live, not offline: on 2026-09-24 two Lazada listings read
  their sale price (SGD 311.00 and 407.00) through the render path. The offline
  fixture tests the embedded-JSON path.
