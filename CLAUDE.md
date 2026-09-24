# Price Drop Decision Tracker — architecture notes

Orientation for anyone (human or Claude) picking this up cold. `README.md` is the
user-facing guide; this file is about **why the code is shaped this way**, and the
traps that will bite you if you "simplify" it.

**The same system as a checkable model lives in `docs/`.** It's the supercharge
docs tree, written in FRAMEWORK.md's Dat/Trn/Loc/Trm terms.

- `docs/architecture-map.md`: the whole-system map and the coherence checklist.
- `docs/<component>/ARCHITECTURE.md`: each component's intent. The components are
  discovery, extraction, browser, storage, analysis, fx, web and refresh.
- `docs/<component>/IMPLEMENTATION.md`: maps every object and morphism to a
  `file:symbol`.
- `docs/STATUS.md`: what's built and what isn't.
- `docs/sessions/`: handoff logs. Read the newest first.

When you change code, update the touched component's `IMPLEMENTATION.md` rows **in
the same change**, then run
`bash ~/.claude/skills/supercharge/scripts/drift-check.sh`. It fails on any
`file:symbol` that no longer resolves.

Local FastAPI app. Type a product name → search shops → price the matches → user
confirms which are the same item → track them → automatic BUY/WAIT verdict.

## Pipeline

```
discovery              extraction        storage         analysis        UI
search/site_search  →  scraper.py    →  database.py  →  analysis.py  →  templates/
 (per shop, browser)    (name a price)   (snapshots)     (compare +      (+ per-shop
search/providers                                          decide)         SSE stream)
 (web search fallback)        ↑                              ↑
        ↑                     └──── fx.py (convert at read time)
   search/matching.py
   (is this the same product?)
```

`browser.py` is the only place Chromium is started or a page opened. Both
`site_search` and `scraper._render_with_playwright` go through it. See the
`--reload` trap below.

Each stage is independently testable, and `tests/` mostly tests stages, not routes.

## Data model (SQLite, plain `sqlite3`, no ORM on purpose)

```
products    (id, name, target_price, target_currency, currency)
  └── sources        (id, product_id, retailer, url, price_selector)   -- same item, many shops
        └── price_snapshots (id, source_id, price, currency, strategy, fetched_at, error)
settings    (key, value)          -- display_currency lives here
fx_rates    (base, quote, rate, fetched_at)
```

One product has many **sources** (Amazon + Lazada + Shopee listings of one item).
Failed fetches are stored too, as a snapshot with `error` set and `price` NULL —
that's deliberate, it's how the UI explains *why* a shop shows no price.

## Invariants — break these and the app lies to the user

These each cost real debugging. Please don't undo them.

1. **Never store a converted price.** Snapshots keep the shop's own currency.
   Converting on write bakes today's rate into permanent history; tomorrow's rate
   move would silently rewrite what past prices "were". Convert only at
   compare/display time (`fx.make_converter` → `analysis.py`).

2. **Never show a list price as the price.** Lazada's server HTML carries
   `pdt_price`, which is the *crossed-out* price (read $589.00 on an item selling
   for $345.50). It is deliberately NOT in `EMBEDDED_PRICE_PATTERNS`. Lazada is
   `needs_js=True` and its real price comes from rendering
   `.pdp-v2-product-price-content-salePrice`. Inflating prices ~70% would invent
   savings that don't exist — the worst possible bug in a deal finder.

3. **A block must never look like an empty result.** Two detectors exist for this:
   `scraper.looks_like_bot_wall()` (shops disguise blocks as 404/503/200) and
   `providers._looks_throttled()` (DuckDuckGo answers a throttled client with
   HTTP 202 + an "anomaly" page). Without them the UI would claim "no products
   found" and send the user hunting for a CSS selector that can never work.

4. **Never rank different currencies by magnitude.** 4,000 PHP is not cheaper than
   95 SGD. Without a display currency, off-currency sources are shown but excluded
   from ranking (`off_currency`); with one, they're converted first. A currency
   with no available rate is shown but never declared cheapest. Prices with no
   recognized currency are also shown but excluded from ranking and history.

