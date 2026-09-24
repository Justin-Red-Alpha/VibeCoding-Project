"""Search each shop's OWN search page, rendered in a real browser.

Why this exists: the web-search route (`providers.py`) is rate-limited hard and
takes the whole feature down with it. Searching a shop directly has no such
budget, and it is what "search this site for a deal" actually means.

The big win is that search-result cards already carry prices, so a shop's entire
result set costs **one** page render instead of one render per product.

All shops are searched at once in one browser, and each is reported the moment it
finishes -- a slow or blocked shop never holds the others up.

Needs Playwright. Without it, fall back to `providers.discover`.
"""

import asyncio
import logging
import queue
import threading
from urllib.parse import urlparse, urlunparse

from .. import browser
from ..adapters import adapter_for, retailer_label
from ..scraper import parse_price_number, detect_currency, looks_like_bot_wall, ScrapeError
from .base import Candidate
from .matching import score_candidate

logger = logging.getLogger("price_tracker.site_search")

MAX_CARDS_PER_SHOP = 12
PAGE_SETTLE_MS = 7000
NO_RESULTS = "No results found (the shop may have blocked the search)."

# Real results pages measured 1.3 MB (Amazon) and 2.3 MB (Lazada) as soon as the
# HTML arrived; eBay's refusal is a 1.8 KB "Error Page". A page this small with no
# result cards is not a results page still loading -- don't wait 7 s to find out.
BLOCKED_PAGE_MAX_CHARS = 20_000

# Runs inside the page: pull (title, price, href) out of each result card.
EXTRACT_JS = """
(sel) => {
  const out = [];
  document.querySelectorAll(sel.card).forEach(card => {
    const link = card.querySelector(sel.link);
    if (!link || !link.href) return;
    const titleEl = sel.title ? card.querySelector(sel.title) : null;
    const title = ((titleEl ? titleEl.innerText : card.innerText) || "")
        .replace(/\\s+/g, " ").trim();
    const priceEl = sel.price ? card.querySelector(sel.price) : null;
    // textContent, not innerText: shops hide the canonical price off-screen.
    const price = priceEl ? (priceEl.textContent || "").trim() : "";
    if (!title) return;
    out.push({ href: link.href, title: title.slice(0, 160), price: price.slice(0, 40) });
  });
  return out;
}
"""


def playwright_available() -> bool:
    try:
        import playwright.sync_api  # noqa: F401
        return True
    except ImportError:
        return False


def _clean_url(url: str) -> str:
    """Drop tracking query strings so the same listing dedupes and stays readable."""
    parsed = urlparse(url)
    return urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))


def shops_for(domains: list[str]):
    """Pair each configured domain with the adapter that can search it."""
    pairs = []
    for domain in domains:
        adapter = adapter_for(f"https://www.{domain}/")
        if adapter.supports_site_search:
            pairs.append((adapter, domain))
        else:
            logger.info("No site-search support for %s; skipping", domain)
    return pairs


class ShopRefused(Exception):
    """The shop answered with an error or bot-check page instead of results."""


def looks_blocked(html: str, card_count: int) -> bool:
    """True only on a positive sign of a block. A big page with no cards yet is
    still rendering and gets the full wait (a block must never look like an
    empty result, and a slow shop must never look like a block)."""
    if card_count:
        return False
    return looks_like_bot_wall(html) or len(html) < BLOCKED_PAGE_MAX_CHARS


async def search_shop(page, adapter, domain: str, query: str) -> list[Candidate]:
    """Render one shop's search page and read its result cards."""
    url = adapter.search_url(domain, query)
    await page.goto(url, timeout=60000, wait_until="domcontentloaded")

    cards = await page.locator(adapter.search_card).count()
    if not cards and looks_blocked(await page.content(), cards):
        raise ShopRefused(
            f"{adapter.name} answered with an error page instead of search results -- it is "
            "refusing automated searches from this network."
        )

    try:
        await page.wait_for_selector(adapter.search_card, timeout=PAGE_SETTLE_MS)
    except Exception:
        await page.wait_for_timeout(2000)  # give a slow shop one more moment

    rows = await page.evaluate(EXTRACT_JS, {
        "card": adapter.search_card,
        "title": adapter.search_title,
        "price": adapter.search_price,
        "link": adapter.search_link,
    })
    return _to_candidates(rows, adapter, domain, query)


def _to_candidates(rows, adapter, domain: str, query: str) -> list[Candidate]:
    candidates: list[Candidate] = []
    seen: set[str] = set()
    for row in rows:
        href = _clean_url(row["href"])
        if not adapter.is_product_url(href) or href in seen:
            continue
        seen.add(href)

        price, currency = None, None
        if row["price"]:
            try:
                price = parse_price_number(row["price"])
                currency = detect_currency(row["price"], href)
            except ScrapeError:
                price = None  # card without a usable price; keep the listing anyway

        candidate = Candidate(
            title=row["title"],
            url=href,
            retailer=retailer_label(href),
            provider=f"site:{domain}",
            price=price,
            currency=currency,
        )
        candidate.score, candidate.flags = score_candidate(query, candidate.title)
        candidates.append(candidate)
        if len(candidates) >= MAX_CARDS_PER_SHOP:
            break

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates


async def _gather_shops(pairs, run_one, emit) -> None:
    """Search every shop at once; `emit` each (domain, retailer, candidates, error)
    the moment that shop finishes. One shop failing never stops the others."""

    async def one(adapter, domain):
        try:
            found = await run_one(adapter, domain)
            emit((domain, adapter.name, found, None if found else NO_RESULTS))
        except ShopRefused as exc:
            emit((domain, adapter.name, [], str(exc)))
        except Exception as exc:
            logger.warning("Site search failed for %s: %s", domain, exc)
            emit((domain, adapter.name, [], f"{type(exc).__name__}: {str(exc)[:120]}"))

    await asyncio.gather(*(one(adapter, domain) for adapter, domain in pairs))


_DONE = object()


def _stream(job):
    """Run the async `job(emit)` on a thread of its own; yield what it emits, as it
    emits it. The job's own failure (e.g. BrowserUnavailable) is re-raised here,
    after anything it managed to emit."""
    results: queue.Queue = queue.Queue()
    failure: list[BaseException] = []

    def worker():
        try:
            browser.run(job(results.put))
        except BaseException as exc:
            failure.append(exc)
        finally:
            results.put(_DONE)

    # Daemon: if the user closes the tab, the search still ends within its timeouts.
    threading.Thread(target=worker, name="shop-search", daemon=True).start()
    while (item := results.get()) is not _DONE:
        yield item
    if failure:
        raise failure[0]


def search_all(query: str, domains: list[str], per_shop: int = 6):
    """Yield (domain, retailer, candidates, error) per shop, as each finishes.

    A generator on purpose: the caller streams each shop to the browser the moment
    it lands, instead of making the user wait for the slowest one. Raises
    browser.BrowserUnavailable if Chromium can't be started at all.
    """
    pairs = shops_for(domains)
    if not pairs:
        return

    async def job(emit):
        async with browser.chromium() as instance:
            async def run_one(adapter, domain):
                page = await browser.new_page(instance)
                try:
                    return (await search_shop(page, adapter, domain, query))[:per_shop]
                finally:
                    await page.context.close()

            await _gather_shops(pairs, run_one, emit)

    yield from _stream(job)
