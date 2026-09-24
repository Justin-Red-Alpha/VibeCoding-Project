# Proposal

## Why

Searching for a deal takes **30.0 s** (measured 2026-09-24, "Sony WH-1000XM5", three
default shops). Nearly all of that is waiting in line: shops are searched one after
another, every product image is downloaded, eBay's error page is waited on for 9 s,
and missing prices are looked up one at a time.

Separately, search **breaks completely** when the server runs with `--reload`, which
is how `README.md` and `CLAUDE.md` both say to run it. On Windows, uvicorn then
forces an event loop that cannot start subprocesses, so Playwright can't launch
Chromium. The page shows every shop spinning on "searching…" forever, which looks
like slowness but is a crash. That is how it was found: a user trying to test
currency display saw shops "taking a while to load".

## What Changes

- Shops are searched **at the same time**. Each shop's results appear the moment
  that shop finishes, so a slow or blocked shop no longer holds up the others.
- Pages are rendered **without downloading images, fonts or media**. Result titles
  and prices come from text, and live measurement shows the same 48 Amazon and 40
  Lazada cards. Amazon's page load drops from ~9.6 s to ~1.3 s.
- A shop that answers with an **error or block page** is reported as blocked
  immediately. eBay currently returns a 1.8 KB error page in 0.1 s, then the app
  waits 9 s for results that can't appear. Its message also changes from "No
  results found (may have been blocked)" to a plain statement that the shop
  refused the search.
- Missing prices are looked up **up to 3 at a time**, each shown as it lands.
- Browser rendering works **however the server is started**, including `--reload`.
- If the browser can't start at all, the page **says so** and stops the spinners.
  It no longer leaves every shop on "searching…".

Target: the same search finishes in under 15 s. The scratch experiments point to
about 6–8 s.

## Capabilities

### New Capabilities
- `shop-search`: searching the configured shops for a product, how results and missing prices arrive, and how blocked shops and browser failures are reported.

### Modified Capabilities
- none

## Impact

- **Code:** new `app/browser.py`, which is the one place Chromium is started and
  pages are opened. Also `app/search/site_search.py` (moves to Playwright's async
  API and concurrent shops), `app/scraper.py` (`_render_with_playwright` switches to
  the shared browser helper), `app/main.py` (concurrent price lookups, a browser
  failure becomes an error event) and `app/templates/discover.html` (spinners stop
  when the stream stops).
- **Behaviour:** shop sections fill in the order shops finish, not in a fixed
  order. The page already keys sections by shop, so nothing depends on the order.
- **Load on shops:** the number of requests doesn't change; they overlap in time.
  Price lookups are capped at 3 at once.
- **Tests:** new offline `tests/test_shop_search.py`. It needs no network; one check
  launches local Chromium on an in-memory page.
- **Docs:** `CLAUDE.md` gets a Windows trap about `--reload` and the Playwright sync
  API, plus eBay's search behaviour. `README.md` gets the new timings.
- **No new dependencies.** The async API ships with the installed Playwright 1.63.
