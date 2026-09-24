# Proposal

## Why

The BUY/WAIT verdict needs price history, but a newly tracked product has none.
It reads `NOT ENOUGH DATA` until the app has checked it at least 3 times, which
takes about 12 hours on the 6-hourly schedule, and weeks before percentiles mean
anything. Much of that history already exists: the Internet Archive has stored
dated copies of many product pages. On 2026-09-24 the Sony WH-1000XM5 amazon.com
page had **53 monthly captures from 2022 to 2026**, and the app's existing
extractor read real prices from them (USD 196.23 in Jul 2024, USD 149.95 in
Sep 2026). The user asked for exactly this: find a store of past prices and match
it to the product they track.

## What Changes

- When a listing is tracked, its **archived price history is looked up in the
  background** from the Internet Archive (Wayback CDX index plus raw archived
  pages). Each capture's price is read with the existing extractor and stored as
  that listing's own past observation, dated at capture time.
- Matching is **exact**. The archive is searched for the tracked listing's own
  URL, plus the shop's canonical form of it (Amazon `/dp/<ASIN>`). There's no fuzzy
  matching and no cross-listing guesswork.
- Archived observations are **marked as archived** and link to the capture. They
  count toward history and the verdict, but **never toward "cheapest right
  now"**, which stays live-only.
- It's honest about gaps. The product page says per listing whether archived
  prices were found, none exist, the archive was unreachable, or the shop can't be
  read from archives. Lazada and Shopee paint prices with JavaScript, so their
  archived copies hold only the crossed-out list price.
- It's safe by construction. Captures are **never rendered in a browser**.
  Archived prices in a different currency from the listing are not stored.
  Implausible outliers (under ⅓ or over 3× the listing's median) are dropped and
  counted.
- **Polite:** at most 24 captures per listing (one per month, newest first),
  about 1 request per second, one job per product, never blocking a page load.
- A **"Look for archived prices"** button re-runs the lookup. Re-running never
  duplicates observations.
- A small **history-source port**, so a second provider can be added later
  without touching the rest. BuyWhere is the intended next one; its API was
  unreachable on 2026-09-24.

## Capabilities

### New Capabilities
- `price-history-backfill`: finding a tracked listing's past prices in an external archive, storing them with provenance, and how they affect history, verdicts and current-price comparison.

### Modified Capabilities
- none (the existing currency and target specs still hold unchanged; archived observations obey them)

## Impact

- **Schema:** additive columns, with no table rebuild:
  - `price_snapshots.origin` (NULL = live) and `price_snapshots.origin_ref` (the
    capture URL)
  - `sources.history_checked_at` and `sources.history_note`
- **Code:**
  - new `app/history.py` (the port, the Wayback adapter, the backfill job)
  - `app/scraper.py` (a public, never-render extraction entry point)
  - `app/database.py`
  - `app/main.py` (live-only latest price, scheduling, re-run route, view data)
  - `app/scheduler.py` (a one-off job helper)
  - `app/templates/product.html`
- **External:** read-only requests to `web.archive.org` (the CDX API and raw
  captures). No key or account is needed.
- **Tests:** a new offline `tests/test_history.py` using fixture CDX JSON and
  archived HTML.
- **Docs:** a new `docs/history/` component, plus row updates in the storage,
  web and extraction maps, the architecture map and the roll-ups. `README.md` and
  `CLAUDE.md` get the new behaviour and its limits.
