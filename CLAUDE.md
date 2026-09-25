# Price Drop Decision Tracker — architecture notes

Orientation for anyone (human or Claude) picking this up cold. `README.md` is the
user-facing guide; this file is about **why the code is shaped this way**, and the
traps that will bite you if you "simplify" it.

**The same system as a checkable model lives in `docs/`.** It's the supercharge
docs tree, written in FRAMEWORK.md's Dat/Trn/Loc/Trm terms.

- `docs/architecture-map.md`: the whole-system map and the coherence checklist.
- `docs/<component>/ARCHITECTURE.md`: each component's intent. The components are
  discovery, extraction, browser, storage, analysis, fx, web, refresh, history,
  auth, settings and delivery.
- `docs/<component>/IMPLEMENTATION.md`: maps every object and morphism to a
  `file:symbol`.
- `docs/STATUS.md`: what's built and what isn't.
- `docs/sessions/`: handoff logs. Read the newest first.

When you change code, update the touched component's `IMPLEMENTATION.md` rows **in
the same change**, then run
`bash scripts/drift-check.sh` (the vendored copy CI runs; identical to
`~/.claude/skills/supercharge/scripts/drift-check.sh` below its header). It fails
on any `file:symbol` that no longer resolves. New files must be tracked by git
(`git add -N` is enough) or their references count as dead.

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

## Data model (SQLite locally, Postgres when hosted; plain SQL, no ORM on purpose)