5. **A target price and its history must use the same currency.** The target is
   stored as typed, with the currency the user picked (`products.target_currency`).
   NULL means "Shop's currency", which is the product's primary currency (the first
   successful source with a known currency). Before the verdict, `analysis.target_in`
   restates the target in the history's currency: the display currency if one is
   selected, else the primary currency. If it can't be restated, show the target but
   don't apply it. Don't reuse `products.currency` for the target's currency. That
   column is the ranking pin, so storing an MYR target there would drop every SGD
   listing from as-quoted ranking. Reading a ringgit target as dollars produced a
   false `BUY NOW` (`tests/test_currency.py` pins it).

6. **Matching ranks, the user decides.** Accessories are capped at 0.30 (low
   confidence) because a $30 case next to $345 headphones fabricates a 91%
   "saving". Only high-confidence *and* priced candidates are pre-ticked. Nothing
   is tracked without a human tick.

7. **The headline "best price" may only come from plausible listings.** Ranking
   every result by price alone makes a cheaper *different* product the deal. Two
   real examples, both caught live: a WH-CH520 at SGD 17.69 headlined a search for
   WH-1000XM5 ("save 96%"), and an Amazon listing whose title matched perfectly but
   priced SGD 38.60 among SGD 270-440 listings headlined "save 91%". The summary
   therefore requires `score >= MIN_HEADLINE_SCORE` **and** `not price_suspect`.
   Such listings stay visible in their shop's list with the warning — they just
   can't set the headline. Saying "probably not the same item" and "best price
   found" about one listing is a contradiction.

8. **SQLite table rebuilds need both pragmas off.** See "Migration trap" below.

## Traps already hit (don't rediscover these)

**Migration / FK cascade.** `ALTER TABLE x RENAME TO x_v1` makes SQLite rewrite
*other tables'* foreign keys to follow the rename. With `ON DELETE CASCADE`, the
final `DROP TABLE x_v1` then cascades and deletes rows you just migrated. The v1→v2
migration therefore sets `PRAGMA foreign_keys = OFF` **and**
`PRAGMA legacy_alter_table = ON` for the rebuild. Also: migrate *before* applying
`SCHEMA`, since the new indexes reference columns a v1 DB doesn't have yet.

**Model-number matching.** Squash per *word*, never across the whole string.
Squashing globally turned "Sony WH-1000XM5" into one token `sonywh1000xm5`, which
then failed to match "Sony Singapore WH-1000XM5". See `matching.model_tokens`.

**Money parsing.** `Rp1.234.567` is 1234567, not 1.234567. `parse_price_number`
decides whether the last separator is a decimal point by counting trailing digits
(1–2 = decimal, otherwise grouping). Don't replace it with `float()`.

**SSE looks broken under TestClient.** `fastapi.testclient` buffers the stream, so
all events appear at once. The real HTTP path is genuinely progressive — verify
with `curl -N --no-buffer`, not TestClient.

**Windows console encoding.** Printing `₫`/`₱` etc. via the venv python crashes with
a cp1252 `UnicodeEncodeError`. Prefix test runs with `PYTHONIOENCODING=utf-8`.

**`--reload` + Playwright's sync API = every search dies (Windows).** With
`--reload`, uvicorn 0.30 sets the process-wide policy to the Selector event loop,
which cannot start subprocesses. The sync API builds its loop from that policy, so
launching Chromium raised `NotImplementedError`. The page then sat on "searching…",
which reads as slow rather than broken, and that is how it was reported. Always go
through `browser.run()`, which hands Playwright's **async** API an explicit
`ProactorEventLoop`. Don't reintroduce `playwright.sync_api` in app code, and don't
"fix" it with `set_event_loop_policy`: that API is deprecated in 3.14 and is global
state. (Test scripts outside the server can use the sync API.)

**A stuck spinner is a bug.** Any shop section left on "searching…" means an event
that will never come: a crash, a dropped stream, or a shop that isn't searched at
all (Shopee and Qoo10 used to spin forever). The page marks unsearchable shops up
front and `stopPending()` clears the rest on `done`, `error` and `onerror`.

## Per-shop reality (measured Sept 2026, not assumed)

Product pages and search pages behave *differently* per shop — test both.

| Shop | Search page | Product page |
|---|---|---|
| Amazon | works well in a browser (~48 cards) | often bot-blocked via plain HTTP, fine in a browser |
| Lazada | works, but **intermittent** — sometimes returns 0 after repeated searches | works with Playwright only (see invariant 2) |
| eBay | blocked: a **1.8 KB** "Error Page \| eBay" in 0.1 s, caught at once by `site_search.looks_blocked` (was a 9 s wait) | usually works |
| Shopee | no site-search support configured (page shows "not searched") | item API returns 403 |
| Qoo10 / schema.org sites | not configured | usually work |

