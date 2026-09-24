# Whole-system categorical map (Dat/Trn/Loc/Trm)

> Top-level architecture doc (FRAMEWORK §4). It names the four atoms, lists the
> components (each linking to its ARCHITECTURE.md), reifies placement where it's a
> relation, and runs the §4.5 coherence checklist against the code. Detail lives in
> the linked component docs. Source of record: `app/main.py` (entry points),
> `app/database.py` (schema), `app/adapters.py` (shop knowledge).
>
> Method: `~/.claude/skills/supercharge/FRAMEWORK.md`. `CLAUDE.md` holds the eight
> invariants in prose; this tree is the same system as a checkable model.

## 1. Why
The app's worst failures have all been **lies**: a list price shown as the price,
a block shown as "no results", a ringgit target read as dollars, a spinner with no
event coming. Each one is a morphism defined where it shouldn't be, or a missing
transmission. As a category they become checkable rules (partial morphisms, sum
types, placement laws) instead of lessons to remember. The physical side (`Loc`)
matters here too: the `--reload` crash came from one transformation (rendering)
placed on four threads, with code that assumed only one.

## 2. The four atoms (at a glance)
**Dat**
| Object | Shape | Lives at |
| --- | --- | --- |
| `User` | username, password hash, `role ∈ {user, admin}`, display_currency?, disabled? | SQLite |
| `Session` | sha256(token) → user, expiry | SQLite (hash); raw token only in the browser cookie |
| `Product` | name, target_price?, target_currency?, currency?, `owner? → User` | SQLite |
| `Source` | one shop's listing of a product: url, retailer, price_selector? | SQLite |
| `PriceSnapshot` | success ⊕ failure: price?/currency?/strategy? or error; `origin?` marks an archived observation | SQLite. In RAM as `PriceResult` ⊕ `ScrapeError` (live) or `Observation` (archived) |
| `Adapter` | per-shop knowledge, with site search as partial morphisms | code (`ADAPTERS`) |
| `Candidate` | a search hit with its score, flags and price? | RAM (transient) |
| `FxRate`, `Setting` | USD-based rate cache; site settings (default currency, shops, refresh interval, limits, history pause) | SQLite |
| `Comparison`, `SourcePrice`, `Verdict`, series | **deduced** views, never stored | RAM, per request |
| `SseEvent*` | `(shop ⊕ price ⊕ note ⊕ error ⊕ done)*` | on the wire to the page |

**Trn** (owning component)
| Trn | t_from → t_to | Component |
| --- | --- | --- |
| `fetch_price` | `Url → PriceResult ⊕ ScrapeError` ⊸ | extraction |
| `search_all` | `Query → ShopOutcome*` ⊸ | discovery |
| `score_candidate` | `Query × Title → ℝ × Flag*` | discovery |
| `compare_sources` | `Source* × Latest → Comparison` | analysis |
| `best_price_series` → `analyze` | `PriceSnapshot* → ℝ* → Verdict` | analysis |
| `target_in` | `Target × Currency → ℝ?` | analysis |
| `convert` | `ℝ × Currency × Currency → ℝ?` | fx |
| `refresh_source` | `Source → PriceSnapshot` ⊸ | refresh |
| `backfill_source` | `Source → PriceSnapshot*` ⊸ (archived, background) | history |
| `run` / `chromium` / `new_page` | start and drive Chromium | browser |
| `discover_stream`, `_product_view` | request → events / view | web |

**Loc**
- `ServerProc`: the uvicorn process. Its sub-sites matter here: request workers,
  the `shop-search` thread with its own loop, the price-lookup pool of 3, and the
  scheduler thread.
- `Chromium`: a headless child process, one per search or render.
- `SQLite`: `data/app.db`.
- `UserBrowser`: the page.
- External: `Shop`s, `FxApi`, `DDG`, `Archive` (web.archive.org).

**Trm**
| Trm | carries | c_from → c_to |
| --- | --- | --- |
| `t_page`, `t_form` | HTML / form fields (cross-site POSTs refused) | ServerProc ⇄ UserBrowser |
| `t_cookie` | opaque session token (HttpOnly, SameSite=Lax) | UserBrowser → ServerProc |
| `t_sse` | `SseEvent*` | ServerProc → UserBrowser |
| `t_shop_http` | product-page HTML | Shop → ServerProc |
| `t_cdp` | commands, page HTML, card rows | ServerProc ⇄ Chromium |
| `t_render` | shop pages (minus images/fonts/media) | Shop → Chromium |
| `t_queue` | `ShopOutcome` | shop-search thread → request worker |
| `t_future` | `PriceResult ⊕ ScrapeError` | lookup pool → request worker |
| `t_sql` | rows | ServerProc ⇄ SQLite |
| `t_fx` | `{currency: rate}` | FxApi → ServerProc |
| `t_ddg` | search-result HTML | DDG → ServerProc (fallback only) |
| `t_archive` | capture index rows, raw archived HTML | Archive → ServerProc (scheduler thread; ≤ 15/min, stops on 429) |