```
users       (id, username NOCASE UNIQUE, password_hash, role user|admin,
             display_currency, disabled_at)          -- first account = admin
  └── sessions       (token_hash, user_id, expires_at)  -- sha256 only; raw token in the cookie
products    (id, name, target_price, target_currency, currency,
             user_id → users ON DELETE CASCADE)       -- NULL = pre-accounts, claimed by 1st admin
  └── sources        (id, product_id, retailer, url, price_selector,
  │                   history_checked_at, history_note)                -- same item, many shops
        └── price_snapshots (id, source_id, price, currency, strategy, fetched_at, error,
                             origin, origin_ref)    -- origin NULL = live; 'wayback' = archived
settings    (key, value)          -- site settings (admin page): default currency, shops, intervals, pause
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
   **The same goes for the database:** an unreachable one raises
   `db.DatabaseUnavailable`, and every page answers with a 503 ("We couldn't load
   your data"), never "Nothing tracked yet". Don't catch it in a route.

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

9. **Archived prices are history, never the current price.** Rows with
   `price_snapshots.origin` set were read from an Internet Archive copy of the
   *same* listing (`app/history.py`). They feed `best_price_series` and the
   verdict, but `main._latest_per_source` skips them, so they can never become
   "cheapest right now". Archived pages are **never rendered**, and JS-priced
   shops are skipped, because the only number in Lazada's archived HTML is the
   list price (invariant 2).

10. **Every product or source route goes through `auth.product_for` / `source_for`.**
    Products belong to users (`products.user_id`). Another user's product is a
    **404**, exactly like a missing one, so ids can't be probed; admins may open
    any. Don't add a product route that reads `db.get_product` directly. Any
    redirect whose target comes from the request must go through `auth.local_path`
    (the old `/settings/currency` was an open redirect).

11. **The first account is the admin, and it claims unowned products.** Tests,
    scripts and live checks must never register on the owner's real
    `data/app.db`, or the admin slot is taken. Use `tests/helpers.py` (temp DB),
    or an isolated app instance with a temp `DB_PATH`. **Tests never touch the
    hosted database either:** every suite starts by dropping the whole schema, so
    `helpers.use_temp_db()` refuses a `TEST_DATABASE_URL` whose host isn't
    `localhost`/`127.0.0.1`, or that equals `DATABASE_URL`, before anything runs.
    On the hosted site, register the admin account straight after the first
    deploy.

## Hosted mode (Vercel + Neon)

Plan and reasons: `openspec/changes/ci-cd-and-vercel-hosting/design.md` (until
archived), then `docs/delivery/` and `docs/storage/`. It's a personal dev
deployment; no launch is planned.

- **One storage port, two adapters.** `db.get_connection()` returns SQLite
  (default, `DB_PATH`) or pooled Postgres when `DATABASE_URL` is set (Neon injects
  it). Nothing outside `app/database.py` imports `sqlite3` or `psycopg`: catch
  `db.IntegrityError` and `db.DatabaseUnavailable`, and read rows by name, index,
  `.keys()` or `dict(row)`.
- **Write SQL once, for both engines:**
  - placeholders are `?` (the adapter rewrites them to `%s`);
  - the schema's two dialect differences are the `{pk}` and `{username}` tokens
    in `SCHEMA` (`CITEXT` on Postgres keeps usernames case-insensitive);
  - money columns are `DOUBLE PRECISION` (trap below);
  - new ids come from `INSERT … RETURNING id`, never `lastrowid`;
  - every list query's `ORDER BY` ends with `id`, since Postgres doesn't break
    ties by insertion order;
  - write `NULLS FIRST`/`LAST` explicitly (the engines' defaults differ);
  - timestamps stay ISO-8601 text.
- **"Only if fewer than N" rules go through `db.write_transaction(conn)`**, the one
  exclusive-write primitive (`BEGIN IMMEDIATE` on SQLite; see the lock-first trap
  for Postgres).
- **Scheduling: `SCHEDULER_MODE = in-process ⊕ cron`.** Locally and in plain
  Docker, the 6-hour APScheduler job runs as before. On Vercel (`cron`) there's
  no interval job: Vercel Cron calls `GET /cron/daily` once a day with
  `Authorization: Bearer $CRON_SECRET`. The route is a 404 when the secret is
  unset, and does no work without the right secret. `scheduler.daily_run`
  re-checks the stalest listings until 150 s, then finishes unchecked archive
  lookups until 230 s (the request limit is 300 s). What it doesn't reach is
  picked up next time from stored state (stale listings,
  `history_checked_at IS NULL`), not a queue. The admin page shows "once a day,
  set by the host" and ignores a posted interval.
- **Behind the proxy:** the image runs uvicorn with `--proxy-headers`, so the
  cookie is `Secure` over https. `SameSitePostGuard` compares Origin/Referer with
  `x-forwarded-host` when present, else `host`.
- **Delivery:** `.github/workflows/ci.yml` runs the seven suites on Ubuntu and
  Windows, again on Postgres 17, the drift check, and a smoke test of
  `Containerfile.vercel` (the same file Vercel builds). Only then does a push to
  `main` deploy (`vercel deploy --prod`), and only if `VERCEL_TOKEN` exists
  (otherwise it's skipped with a notice). `vercel.json` turns Vercel's Git
  auto-deploy off, so nothing bypasses the gate.
- `GET /healthz` returns `{"app","database"}` with 200 or 503, and never the
  backend, host or URL.

## Traps already hit (don't rediscover these)

**The Internet Archive firewall-blocks clients that ignore HTTP 429,** for an hour,
doubling on repeat. It happened to this machine on 2026-09-24: research probes
plus one live lookup, and the first version of `history` carried on past a 429 on
a capture. `history` now keeps a 4 s gap, stops at the first 429 or refused
connection, and pauses all lookups for 15 or 60 minutes. Don't hand-probe
web.archive.org in loops; `tests/test_history.py` fakes it.

**A failed SQLite write must roll back before anything else writes.** Python's
`sqlite3` opens a transaction implicitly, and an INSERT that raises (for example,
a foreign-key refusal because the source was deleted mid-refresh) leaves it open
and holding the write lock. Every other write then waits 5 s and fails with
"database is locked". `add_snapshot` uses `with conn:` plus `close()` in `finally`
for this reason; do the same in any write that is *expected* to fail sometimes.

**Check-then-act races (found by the 2026-09-24 code review).** "Count the admins,
then demote" and "count the failures, then check the password" each let two
parallel requests both pass the check. The admin guard now counts and writes in
one `BEGIN IMMEDIATE` transaction (`db.guarded_user_change`). The sign-in throttle
counts guesses still in flight under a lock. Keep any new "only if fewer than N"
rule atomic in the same way.

**Admin settings store only what changed.** Writing every field on each save froze
env values and defaults into the DB, so a later env change silently did nothing.
Shops are stored as the ones switched *off*, so a shop added to `ADAPTERS` is
searched automatically. See `app/site_settings.py`'s docstring.

**`--reload` can orphan its worker on Windows.** When the reloader is killed, the
`multiprocessing` worker it spawned keeps the port and serves **stale code**. Port
8000 then shows as owned by a dead PID. Find the child with
`Get-CimInstance Win32_Process | ? ParentProcessId -eq <dead pid>` and stop it.

**`--reload` never reloads when started from an agent's background shell.**
uvicorn 0.30.6 on Windows restarts its worker by sending a Ctrl+C *console* event.
A background shell has no console, so the worker never receives it. The log shows
`Reloading...` and nothing after it: the reloader waits forever, and the old
worker keeps serving the code it started with. The code isn't at fault (the
2026-09-24 pre-fix commit behaved the same). After editing code, **stop and
restart** a server you started in the background, then check that a new
`Started server process` line appears. In a normal terminal, `--reload` works.

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

**Postgres `REAL` is 4 bytes.** It keeps about 7 significant digits, so IDR
1,234,567.89 would be stored rounded, with no error. That's why money is
`DOUBLE PRECISION` on both engines (SQLite reads it as its own 8-byte REAL).
`test_hosting.test_money_keeps_every_digit` pins it.

**Lock first, then count (Postgres).** `write_transaction` takes
`pg_advisory_xact_lock` as the transaction's *first* statement, under READ
COMMITTED (pinned in `_configure_pg`). Measured on 2026-09-25 with four racing
first sign-ups: without the lock, 2–4 admins per race; with the lock but
REPEATABLE READ, 3–4, because the snapshot is taken before the wait and the
count misses the other commit. Don't "upgrade" the isolation level, and don't
put a query before the lock.

**Concurrent cold starts collide on `CREATE TABLE IF NOT EXISTS`.** Two Vercel
instances starting together can make Postgres reject the second schema run.
`init_db` holds `pg_advisory_xact_lock(SCHEMA_LOCK)` for the whole schema.

**Pooled connections remember dropped types.** After `DROP SCHEMA public CASCADE`
(the test reset), psycopg's auto-prepared statements still name the old `citext`
type ("cache lookup failed for type …"). `helpers.empty_db()` closes the pool
after a reset. Only tests drop schemas.

**The image is 1.32 GB unpacked (~353 MB compressed).** It's Chromium's headless
shell only (`playwright install --only-shell`). Whether Vercel accepts it is
settled by the first deploy. Don't switch to the full Chromium build.

**Background threads may freeze on Vercel once a response is sent.** `run_once`
jobs (archive lookups, "refresh my prices") are best-effort there. The daily
cron run is the backstop, and it works *inside* its request. Don't move that work
into a thread.

**Behind Vercel's proxy, `host` may be an internal name.** Hence the
forwarded-host rule above. Which header Vercel actually fills is confirmed at the
first deploy; record the answer here.

**Vercel may quietly build the plain Python runtime instead of the container.**
Vercel's Container Images feature is a permissioned beta. Without it, a repo with
`Containerfile.vercel` still deploys, as a Python function with no Chromium. The
site works, but search fails with "Executable doesn't exist at
/home/sbx_user…/ms-playwright/…". Seen on the first deploy (`a237b69`). Check the
build log before debugging the app.

**The Vercel site is behind Vercel Authentication.** Every URL, the production
alias included, 302s to `vercel.com/sso-api`, so curl sees a redirect rather
than your app. Use the Protection Bypass for Automation secret
(`x-vercel-protection-bypass` header) or a signed-in browser.

**`/cron/daily` makes real requests.** Called against a database that holds
listings, it fetches real shop pages and asks the Internet Archive. On 2026-09-25
a local image smoke test ran it against the test Postgres with leftover fixtures,
and it hit amazon.com twice and the archive once. Empty the database first.

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
python -m tests.test_history                       # archived prices: matching, filters, back-off, live-only current
python -m tests.test_auth                          # accounts, sessions, ownership, admin page, cross-site guard
python -m tests.test_hosting                       # both engines, outage page, /healthz, cron + daily run, proxy
bash scripts/drift-check.sh                        # docs ↔ code (CI runs it too)
```

