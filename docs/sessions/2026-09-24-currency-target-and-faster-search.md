# 2026-09-24 — currency target and faster search

## 0. Continuation brief

Current state: two OpenSpec changes were built, verified live and **archived**.
Both are committed as `b821d90` on branch `session/2026-09-24-currency-and-search-speed`,
which is **not merged to `main` and not pushed**.

1. `target-price-currency`: a target price now carries a user-chosen currency, and
   the target is converted into the price history's currency before the verdict.
   The currency rules Codex added in `9a3fc71` are now pinned by tests.
2. `faster-shop-search`: discovery went from **30.0 s to 7.8 s**. It also fixed a
   crash that killed every search under `uvicorn --reload` on Windows, and stopped
   Shopee/Qoo10 spinning "searching…" forever.

gbrain is now set up: local-only, keyword search. All 4 test suites pass
(232 checks). The dev server is **still running** with `--reload` on port 8000.

Next step: merge the session branch into `main` (and push, if the user wants), then
pick up the docs-tree scaffold (P2), which drift checking still has nothing to
verify without.

Resume command/check: `git log --oneline -3 main session/2026-09-24-currency-and-search-speed`,
then `git checkout main && git merge --ff-only session/2026-09-24-currency-and-search-speed`.

---

## 1. Work completed

In order:

1. **Reviewed Codex commit `9a3fc71`** (currency fixes). Probed its logic offline,
   and it held up. `.codex/` (`e137385`) is Codex's own skill install; the user said
   to leave it alone.
2. **`target-price-currency`**, OpenSpec change now in
   `openspec/changes/archive/2026-09-24-target-price-currency/`.
   - `products.target_currency` column. It's an additive `ALTER TABLE` in
     `database._add_missing_columns`, run after `SCHEMA`. NULL keeps the legacy
     meaning.
   - `analysis.target_in(amount, currency, into, convert)`: a pure function with the
     converter injected.
   - `main._product_view` restates the target in `history_currency`.
     `main._chart_points` was extracted from `product_detail`.
   - `_target_price_field.html`: an amount plus a currency `<select>`, included in
     `index.html` and `discover.html`. It defaults to the current display currency.
   - `main._target_currency()` validates against `fx.DISPLAY_CURRENCIES` and returns
     400 otherwise.
   - `tests/test_currency.py`: 89 checks.
