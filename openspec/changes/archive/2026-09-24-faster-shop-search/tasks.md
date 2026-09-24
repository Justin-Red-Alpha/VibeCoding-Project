# Tasks

## 1. Browser helper (fixes the --reload crash)

- [x] 1.1 Create `app/browser.py` with `run(coro)` (explicit Proactor loop on Windows via `asyncio.run(loop_factory=...)`), `new_page(browser)` (shop UA/locale/viewport, aborts image/font/media) and `BrowserUnavailable`; verify with a test in new `tests/test_shop_search.py` that, under a forced `WindowsSelectorEventLoopPolicy`, `run()` can spawn a subprocess and launch local Chromium on an in-memory page
- [x] 1.2 Port `scraper._render_with_playwright` to the async API through `browser.run` / `new_page`; verify `python -m tests.test_extraction` still passes (63 checks)

## 2. Concurrent shop search

- [x] 2.1 Add `site_search.looks_blocked(html, card_count)`; verify tests: 1.8 KB error page with 0 cards → True, bot-wall page → True, 1 MB page with 0 cards → False, small page with cards → False
- [x] 2.2 Port `search_shop` to async, checking `looks_blocked` right after DOMContentLoaded and returning a "refused the search" error instead of waiting; verify via test 2.1 plus live task 4.2 — live: eBay reported as refusing at DOMContentLoaded (0.9 s warm)
- [x] 2.3 Split orchestration into `_gather_shops(pairs, run_one, emit)` and rebuild `search_all` as a sync generator fed by a queue from a background thread, raising `BrowserUnavailable` if Chromium won't start; verify tests with a fake `run_one`: results arrive in completion order (fast shop first), one raising shop yields its error while others still yield results, and the generator ends cleanly

## 3. Stream and page

- [x] 3.1 Run missing-price lookups in `discover_stream` through `ThreadPoolExecutor(max_workers=3)` + `as_completed`; verify a TestClient test with stubbed `search_all`/`fetch_price` (4 lookups × 0.5 s) finishes in < 1.5 s, delivers all 4 `price` events, and a failing lookup yields an `error` on its row only
- [x] 3.2 Turn `BrowserUnavailable` into a `{"type": "error"}` event; verify a TestClient test with `search_all` stubbed to raise gets one error event and no crash
- [x] 3.3 In `discover.html`, make `onerror` (and the `error` message) replace any remaining "searching…" shop status with "not searched"; verify by rendering the page and checking the handler, and live in task 4.3

- [x] 3.4 (found during apply) Shops with no site-search support (Shopee, Qoo10) currently render "searching…" forever and inflate the "of N shops" count; render them as "not searched — no site search for this shop" and count only searchable shops; verify in a browser against the running server that after the stream finishes no section shows "searching…"

## 4. Live verification

- [x] 4.1 Run all suites (`test_extraction`, `test_search`, `test_currency`, `test_shop_search`) with `PYTHONIOENCODING=utf-8`; verify all pass — 63 + 48 + 89 + 32 = 232 checks pass
- [x] 4.2 Restart the server and time "Sony WH-1000XM5" with the SSE timing client; verify total < 15 s (baseline 30.0 s), Amazon and Lazada still return priced rows, and eBay is reported as refusing the search within ~3 s — measured: warm 7.8 s ✓ (eBay 0.9 s, Amazon 2.5 s, Lazada 3.3 s); first search after server start 15.0 s ✗ (Chromium cold start ~7 s; baseline 30.0 s was also a first search). Accepted as-is by the user on 2026-09-24 (startup warm-up not done; carried as an open item in the session log).
- [x] 4.3 Restart the server **with `--reload`** and repeat one search; verify results arrive (no `NotImplementedError` in the log) — live: search finished in 8.5 s in a real browser, 0 NotImplementedError in the log; every section ended in a final state (3.4 confirmed live)
- [x] 4.4 Fetch one Lazada product page through `fetch_price`; verify the price read equals the sale price on its search card, not a higher list price (invariant 2) — live: two listings, card SGD 311.00 → page SGD 311.00, card SGD 407.00 → page SGD 407.00 (lazada-css+browser, ~4.7 s each)

## 5. Reconcile

- [x] 5.1 Update `CLAUDE.md` (Windows `--reload` + sync-API trap, eBay error-page row, `browser.py` in the pipeline, test command) and `README.md` (timings, test command); verify by reading against the spec
- [x] 5.2 Run the supercharge drift check; record the result — result: `0 dead / 0 refs` (no docs/ tree yet)
