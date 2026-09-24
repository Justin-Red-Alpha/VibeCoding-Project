# 2026-09-24 — archived price history

## 0. Continuation brief

Current state: **archived price history is built, verified and archived** as an
OpenSpec change (17/17). When a listing is tracked, a background job looks up
Internet Archive copies of that same listing's page. It reads each copy's price
with the existing extractor and stores them as `PriceSnapshot`s marked
`origin='wayback'`, dated at capture time. They feed history and the verdict,
**never** the current price.

Live result: the amazon.com WH-1000XM5 gave 9 USD prices (2025-05 → 2026-09).
Lazada and Shopee are skipped by design, since their archived copies only hold
the list price. BuyWhere, the intended source for them, was unreachable all day.

**This machine was rate-limit-blocked by web.archive.org** at about 14:00 SGT
(research probes plus one live lookup). The code now follows the archive's limits.

Next step: after the block has surely lifted (1 h+, and it doubles on repeat, so
wait longer rather than probe), inspect the suspicious **USD 88.00 (2025-12)**
capture. If it's a wrong element, order Amazon's `#corePrice…` selectors first.

Resume command/check: `python -m tests.test_history` (77 OK), then
`bash ~/.claude/skills/supercharge/scripts/drift-check.sh` (expect `0 dead / 312 refs`).

---

## 1. Work completed

1. **Research, for the user's request** ("a database with price history, matched
   to the item"):
   - **Keepa:** €49/mo+, no amazon.sg, so excluded.
   - **BuyWhere** (SEA API, free key): search came back `degraded`/empty, and
     registration timed out at 30 s and 90 s. Its docs disagree on whether price
     history exists. **Nothing was registered and no key exists.**
   - **Wayback:** 53 monthly captures of the WH-1000XM5 amazon.com page, and the
     existing extractor read real prices from them.
   - The user chose "Wayback now, BuyWhere next" and allowed a BuyWhere key.
2. `.gitignore` now ignores `.env`. It was *not* ignored before, and that was
   fixed ahead of any key.
3. The OpenSpec change `archived-price-history` was proposed, applied and archived.
   Code:
   - `app/history.py` (new): the `HistoryResult` sum, `archive_urls`,
     `wayback_lookup`, `filter_observations`, `backfill_source`,
     `backfill_product`, `schedule_backfill`, `HISTORY_SOURCES`, back-off
   - `app/database.py`: 4 additive columns, `add_snapshot(fetched_at, origin,
     origin_ref)`, `get_origin_refs`, `set_history_note`
   - `app/scraper.py`: `extract_from_html`, which never renders
   - `app/adapters.py`: `item_id_re`, `canonical_path`, set for Amazon
   - `app/scheduler.py`: `run_once`
   - `app/main.py`: `_latest_per_source` is live-only; scheduling after add,
     track and add-source; `POST /products/{id}/history`
   - `product.html`: per-listing note, the "Look for archived prices" button, and
     archived rows marked and linked
4. Tests: new `tests/test_history.py` with 77 checks, all offline, with the
   archive faked.
5. Docs:
   - a new `docs/history/` component;
   - storage, extraction, web and refresh maps, the architecture map and the
     roll-ups updated;
   - README gets a new "Past prices from the Internet Archive" section;
   - CLAUDE.md gets invariant 9 (archived = history only) and two new traps
     (archive 429 blocks, orphaned `--reload` worker);
   - `openspec/config.yaml` lists history and invariant 9.

---

## 2. Decisions

