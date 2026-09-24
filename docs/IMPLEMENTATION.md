# System implementation map

> The whole-system functor architecture-map.md → code, deduced from the component
> IMPLEMENTATION.md files. System-level rows only. `drift-check.sh` verifies every
> `path:symbol` below and in each component map.

## Components → code root
| Component | Code root | Model | Code map |
| --- | --- | --- | --- |
| discovery | `app/search/` | [discovery/ARCHITECTURE.md](discovery/ARCHITECTURE.md) | [discovery/IMPLEMENTATION.md](discovery/IMPLEMENTATION.md) |
| extraction | `app/scraper.py`, `app/adapters.py` | [extraction/ARCHITECTURE.md](extraction/ARCHITECTURE.md) | [extraction/IMPLEMENTATION.md](extraction/IMPLEMENTATION.md) |
| browser | `app/browser.py` | [browser/ARCHITECTURE.md](browser/ARCHITECTURE.md) | [browser/IMPLEMENTATION.md](browser/IMPLEMENTATION.md) |
| storage | `app/database.py` | [storage/ARCHITECTURE.md](storage/ARCHITECTURE.md) | [storage/IMPLEMENTATION.md](storage/IMPLEMENTATION.md) |
| analysis | `app/analysis.py` | [analysis/ARCHITECTURE.md](analysis/ARCHITECTURE.md) | [analysis/IMPLEMENTATION.md](analysis/IMPLEMENTATION.md) |
| fx | `app/fx.py` | [fx/ARCHITECTURE.md](fx/ARCHITECTURE.md) | [fx/IMPLEMENTATION.md](fx/IMPLEMENTATION.md) |
| web | `app/main.py`, `app/templates/`, `app/static/` | [web/ARCHITECTURE.md](web/ARCHITECTURE.md) | [web/IMPLEMENTATION.md](web/IMPLEMENTATION.md) |
| refresh | `app/refresh.py`, `app/scheduler.py` | [refresh/ARCHITECTURE.md](refresh/ARCHITECTURE.md) | [refresh/IMPLEMENTATION.md](refresh/IMPLEMENTATION.md) |

## Shared objects (one Dat, DataLocs in ≥2 components)
| Object | Authoritative at | Also read by | Realised at |
| --- | --- | --- | --- |
| `Adapter` | extraction | discovery (search selectors), web (`discover_page` marks searchable shops) | `app/adapters.py:Adapter` |
| `PriceSnapshot` | storage (row) | extraction (RAM form `PriceResult`), refresh (writer), analysis (reader) | `app/database.py:add_snapshot` |
| `Candidate` | discovery | web (rows, summary, price lookups) | `app/search/base.py:Candidate` |
| supported currencies | fx | web (target validation, both pickers) | `app/fx.py:DISPLAY_CURRENCIES` |
| shop request headers | extraction | browser (user agent) | `app/scraper.py:BROWSER_HEADERS` |

## Inter-component transmissions / ports (Trm)
| Port | carries | c_from → c_to | Realising code |
| --- | --- | --- | --- |
| `outcome_stream` / `t_queue` | `ShopOutcome` | discovery → web | `app/search/site_search.py:_stream` |
| `price_lookup` / `t_future` | `PriceResult ⊕ ScrapeError` | extraction → web | `app/main.py:discover_stream` |
| `render_port` | `Html` | browser → extraction | `app/scraper.py:_render_with_playwright` |
| `search_port` | pages | browser → discovery | `app/search/site_search.py:search_all` |
| `to_display` port | `ℝ × Currency → ℝ?` | fx → analysis | `app/fx.py:make_converter` |
| `convert` port | `ℝ × Currency × Currency → ℝ?` | fx → analysis, web | `app/fx.py:convert` |
| `record` | `PriceSnapshot` | refresh → storage | `app/refresh.py:refresh_source` |
| `t_sse` | `SseEvent*` | web → user's browser | `app/main.py:_sse` |

## System entry points
| Entry | Trn triggered | Code |
| --- | --- | --- |
| HTTP `GET /` | `_product_view` per product | `app/main.py:dashboard` |
| HTTP `GET /product/{id}` | `_product_view`, `_chart_points` | `app/main.py:product_detail` |
| HTTP `GET /discover` | render shop sections | `app/main.py:discover_page` |
| HTTP `GET /discover/stream` | `search_all` → price lookups → summary | `app/main.py:discover_stream` |
| HTTP `POST /discover/track` | `add_product`, `add_source`, `refresh_product` | `app/main.py:track_from_discovery` |
| HTTP `POST /products` | `add_product`, `add_source`, `refresh_product` | `app/main.py:create_product` |
| HTTP `POST /settings/currency` | `set_setting`, `refresh_rates` | `app/main.py:set_display_currency` |
| scheduler (every 6 h) | `refresh_all` | `app/scheduler.py:start_scheduler` |
| startup | `init_db`, `refresh_rates`, scheduler | `app/main.py:lifespan` |

## Divergences (system-level)
- **Fixed 2026-09-24:** CLAUDE.md said keyed search providers were "scaffolded
  but unverified". No such code exists; they're `planned` in discovery.
- `ShopOutcome` and `SseEvent` are shared shapes with no single declaration
  (discovery suggestion #1, web suggestion #1).
