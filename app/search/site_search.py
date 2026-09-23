"""Search each shop's OWN search page, rendered in a real browser.

Why this exists: the web-search route (`providers.py`) is rate-limited hard and
takes the whole feature down with it. Searching a shop directly has no such
budget, and it is what "search this site for a deal" actually means.

The big win is that search-result cards already carry prices, so a shop's entire
result set costs **one** page render instead of one render per product.

Needs Playwright. Without it, fall back to `providers.discover`.
"""

import logging
import re
from urllib.parse import urlparse, urlunparse

from ..adapters import ADAPTERS, adapter_for, retailer_label
from ..scraper import BROWSER_HEADERS, parse_price_number, detect_currency, ScrapeError
from .base import Candidate
from .matching import score_candidate

logger = logging.getLogger("price_tracker.site_search")

MAX_CARDS_PER_SHOP = 12
PAGE_SETTLE_MS = 7000

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


def search_shop(page, adapter, domain: str, query: str) -> list[Candidate]:
    """Render one shop's search page and read its result cards."""
    url = adapter.search_url(domain, query)
    page.goto(url, timeout=60000, wait_until="domcontentloaded")
    try:
        page.wait_for_selector(adapter.search_card, timeout=PAGE_SETTLE_MS)
    except Exception:
        page.wait_for_timeout(2000)  # give a slow shop one more moment

    rows = page.evaluate(EXTRACT_JS, {
        "card": adapter.search_card,
        "title": adapter.search_title,
        "price": adapter.search_price,
        "link": adapter.search_link,
    })

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


def search_all(query: str, domains: list[str], per_shop: int = 6):
    """Yield (domain, retailer, candidates, error) per shop, as each finishes.

    A generator on purpose: the caller streams each shop to the browser the moment
    it lands, instead of making the user wait for the slowest one.
    """
    from playwright.sync_api import sync_playwright

    pairs = shops_for(domains)
    if not pairs:
        return

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        try:
            for adapter, domain in pairs:
                context = browser.new_context(
                    user_agent=BROWSER_HEADERS["User-Agent"],
                    locale="en-SG",
                    viewport={"width": 1366, "height": 900},
                )
                page = context.new_page()
                try:
                    found = search_shop(page, adapter, domain, query)
                    if found:
                        yield domain, adapter.name, found[:per_shop], None
                    else:
                        yield domain, adapter.name, [], "No results found (the shop may have blocked the search)."
                except Exception as exc:
                    logger.warning("Site search failed for %s: %s", domain, exc)
                    yield domain, adapter.name, [], f"{type(exc).__name__}: {str(exc)[:120]}"
                finally:
                    context.close()
        finally:
            browser.close()
