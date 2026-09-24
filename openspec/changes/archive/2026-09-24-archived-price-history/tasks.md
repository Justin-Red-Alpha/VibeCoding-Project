# Tasks

## 1. Data

- [x] 1.1 Add nullable `price_snapshots.origin`, `price_snapshots.origin_ref`, `sources.history_checked_at` and `sources.history_note` to `SCHEMA` and `_add_missing_columns`. Add `db.add_snapshot(..., fetched_at=?, origin=?, origin_ref=?)`, `db.get_origin_refs(source_id)` and `db.set_history_note(source_id, note)`. Verify in new `tests/test_history.py` (temp DB) that an old DB gains the columns with its rows intact, that an archived snapshot round-trips with its own `fetched_at`, and that `init_db` stays idempotent

## 2. Extraction entry point

- [x] 2.1 Add public `scraper.extract_from_html(html, url)`: the non-browser strategies only, never rendering. Verify that the Amazon fixture gives `(449.0, SGD)` and that a Lazada fixture carrying only `pdt_price` gives None (invariant 2)

## 3. History component

- [x] 3.1 Create `app/history.py` with the `HistoryResult` sum (`found` / `none` / `unavailable` / `unsupported`), `archive_urls(url, adapter)` and the `HISTORY_SOURCES` registry. Verify tests: an Amazon slug URL gives the stripped URL plus `https://www.amazon.<host>/dp/<ASIN>` on the same host; query strings are removed; non-Amazon gets the stripped URL only
- [x] 3.2 Implement `wayback_lookup(source, adapter, get=, sleep=)`: CDX per URL, one capture per month across all URLs, newest 24, raw `id_` fetch, `extract_from_html`, `needs_js` gives `unsupported`, a timeout or 5xx gives `unavailable`. Verify with fake `get`/`sleep` against fixture CDX JSON and archived HTML: month collapsing, the cap of 24, sleep called between requests, all four result variants
- [x] 3.3 Implement the filters (currency equal to the listing's; plausibility `[median/3, median×3]` when there are ≥ 3 values) and `backfill_source(source_id)` (dedup on `origin_ref`, store with `origin='wayback'`, write `history_note` with found/excluded counts and the date range). Verify tests: a foreign-currency capture is excluded and counted; a 1/10-median capture is excluded and counted; a second run adds nothing; the note text for each outcome
- [x] 3.4 Add `schedule_backfill(product_id)`: a one-off scheduler job `history-<id>` (`replace_existing`, `max_instances=1`) that loops over sources. Verify that calling it twice leaves one job, and the job calls `backfill_source` for each source (the scheduler isn't started in the test)

## 4. Web

- [x] 4.1 Make `_latest_per_source` ignore archived rows. Verify tests: a capture newer than the last live check doesn't become the current price; a listing with only archived prices has no current price but keeps them in `best_price_series`
- [x] 4.2 Call `schedule_backfill` after `track_from_discovery`, `create_product` and `create_source`, and add `POST /products/{id}/history` (re-run, then redirect). Verify with TestClient and a stubbed scheduler that each route schedules once, the page redirects, and no network call happens — refinement during apply: automatic triggers look up only listings never checked (`only_unchecked=True`), so adding a 2nd shop does not re-fetch the 1st one's copies; the button re-checks all
- [x] 4.3 On the product page: a per-source history note, a "Look for archived prices" button, and archived rows in "Raw snapshots" marked "archived" with a link to `origin_ref`. Verify that the rendered page for a product with one archived row shows the marker and the link, and the note
- [x] 4.4 Verdict: a product with 1 live check and 12 varying archived prices gets a trend verdict (not `NOT_ENOUGH_DATA`). Verify via `_product_view` in a temp DB

## 5. Live verification

- [x] 5.1 Run all suites (`test_extraction`, `test_search`, `test_currency`, `test_shop_search`, `test_history`) with `PYTHONIOENCODING=utf-8`; verify all pass — 63 + 48 + 89 + 32 + 77 = 309 checks pass
- [x] 5.2 Live, temp DB: backfill the amazon.com WH-1000XM5 URL (`/Sony-WH-1000XM5-Canceling-Headphones-Hands-Free/dp/B09XS7JWHH`). Verify that ≥ 10 archived USD prices are stored, that none are outside the plausibility band, and that the request spacing is ≥ 1 s. Record the counts and duration — **result: 9** archived USD prices (2025-05 → 2026-09), 26 requests, 134 s, all inside the band. "≥ 10" was an estimate: 24 copies were fetched and 9 had a readable price. Spacing was 2.07 s under the old 1 s rule. **During this run the archive rate-limited this IP** (connection refused), so the rule became 4 s + stop at the first 429/refusal + a process-wide pause (spec and design updated; covered offline by `test_rate_limit_backoff`). A suspicious USD 88.00 (2025-12) was kept and is recorded as an open item (the first Amazon selector is generic)
- [x] 5.3 Live: backfill a Lazada listing. Verify `unsupported`, zero rows, and no archive page fetched (only the up-front skip) — live: `unsupported`, 0 network calls, 0 rows
- [x] 5.4 Restart the server and track a product through the UI or TestClient against the real server. Verify the page returns immediately and the history note appears after the job completes — done on an isolated copy of the app (:8001, temp DB) so your data stayed untouched: POST returned after the live Lazada check (12.2 s); job `history-1` was queued in the same millisecond; the note appeared; the current price stayed live (SGD 311.00). Also found and fixed: an orphaned `--reload` worker (pid 1248) had been serving pre-change code on :8000

## 6. Reconcile

- [x] 6.1 Create `docs/history/` (ARCHITECTURE, IMPLEMENTATION, STATUS, suggestions, reviews/, general/) and update the storage, extraction and web IMPLEMENTATION rows, `docs/architecture-map.md` (atoms, component, `t_archive`, placement of `extract_from_html`), `docs/IMPLEMENTATION.md` and `docs/STATUS.md`. Every new or changed morphism gets a `file:symbol` row
- [x] 6.2 Update `README.md` (what archived history is, where it comes from, its limits: Amazon/schema.org shops only, never Lazada/Shopee) and `CLAUDE.md` (the "current price is live-only" rule, and "never render archived pages")
- [x] 6.3 Run the supercharge drift check; fix dead rows; record the result — `0 dead / 312 refs` (was 253; new files must be staged for `git ls-files` to see them)