Note the inversion on Amazon: its *search* renders happily in a browser even when
its *product* pages serve bot checks. Don't assume one implies the other.

Extraction strategies are tried in order and first number wins: Shopee API → user
selector → adapter selectors → JSON-LD → meta tags → embedded JSON (escaped or
not) → Playwright render.

## Discovery

Two providers, in order of preference:

**1. Per-shop site search** (`search/site_search.py`, default). Renders each shop's
own search page in Playwright and reads the result cards. This is the good path:

- no web-search dependency and no shared query budget
- result cards already carry prices, so a shop's whole result set costs **one**
  page render instead of one render per product
- all shops are searched **at once** (one Chromium, one context per shop,
  `asyncio.gather`), and each streams the moment it finishes
- pages skip images, fonts and media (`browser.SKIPPED_RESOURCES`). Amazon's load
  dropped from 9.6 s to 1.3 s, and Lazada still reads its sale price
- a search page with no cards that is a bot wall or **under 20 KB** is reported as
  refused straight away (`looks_blocked`). Real results pages are over 1 MB. A big
  page with no cards yet still gets the full wait, so a slow shop is never
  mistaken for a block

Measured for "Sony WH-1000XM5": **30.0 s → 7.8 s** (first search after server start
~15 s, because Chromium starts cold). Missing prices are fetched 3 at a time
(`PRICE_LOOKUP_CONCURRENCY`). Refresh deliberately stays sequential with a 1.5 s gap.

Selectors live on the adapter (`search_path`, `search_card`, `search_title`,
`search_price`, `search_link`). Amazon puts two `h2`s in a card (brand, then
product name) — take the `[data-cy="title-recipe"]` container so the brand is
included, or matching loses a token. Amazon also legitimately shows cards with
**no price**; those candidates are kept and their product page is fetched
afterwards, best matches first, within `DISCOVER_PRICE_LIMIT`.

**2. Web search** (`search/providers.py`, fallback when Playwright is missing).
DuckDuckGo's HTML endpoint. **Query budget is the binding constraint** — it
throttles after roughly 15–20 queries and stays throttled a while. Hence one broad
query per search, a 15-minute cache, and per-shop queries only as a last resort.

Both paths can be blocked, and both report it rather than returning an empty list.

## Conventions

- Adding a shop = one entry in `ADAPTERS` (`app/adapters.py`). Nothing else changes.
- Analysis takes a `to_display` **callable**, not an `fx` import, so tests stay
  offline and deterministic.
- Streaming keeps ranking/conversion/outlier logic **server-side**; the JS is a
  dumb renderer and uses `textContent` for shop text (never inject listing titles
  as HTML).
- Chart colours come from `--series-1..8` CSS vars, assigned in fixed order and
  never cycled; the table dot and chart line for a shop must match.

## Running

```powershell
.\.venv\Scripts\Activate.ps1
uvicorn app.main:app --reload                      # http://127.0.0.1:8000
python -m tests.test_extraction                    # extraction, comparison, decisions, FX
python -m tests.test_search                        # matching, URL filters, throttle detection
python -m tests.test_currency                      # ranking/chart/target currency rules, DB upgrade
python -m tests.test_shop_search                   # concurrency, block detection, --reload loop, page spinners
```

`test_currency` points `database.DB_PATH` at a temp file and drives routes with
`TestClient` *without* its context manager, so startup (FX download, scheduler)
never runs. It stubs `main.refresh_product`, because tracking a product would
otherwise fetch real shop pages.

Python 3.14 + Playwright/chromium are already installed in `.venv`.

## Open / known-incomplete

- Keyed search providers (SerpAPI, Brave, eBay Browse) are **not built**:
  `available_providers()` returns only DuckDuckGo. (This line used to say
  "scaffolded", which was never true.)
- `refresh` has no offline tests (see `docs/refresh/STATUS.md`).
- Converted history uses *today's* rate for all snapshots (fine within one
  currency; across currencies the series reflects today's rate, not each day's).
- FX figures are mid-market — they exclude shipping, card FX fees and import duty.
- No auth, no rate limiting on routes; it's a localhost-only personal tool.