## 3. Components
| Component | Owned `Trn` | Built/active when | Doc |
| --- | --- | --- | --- |
| `discovery` | search_all, search_shop, looks_blocked, score_candidate, discover | on a search | [discovery/ARCHITECTURE.md](discovery/ARCHITECTURE.md) |
| `extraction` | fetch_price, extract strategies, parse/detect, adapter_for | on any price fetch | [extraction/ARCHITECTURE.md](extraction/ARCHITECTURE.md) |
| `browser` | run, chromium, new_page | whenever a page is rendered | [browser/ARCHITECTURE.md](browser/ARCHITECTURE.md) |
| `storage` | CRUD, migrations, rate cache | always | [storage/ARCHITECTURE.md](storage/ARCHITECTURE.md) |
| `analysis` | compare_sources, best_price_series, analyze, target_in | on every view | [analysis/ARCHITECTURE.md](analysis/ARCHITECTURE.md) |
| `fx` | convert, make_converter, refresh_rates | when converting | [fx/ARCHITECTURE.md](fx/ARCHITECTURE.md) |
| `web` | routes, SSE stream, views, page JS | always | [web/ARCHITECTURE.md](web/ARCHITECTURE.md) |
| `refresh` | refresh_source/product/all, scheduler | on demand + every 6 h | [refresh/ARCHITECTURE.md](refresh/ARCHITECTURE.md) |
| `history` | archive_urls, wayback_lookup, filter_observations, backfill_source | after tracking a listing; on the button (unless paused) | [history/ARCHITECTURE.md](history/ARCHITECTURE.md) |
| `auth` | register, authenticate, sessions, require_user/admin, product_for, admin user actions | every request (public: search, login, register) | [auth/ARCHITECTURE.md](auth/ARCHITECTURE.md) |
| `settings` | effective site settings, validated setters, live reschedule | per search / refresh / admin save | [settings/ARCHITECTURE.md](settings/ARCHITECTURE.md) |

The pipeline, read left to right, is `discovery → extraction → storage →
analysis → web`, with `fx` plugged into `analysis` as an adapter for its
conversion port, and `browser` beneath discovery and extraction.

## 4. Placement (only where runsAt is a relation, §4.2)
| `Trn`/`Dat` | placements | why it matters |
| --- | --- | --- |
| `browser.run` (rendering) | shop-search thread · lookup pool · request workers · scheduler thread | it must not depend on any one thread's loop. The `--reload` crash was this law failing |
| `fetch_price` | lookup pool · request workers · scheduler thread | the same `Trn` at three sites. Each site gets its own loop via `run` |
| target-currency validation | `UserBrowser` (`<select>`) · `ServerProc` (`_target_currency`) | one validation placed twice (§7.2). The server copy is the authority |
| `score_candidate` | shop-search thread · request worker (web fallback) | pure, so it's safe anywhere |
| `PriceSnapshot` | RAM (`PriceResult`/`ScrapeError`, or `Observation`) · SQLite row | one `Dat`, with archived and live rows in the same object (§3). Two writers: `refresh_source` and `backfill_source` |
| `extract_from_html` | request/lookup threads (live) · scheduler thread (archived) | the same extraction for both, and neither renders |
| storage `Trn`s | every thread | a connection per call keeps this safe |

## 5. Coherence checklist (§4.5 / §8) against the implementation
- [x] 1. **Placement honesty.** Every view is built from rows delivered over
  `t_sql`. `EXTRACT_JS` runs inside Chromium, where the page lives. The page's JS
  only renders data delivered by `t_sse`.
- [~] 2. **Transmission well-typing.** Every `Trm` crosses a real boundary, but
  `t_sse`'s variants have no single declaration: they're built as ad-hoc dicts in
  `main.py` and parsed by hand in JS. Advisory: see [web/suggestions.md](web/suggestions.md) #1.
- [x] 3. **Placement totality.** Every placement has a thread or process and a
  component.
- [x] 4. **Dependency mediation.** Cross-thread handoffs go through `t_queue`
  (search) and `t_future` (lookups), and Chromium is reached only through `t_cdp`.
  Nothing reaches across directly.
- [x] 5. **Composition soundness.** This map and `docs/IMPLEMENTATION.md` /
  `docs/STATUS.md` are deduced from the component docs, not redescribed.
- [x] 6. **runsAt is a relation.** Rendering and `fetch_price` are explicitly
  multi-placed. `browser.run` exists so that no placement assumes another's
  setup. (This failed until 2026-09-24.)

## 6. Modeling smells swept (§3)
- **No parallel objects.** "Admin" is a `User` with `role = admin`, not an
  admins table (the §3 check in `auth/ARCHITECTURE.md`). Archived prices are
  `PriceSnapshot`s with `origin?`,
  not a history table (the §3 reduction in `history/ARCHITECTURE.md`). `Adapter`
  folds site search into partial morphisms.
  `PriceResult` is a `DataLoc` of `PriceSnapshot`, not a twin. `Candidate` vs
  `Source` was checked with the §3 reduction and kept apart, because they have
  different lifetimes and `Loc`s ([discovery/suggestions.md](discovery/suggestions.md) #3).
- **Deduced, not copied.** All analysis views are recomputed per request.
  `Product.currency` is the one stored copy of a deduced morphism, justified and
  kept consistent by being write-once.
- **One source of truth.** A single browser seam (`browser.py`) and a single shop
  registry (`ADAPTERS`). Open items: the SSE schema, and the dual role of
  `DISPLAY_CURRENCIES`.