3. **gbrain set up** (last session's P1). Both bun directories were appended to the
   user PATH, then `gbrain init --pglite --no-embedding --non-interactive`, then
   yesterday's log was indexed.
4. **Found the "slow shops" report was mostly a crash.** I had relaunched the server
   with `--reload`, and every search then died with `NotImplementedError`. The page
   left spinners running, so it looked slow.
5. **`faster-shop-search`**, OpenSpec change now in
   `openspec/changes/archive/2026-09-24-faster-shop-search/`.
   - New `app/browser.py`: `run()`, `chromium()`, `new_page()` and
     `BrowserUnavailable`. It's the only place Chromium starts.
   - `site_search` was rewritten to use the async API: `looks_blocked`,
     `_gather_shops`, `_stream` (a queue bridge to a sync generator) and
     `ShopRefused`.
   - `scraper._render_with_playwright` goes through `browser.run`.
   - `main.discover_stream`: `ThreadPoolExecutor(3)` for missing prices, and
     `BrowserUnavailable` becomes an error event.
   - `discover.html`: `stopPending()`. Unsearchable shops are marked up front, and
     progress counts only the searchable ones.
   - `tests/test_shop_search.py`: 32 checks.
6. Archived both changes, which merged 3 capability specs into `openspec/specs/`.
   Refreshed the code graph, committed, and wrote this log.

---

## 2. Decisions

| Decision | Verdict | Why |
| --- | --- | --- |
| Store the target's currency in `products.currency` | **discarded** | That column is the ranking pin. An MYR target would re-pin an SGD product and drop every SGD listing from as-quoted ranking |
| New nullable `products.target_currency`, NULL = legacy meaning | **kept** | No backfill needed. Old rows behave exactly as before |
| Backfill `target_currency` from `products.currency` | discarded | The primary currency is NULL until the first fetch succeeds, so a backfill would miss rows and add a second code path |
| Target dropdown default | **display currency, else "Shop's currency"** | The user types the number they're reading off the page |
| Unknown target currency code | **400** | Silently storing it would leave a target that looks applied but can never be compared |
| Put the new tests in `test_extraction.py` | discarded | New suites instead: `test_currency.py` and `test_shop_search.py`, which need DB and browser fixtures |
| Pin 9a3fc71's behaviour **before** changing code | **kept** | The tests passed on unmodified code, so any later failure is a regression, not a Codex bug |
| gbrain embeddings / `think` via an API key | **discarded (for now)** | Matches the graphify "nothing leaves the machine" stance. Search is keyword-only |
| gbrain ambient memory writeback | **not enabled; user never answered** | The supercharge law says gbrain indexes `docs/sessions/` and never authors, and writeback would create a second record. Recommended declining |
| gbrain self-upgrade 0.52.2 → 0.54.1 | not done | Not asked |
| Fix `--reload` with `asyncio.set_event_loop_policy(Proactor)` | discarded | Global state, deprecated in 3.14 and removed in 3.16, and it only works if it runs after uvicorn's setup |
| Document "don't use `--reload`" | discarded | The docs already say to use it. The code must not depend on how it's launched |
| Playwright **async** API on an explicit `ProactorEventLoop` (`browser.run`) | **kept** | Proven by a probe under the forced Selector policy: the sync API fails, the async + explicit loop works |
| One thread plus sync Playwright per shop | discarded | Three Chromium processes, and it still needs the loop fix |
| One Chromium per search, a context per shop, `asyncio.gather` | **kept** | 8.3 s → 3.25 s for the search phase in the probe |
| Block detection = `readyState complete` with no cards | discarded | JS-rendered results can arrive after `load`, so it would misreport slow shops as blocked |
| Block detection = no cards and (bot wall or < 20 KB) | **kept** | eBay's error page is 1.8 KB and real results pages are over 1.3 MB: a ~700× margin |
| Abort image/font/media requests | **kept** | Amazon's page load went from 9.6 s to 1.3 s, with the same 48 and 40 cards and Lazada's sale price intact |
| Also abort CSS | discarded | Small gain, real risk to `innerText` and layout-dependent price nodes |
| Concurrent missing-price lookups | **kept, max 3** | About a person opening three tabs |
| Make `refresh_product` / `refresh_all` concurrent | **discarded** | Their 1.5 s gap between shops is a deliberate politeness rule |
| Warm Chromium at server startup | **not done; user accepted as-is** | The first search after a start is ~15 s, later ones ~8 s. Open item P3 |
| Commit directly on `main` | discarded | The harness rule is to branch off the default branch. The user can fast-forward |

---

## 3. Tests, checks, benchmarks

| Check | Result | What it proved |
| --- | --- | --- |
| `python -m tests.test_extraction` | 63 OK | Unchanged behaviour, including the ported `_render_with_playwright` |
| `python -m tests.test_search` | 48 OK | Unchanged |
| `python -m tests.test_currency` | **89 OK** (new) | Currency ranking, history and chart rules, target conversion, DB upgrade (v2 and v1), forms, product page |
| `python -m tests.test_shop_search` | **32 OK** (new) | Loop fix under a forced Selector policy, image blocking, block detection, completion order, error isolation, concurrent price events, and a real-browser check that no spinner is left |
| Mutation: `target_in` ignores the currency | 10 checks FAIL, including a false `BUY_NOW` | The target tests are not vacuous |
| Live search, baseline (fresh server) | **30.0 s**: Amazon 9.6, Lazada 12.3, eBay 21.5, 4 prices one at a time | Sequential waiting dominated |
| Live search, after (fresh server) | 15.0 s: eBay 8.3, Amazon 9.5, Lazada 10.6 | ~7 s of Chromium cold start on the first launch |
| Live search, after (warm) | **7.8 s**: eBay 0.9, Amazon 2.5, Lazada 3.3, prices done 7.8 | The target of < 15 s is met when warm |
| Live search in a browser under `--reload` | 8.5 s, 0 `NotImplementedError` | The crash is fixed. All 5 sections end in a final state |
| Lazada product page vs its search card | SGD 311.00 = 311.00, 407.00 = 407.00 (`lazada-css+browser`, ~4.7 s) | Invariant 2 holds with images blocked |
| Phone layout at 390 px | an overflow was found and fixed (`.target-field { min-width: 0 }`) | The dropdown had widened the grid column |
| `openspec validate --specs --strict` | 3/3 pass | Merged specs are valid (14 requirements, 35 scenarios) |
| `gbrain doctor --fast` | 90/100, 2 warnings (MCP serve not running) | The brain is healthy for CLI capture |

Scratch probes (`speed_probe.py`, `phase_probe.py`, `loop_probe.py`,
`sse_timing.py`) were in the session scratchpad and are disposable. `sse_timing.py`
is worth recreating for future timing work: it streams `/discover/stream` and
prints a timestamp for each event.

---

## 4. Live handoff state

| Type | Handle / location | State | Inspect / resume | Stop / cleanup |
| --- | --- | --- | --- | --- |
| branch | `session/2026-09-24-currency-and-search-speed` | clean, `b821d90` + this log, **not merged, not pushed** | `git log --oneline -3` | `git checkout main && git merge --ff-only session/2026-09-24-currency-and-search-speed` |
| remote | `origin` = github.com/Justin-Red-Alpha/VibeCoding-Project | `main` not pushed since `e137385` | `git status -sb` | push only when the user asks |
| process | uvicorn `--reload`: reloader pid 17496, worker pid 8756 | **running** (a harness background task, so it may not survive the session) | `Get-NetTCPConnection -LocalPort 8000 -State Listen` | `Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| ? CommandLine -like '*uvicorn*app.main*' \| % { Stop-Process -Id $_.ProcessId -Force }` |
| port | `127.0.0.1:8000` | serving (HTTP 200) | `curl -s -o NUL -w "%{http_code}" http://127.0.0.1:8000/` | as above |
| process | Playwright Chromium | none running | `Get-Process chrome \| ? Path -like '*ms-playwright*'` | n/a |
| data | `data/app.db` (git-ignored) | **migrated**: `products.target_currency` added at startup; 0 tracked products | `.venv\Scripts\python.exe -c "import sqlite3;print([r[1] for r in sqlite3.connect('data/app.db').execute('PRAGMA table_info(products)')])"` | safe to delete; recreated on boot |
| config | user PATH | now includes `%APPDATA%\npm\node_modules\bun\bin` and `%USERPROFILE%\.bun\bin` (7 original entries kept) | `[Environment]::GetEnvironmentVariable('Path','User')` | shells opened before the change (including VS Code) need a restart |
| data | gbrain brain `~/.gbrain/brain.pglite` | PGLite, `embedding_disabled: true`, 1 page (2026-09-23 log) + this log once captured | `gbrain stats` | `gbrain delete <slug>` |
| artifact | `graphify-out/` (git-ignored) | rebuilt: 728 nodes, 1,355 edges, 50 communities | `ls graphify-out/graph.json` | rebuild, never hand-edit |
| secret | LLM keys | `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `VOYAGE_API_KEY`, `GEMINI_API_KEY`, `GOOGLE_API_KEY` all **absent** | — | — |

**To restart the app** (`--reload` is now safe):
```powershell
cd "C:\Users\Justin\GitHub Repos\VibeCoding Project"
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload   # http://127.0.0.1:8000
```

**gbrain in an old shell:** prepend the PATH first:
`export PATH="/c/Users/Justin/AppData/Roaming/npm/node_modules/bun/bin:/c/Users/Justin/.bun/bin:$PATH"`.

**graphify:** the `graphify.exe` shim is still broken. Use
`"$APPDATA/uv/tools/graphifyy/Scripts/python.exe" -m graphify update .`

---

## 5. In-flight changes (from OpenSpec)

| Change | Tasks | Status | Next ready artifact |
| --- | --- | --- | --- |
| none | — | — | — |

`openspec list --json` → `{"changes": []}`. Archived this session:
`2026-09-24-target-price-currency` (14/14) and `2026-09-24-faster-shop-search`
(15/15, with task 3.4 added during apply). Specs now in `openspec/specs/`:
`target-price`, `currency-comparison` and `shop-search`.

---

## 6. Open items

| Priority | Item | Doc/code reference | Next action | Done when |
| --- | --- | --- | --- | --- |
| P1 | Session branch not merged or pushed | `session/2026-09-24-currency-and-search-speed` | Ask the user, then `git checkout main && git merge --ff-only …` (+ `git push` if wanted) | `main` contains `b821d90` |
| P2 | No `docs/` tree, so drift check verifies 0 rows | `~/.claude/skills/supercharge/references/docs-tree.md` | Scaffold `docs/<component>/ARCHITECTURE.md` + `IMPLEMENTATION.md` + `STATUS.md`. Components: discovery, extraction, storage, analysis, fx, ui/stream, browser | `drift-check.sh` reports N > 0 refs, 0 dead |
| P2 | Keyed search providers never tested | `app/search/providers.py` | Try SerpAPI, Brave or the eBay Browse API with a key | A keyed search returns candidates |
| P3 | First search after a server start takes ~15 s (Chromium cold start) | `app/browser.py`, `main.lifespan` | Warm Chromium in a daemon thread at startup (launch + close) | First search after a restart < 10 s |
| P3 | gbrain ambient writeback decision pending | `gbrain config set memory.auto_writeback …` | Ask the user. The recommendation is to decline (see §2) | Answered and recorded |
| P3 | gbrain 0.54.1 available | `gbrain self-upgrade` | Upgrade if the user wants | `gbrain --version` = 0.54.x |
| P3 | eBay site search blocked (now reported clearly) | `app/adapters.py` EBAY | Use the eBay Browse API instead of scraping search | eBay returns results |
| P3 | Shopee and Qoo10 have no site search | `app/adapters.py` | Add `search_path`/`search_card` selectors, or accept them as not searched | Shown with results, or documented as won't-do |
| P3 | Lazada site search intermittent | `app/search/site_search.py` | Retry with backoff, or document the limit | Consistent results, or a documented limit |
| P3 | `graphify.exe` shim broken on Windows | uv tool install | Report upstream. Workaround in §4 | `graphify update .` works directly |
| P3 | Converted history uses today's rate | `app/analysis.py` `best_price_series` | Store the rate at snapshot time if it matters | Series reflects each day's rate |
| P3 | No way to edit a target after creating it | `app/templates/product.html` | Add an edit form (amount + currency) | Target editable on the product page |
| P3 | Target placeholder truncated at 390 px ("Target price (optior") | `_target_price_field.html` | Shorter placeholder on narrow screens | Readable at 390 px |

Closed this session: **P1 gbrain unusable** (last log). `gbrain doctor` reports a
configured PGLite brain.

---

## 7. Architecture / model changes

There's still no formal `docs/` model (P2). The deltas below are in FRAMEWORK
terms, so that scaffold can absorb them.

- **Dat**
  - `products.target_currency`: ISO code or NULL, where NULL means the product's
    primary currency.
  - SSE event order is now completion order; the payloads are unchanged.
- **Trn**
  - `analysis.target_in(amount, currency, into, convert) → float | None`. Partial:
    None on a missing amount or currency, or when no rate exists.
  - `main._chart_points(snaps, shown_in, primary, convert)`.
  - `main._target_currency(target, choice)`, which rejects unknown codes.
  - `site_search.looks_blocked(html, cards)`, `_gather_shops(pairs, run_one, emit)`
    and `_stream(job)`.
  - `browser.run(coro)`, `browser.chromium()` and `browser.new_page(browser)`.
- **Loc**
  - One headless Chromium per search, shared across shops. Before, shops were
    searched one after another.
  - A daemon thread `shop-search` that owns that search's event loop.
  - A `ThreadPoolExecutor(3)` for price lookups, each with its own loop when it
    renders.
  - The server's own event loop is no longer involved in Playwright.
- **Trm**: unchanged. Still HTTP to shops, SSE to the browser, and the FX API.

Coherence notes:
- Conversion stays a **display-time** morphism. The target is restated at compare
  time and never stored converted (invariants 1 and 5).
- The block detector only fires on a **positive** signal, so a slow shop is never
  reported as blocked and a block is never reported as "no results" (invariant 3).
- Rendering no longer depends on process-global state (the event-loop policy).

---

## 8. Docs reconciled

| Doc | Change |
| --- | --- |
| `CLAUDE.md` | Data model (`target_currency`). Invariant 5 rewritten for the target currency. `browser.py` note under Pipeline. New traps: `--reload` + sync API, and "a stuck spinner is a bug". eBay and Shopee rows. Discovery section (concurrency, skipped resources, `looks_blocked`, timings). Running section with 2 new suites and test-fixture notes |
| `README.md` | Target-currency paragraph (§5). Site-search section (concurrency, table rows). Timings (~8 s, cold-start note). Tests section (2 new suites) |
| `openspec/specs/{target-price,currency-comparison,shop-search}/spec.md` | Created by archive: 14 requirements, 35 scenarios |
| `openspec/changes/archive/2026-09-24-*` | Proposal, design, tasks and spec deltas for both changes, with live results recorded on the tasks |
| `~/.claude/projects/.../memory/vibecoding-env-quirks.md` | gbrain PATH quirk, local-only choice, `session` page type not valid |
| `docs/sessions/2026-09-24-currency-target-and-faster-search.md` | This log |

---

## 9. Drift check

`bash ~/.claude/skills/supercharge/scripts/drift-check.sh` → **`0 dead / 0 refs`**
(exit 0). As last session, that is not a pass: with no `docs/` tree there is
nothing to check. Recorded as open item **P2**.

---

## 10. Files changed

**Committed in `b821d90`** (branch `session/2026-09-24-currency-and-search-speed`):
- New: `app/browser.py`, `app/templates/_target_price_field.html`,
  `tests/test_currency.py`, `tests/test_shop_search.py`, `openspec/specs/*`,
  `openspec/changes/archive/2026-09-24-*`
- Modified: `app/analysis.py`, `app/database.py`, `app/main.py`, `app/scraper.py`,
  `app/search/site_search.py`, `app/static/style.css`, `app/templates/discover.html`,
  `app/templates/index.html`, `app/templates/product.html`, `CLAUDE.md`, `README.md`

**Committed separately:** this log.

**Outside the repo:** user PATH (2 entries), `~/.gbrain/` (new brain), the memory
file above.