Against Postgres, like CI's `postgres` job (Docker Desktop must be running):

```powershell
docker run -d --name pt-pg -p 5433:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=test postgres:17
$env:TEST_DATABASE_URL = "postgresql://postgres:postgres@localhost:5433/test"   # then any suite
docker build -f Containerfile.vercel -t price-tracker . ; docker run --rm -p 8080:80 price-tracker
```

Route tests need `requirements-dev.txt` (httpx).

Every suite that touches the database goes through `tests/helpers.py`
(`use_temp_db`, `reset_db`, `empty_db`): a temp SQLite file, or the
`TEST_DATABASE_URL` Postgres. Route tests drive `TestClient` *without* its
context manager, so startup (FX download, scheduler) never runs.
`test_currency` stubs `main.refresh_product`, because tracking a product would
otherwise fetch real shop pages.

Python 3.14 + Playwright/chromium are already installed in `.venv`.

## Open / known-incomplete

- Keyed search providers (SerpAPI, Brave, eBay Browse) are **not built**:
  `available_providers()` returns only DuckDuckGo. (This line used to say
  "scaffolded", which was never true.)
- `refresh`: batch turn-taking and deleted-source tolerance are tested, but rules 1
  and 3 (every attempt recorded, quoted currency stored) aren't (see
  `docs/refresh/STATUS.md`).
- Converted history uses *today's* rate for all snapshots (fine within one
  currency; across currencies the series reflects today's rate, not each day's).
- FX figures are mid-market — they exclude shipping, card FX fees and import duty.
- **Auth is built for localhost and a personal dev deployment.** SameSite=Lax
  cookies plus an Origin/Referer guard stand in for per-form CSRF tokens, the
  login throttle is in memory (per Vercel instance), and there's no password
  change or reset. These stay on the to-do list, low priority, since no launch is
  planned. HTTPS is handled: behind Vercel's proxy the cookie is `Secure`.
- **Hosting isn't live yet (2026-09-25).** The code, image, workflow and
  `vercel.json` are built and pass locally on both engines. Still to do: the
  first CI run on GitHub, the owner's Vercel setup (Container Images,
  `CRON_SECRET`, `SCHEDULER_MODE=cron`, the three GitHub secrets), and the first
  deploy. Neon is installed. See `docs/delivery/STATUS.md`.