| Decision | Verdict | Why |
| --- | --- | --- |
| Keepa | **discarded** | Paid, and no amazon.sg |
| BuyWhere | **deferred (user: "next")** | Unreachable. Its slot is `HISTORY_SOURCES` |
| Wayback Machine | **kept (user)** | Free, no account, verified to give real prices through the existing extractor |
| A separate `history_points` table | **discarded** | The §3 reduction: an archived price has exactly `PriceSnapshot`'s morphisms plus provenance, so it's `origin?` on the same object |
| Archived rows in the current price | **discarded** | A capture newer than the last live check would pose as "cheapest right now" |
| Fuzzy / name-based or cross-domain matching | **discarded** | It would put another listing's past into this one. Exact URL plus canonical form, same host |
| Render archived pages | **discarded** | Replayed JS reaches live hosts, and for Lazada only the list price is in the HTML (invariant 2) |
| Store everything, filter at read time | **discarded** | An accessory or used-offer price would permanently skew percentiles. It's filtered before storing, with counts in the note |
| A 1 s gap between archive requests | **discarded (wrong)** | The archive firewall-blocks clients that continue past a 429. Now: 4 s gap, stop on the first 429 or refusal, pause 15/60 min |
| Timeouts of 20 s | **discarded** | The index took 9–50 s live. Now 60 s for the index and 30 s per capture |
| A second listing re-fetches the whole product | **discarded** | Automatic runs do only unchecked listings; the button re-checks everything |
| Hard-code "if Amazon" in history | **discarded** | The canonical-URL rule lives on the `Adapter` (`item_id_re`, `canonical_path`) |
| Live check 5.4 against the user's real DB | **discarded** | The user has a real product. An isolated copy of the app ran on :8001 with a temp DB |

---

## 3. Tests, checks, benchmarks

| Check | Result | What it proved |
| --- | --- | --- |
| `test_extraction` / `test_search` / `test_currency` / `test_shop_search` / `test_history` | 63 / 48 / 89 / 32 / **77** OK (309 total) | Nothing regressed. The new behaviour is pinned |
| Mutation: `_latest_per_source` without the origin filter | 2 FAIL (an archived USD 150 shown as current; archived-only listing priced) | The live-only tests are not vacuous |
| Live backfill, amazon.com WH-1000XM5 (temp DB) | `found`, 26 requests, 134 s, **9** USD prices 2025-05 → 2026-09, all within ⅓–3× of the median | Real prices come out of real captures. The "≥ 10" target was an estimate |
| Same, first attempt | `unavailable` (index read timed out at 20 s) | Honest outcome. It led to the timeout change |
| Live: Lazada listing | `unsupported`, **0 network calls**, 0 rows | Invariant 2 holds before any request |
| Live 5.4: isolated app :8001, `POST /products` (Lazada) | 303 after 12.2 s (the live render). Job `history-1` queued in the same ms, then the note appeared. Price SGD 311.00 stayed live | Background, non-blocking, visible |
| CDX timing | 49.7 s (slug URL), 9.2 s (`/dp/`) | Why the timeouts are 60 s / 30 s |
| `drift-check.sh` | **0 dead / 312 refs** | The model maps to real code |
| `openspec validate --specs --strict` | 4/4 | Merged specs valid |

---

## 4. Live handoff state

| Type | Handle / location | State | Inspect / resume | Stop / cleanup |
| --- | --- | --- | --- | --- |
| **external block** | web.archive.org → this IP | **firewall-blocked** from ~14:00 SGT 2026-09-24 (connection refused); 1 h, doubling on repeat | **don't probe in a loop.** After 1 h+, one request: `curl -s -o NUL -w "%{http_code}" https://web.archive.org/` | wait it out |
| process | uvicorn `--reload` on :8000 (fresh; started ~14:08) | running on current code | `Get-NetTCPConnection -LocalPort 8000 -State Listen` | `Get-CimInstance Win32_Process -Filter "Name='python.exe'" \| ? CommandLine -like '*uvicorn*app.main*' \| % { Stop-Process -Id $_.ProcessId -Force }` and check children (see the CLAUDE.md trap) |
| process | isolated test app on :8001 | stopped | `Get-NetTCPConnection -LocalPort 8001` | none |
| data | `data/app.db` (git-ignored) | **migrated** (4 new columns); **1 product created by the user**, untouched | `.venv\Scripts\python.exe -c "import sqlite3;print(sqlite3.connect('data/app.db').execute('select count(*) from products').fetchone())"` | none |
| config | `.env` | ignored by git; **does not exist** (no BuyWhere key was issued) | `git check-ignore -v .env` | — |
| branch | `main` | committed and pushed after this log (see §10) | `git log --oneline -3` | — |

---

## 5. In-flight changes (from OpenSpec)

| Change | Tasks | Status | Next ready artifact |
| --- | --- | --- | --- |
| none | — | — | — |

