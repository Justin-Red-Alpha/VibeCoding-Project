# Design

## Context

See `proposal.md` for the motivation. Measured baseline, 2026-09-24, over real HTTP
(`curl`-style SSE client, "Sony WH-1000XM5"):

```
  9.6s shop  amazon.sg     rows=6 priced=2
 12.3s shop  lazada.sg     rows=6 priced=6
 21.5s shop  ebay.com.sg   rows=0  (error page)
 23.8 / 25.9 / 28.0 / 30.0s   4 Amazon product-page prices, one after another
 30.0s done
```

The scratch experiments were run outside the app, against the same shops:

| Variant | Amazon | Lazada | eBay | Total |
| --- | --- | --- | --- | --- |
| sequential, heavy resources blocked | goto 1.3 s | goto 1.9 s | goto 0.1 s + 7.0 s wait | 11.8 s |
| parallel, heavy resources blocked | 3.0 s | 4.0 s | 8.2 s | 8.3 s |
| page size at DOMContentLoaded | 1,296 KB | 2,302 KB | **1.8 KB** "Error Page \| eBay" | — |

In both runs Amazon returned 48 cards and Lazada 40.

The `--reload` crash was reproduced in `loop_probe.py`. With the Windows Selector
policy set (which is what uvicorn 0.30.6 does when `use_subprocess` is on), the
sync API raises `NotImplementedError`. The async API run via
`asyncio.run(..., loop_factory=asyncio.ProactorEventLoop)` launches Chromium and
reads a page.

Two call sites start Chromium today, both with the sync API and both vulnerable:
`site_search.search_all` and `scraper._render_with_playwright`. The latter is also
used by refresh (the scheduler thread and the Refresh buttons).

Model delta, in FRAMEWORK terms:

| Kind | Item | Signature | Notes |
| --- | --- | --- | --- |
| `Loc` | headless Chromium | one per search, shared by all shops | was one per search, shops in series |
| `Trn` | `browser.run(coro)` | runs a coroutine on a loop that can spawn subprocesses | Proactor on Windows, default elsewhere |
| `Trn` | `browser.new_page(browser)` | opens a page with the shop headers, and image/font/media requests aborted | one definition instead of two copies |
| `Trn` | `site_search.looks_blocked(html, cards)` | → bool | True when there are no cards and the page is a bot wall or < 20 KB |
| `Trn` | `site_search.search_all` | still a sync generator of `(domain, retailer, candidates, error)` | now in completion order; raises `BrowserUnavailable` if Chromium can't start |
| `Trm` | SSE `shop` / `price` events | unchanged payloads | order is completion order |

## Goals / Non-Goals

**Goals:**
- Get the whole search under 15 s without changing what is read.
- Make browser rendering independent of how the server's event loop is configured.
- Say "blocked" when a shop blocks us, promptly.

**Non-Goals:**
- Making refresh (`refresh_product` / `refresh_all`) concurrent. Its 1.5 s gap
  between requests is a deliberate politeness rule. It still gets faster from the
  resource blocking and the loop fix.
- Caching search results or reusing one browser across searches (a persistent
  browser process). Revisit if 6–8 s still feels slow.
- Fixing eBay search itself (open item P3: the Browse API).

## Decisions

1. **Use Playwright's async API on an explicitly created loop, instead of changing
   the global event loop policy.**
   `browser.run(coro)` calls `asyncio.run(coro, loop_factory=ProactorEventLoop)` on
   Windows. It doesn't depend on, or modify, whatever policy the server set.
   *Discarded:* calling `asyncio.set_event_loop_policy(WindowsProactorEventLoopPolicy())`
   at import. It's global mutable state, the API is deprecated in Python 3.14
   (removal in 3.16), and it only works if it runs after uvicorn's own setup.
   *Discarded:* documenting "don't use `--reload`". The docs already say to use it,
   and the code should not depend on how it is launched.

2. **Use one browser per search with one context per shop, run with
   `asyncio.gather`.** The shop tasks run on a background thread. Each finished
   shop is put on a `queue.Queue`, and the sync generator the SSE route iterates
   yields from that queue. This keeps `search_all`'s contract, so `main.py`'s stream
   loop is unchanged.
   *Discarded:* one thread per shop, each with its own sync Playwright. That means
   three Chromium processes, and it still needs the loop fix. *Discarded:* making
   the route async. Starlette already iterates sync generators in a threadpool, so
   an async route would be a bigger change for no speed gain.

3. **Put the browser work (Chromium) and the scheduling of the shop searches in
   separate functions.** `_gather_shops(pairs, run_one, emit)` is the scheduling
   part: plain asyncio, no Chromium. Tests pass a fake `run_one` with
   `asyncio.sleep` delays to check completion order and error isolation. The
   Chromium part is a thin wrapper that supplies the real `run_one`.

4. **Detect a block using a positive signal only.** Right after DOMContentLoaded,
   if the page has no result cards **and** (`looks_like_bot_wall(html)` **or**
   `len(html) < 20_000`), report the shop as blocked without waiting. The 20 KB
   threshold sits between 1.8 KB (eBay's error page) and 1,296 KB (the smallest
   real results page), a margin of about 700×. A large page with no cards yet still
   gets the full wait, so slow rendering is never mistaken for a block
   (invariant 3). The message names the shop and says it refused the search.
   *Discarded:* waiting for `document.readyState === "complete"` and giving up if
   no cards. JS-rendered results can arrive after `load`, so this would misreport
   slow shops as blocked.

5. **Abort `image`, `font` and `media` requests on every rendered page.** Search
   cards and product prices are read from text. Scripts, XHR and CSS still load, so
   JS-rendered prices (Lazada) still appear. The live checks in `tasks.md` must
   confirm that Lazada still reads the sale price (invariant 2).
   *Discarded:* also blocking stylesheets. Some shops lay out price nodes via CSS
   and `innerText` depends on rendering. The saving is small and the risk is real.

6. **Look up missing prices with `ThreadPoolExecutor(max_workers=3)` and yield from
   `as_completed`.** `fetch_price` stays synchronous, and when it needs to render it
   calls `browser.run` on its own worker thread, with its own loop. The cap of 3
   keeps a burst to one shop about the size of a person opening three tabs.
   Candidate objects are updated on the generator's thread, after each future
   completes, so no candidate is shared between workers.

7. **Report a failed browser start as an error event.** `search_all` raises
   `BrowserUnavailable` when Chromium can't launch. `discover_stream` catches it and
   yields `{"type": "error"}`, which the page already handles. The page's `onerror`
   handler also resets every shop still showing "searching…", so a dropped stream
   can't leave spinners running.

## Risks / Trade-offs

- **Risk:** blocking images makes a shop's bot detection more suspicious.
  **Mitigation:** the live runs showed no change on Amazon or Lazada. If one starts
  blocking, add a per-adapter opt-out (`render_images=True`) rather than removing
  it everywhere.
- **Risk:** a background thread outlives a closed browser tab.
  **Mitigation:** it's a daemon thread and finishes within the existing per-shop
  timeouts (at most ~60 s). Nothing it writes is shared.
- **Risk:** concurrent Amazon product-page GETs trigger throttling.
  **Mitigation:** the cap of 3, and the existing bot-wall detection reports it
  plainly if it happens.
- **Trade-off:** shop sections now fill in finishing order. That's the point:
  whatever is ready gets shown.

## Migration Plan

This is a code-only change, with no data or schema changes. To roll back, revert
the commit. Restarting the server picks it up.