Archived: `2026-09-24-archived-price-history` (17/17) → `openspec/specs/price-history-backfill/spec.md` (7 requirements).

---

## 6. Open items

| Priority | Item | Doc/code reference | Next action | Done when |
| --- | --- | --- | --- | --- |
| P1 | Suspicious archived **USD 88.00 (2025-12)** for the WH-1000XM5 | `docs/history/suggestions.md` #1 | After the block lifts, fetch that capture once and see which element `.a-price .a-offscreen` hit | Confirmed right, or the selectors reordered with a test |
| P2 | BuyWhere (Shopee/Lazada history) | `app/history.py:HISTORY_SOURCES` | Retry registration; if price history returns real SEA data, add an adapter | BuyWhere row moves from planned to built |
| P2 | Archived points look like live ones on the chart | `docs/history/suggestions.md` #3 | Hollow point style for `origin?` rows | Visible on the chart |
| P2 | Two writers of `PriceSnapshot`, and success ⊕ failure held by convention | `docs/storage/suggestions.md` #1 | A `CHECK` constraint (rebuild: invariant 8) | Constraint plus test |
| P2 | Carried: SSE types undeclared, refresh has no tests, keyed providers unbuilt | `docs/suggestions.md` | See the roll-up | — |
| P3 | Carried: Chromium cold start, eBay Browse API, Shopee/Qoo10 search, Lazada intermittency, graphify shim, historical FX, target edit form, placeholder truncation | `docs/STATUS.md` | — | — |

---

## 7. Architecture / model changes

- **Dat:**
  - `PriceSnapshot.origin?` and `origin_ref?` (the §3 discriminator, not a new
    object)
  - `Source.history_checked_at?` and `history_note?`
  - `fetched_at` now means *observed at*
- **Trn:** `archive_urls`, `wayback_lookup` (the port's first realisation),
  `filter_observations`, `backfill_source` and `backfill_product`.
  `extract_from_html` gains a second placement.
- **Loc:** `Archive` (external) and the scheduler's worker thread (reused).
- **Trm:** `t_archive : Archive → ServerProc` (index rows or HTML).
- **New invariant 9:** archived prices are history, never the current price.
- **Coherence:** no law fails. Law 4 holds, since the request never waits on the
  archive. `PriceSnapshot` has a second writer (noted in storage).

---

## 8. Docs reconciled

| Doc | Change |
| --- | --- |
| `docs/history/*` | New component: model, map, status, suggestions |
| `docs/storage/*` | 4 new morphisms, rule 6 (archived = history), a second-writer note |
| `docs/extraction/*`, `docs/web/*`, `docs/refresh/IMPLEMENTATION.md` | `extract_from_html`, adapter fields, route, template rows, live-only rule 8, `run_once` |
| `docs/architecture-map.md`, `docs/IMPLEMENTATION.md`, `docs/STATUS.md`, `docs/suggestions.md` | history component, `t_archive`, placements, ports, entry points, status row, suggestion 1a |
| `README.md` | "Past prices from the Internet Archive"; test command |
| `CLAUDE.md` | Component list, data model, invariant 9, traps (archive 429 block, orphaned `--reload` worker), test command |
| `openspec/config.yaml` | history component and invariant 9 in the context |
| `openspec/specs/price-history-backfill/spec.md` | Created by archive (with the corrected politeness requirement) |

---

## 9. Drift check

`drift-check.sh` → **`0 dead / 312 refs`**. It first reported 36 dead: new files
are invisible to `git ls-files` until staged, and they resolved once staged.

---

## 10. Files changed

**Committed on `main` and pushed:**
- Code: `app/history.py` (new), `app/database.py`, `app/scraper.py`,
  `app/adapters.py`, `app/scheduler.py`, `app/main.py`,
  `app/templates/product.html`, `app/static/style.css`
- Tests: `tests/test_history.py` (new)
- Docs: `docs/history/` (new), the storage, extraction, web and refresh maps, the
  4 roll-ups, `README.md`, `CLAUDE.md`, `openspec/config.yaml`,
  `openspec/specs/price-history-backfill/`,
  `openspec/changes/archive/2026-09-24-archived-price-history/`, `.gitignore`,
  and this log

**Outside the repo:** none (no BuyWhere account or key exists).
