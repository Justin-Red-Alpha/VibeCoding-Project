"""Finding candidate listings for a product name.

There is no free, no-key, reliable "search every shop" API. What exists:

  * A web search engine, which we ask for `<product> site:<shop>` and then scrape
    the resulting product pages ourselves. No key, works today, but it is an
    unofficial endpoint that can rate-limit or change shape.
  * Official shop APIs (eBay Browse, Amazon PA-API, Lazada/Shopee Open Platform)
    -- reliable and sanctioned, but each needs credentials.
  * Paid search APIs (SerpAPI, Brave, ScraperAPI) -- reliable, need a key.

The DuckDuckGo HTML endpoint is implemented because it is the only one that works
with zero setup. `SEARCH_DOMAINS` controls which shops get searched, so you can
point this at your own region.
"""

import logging
import os
import re
import time
import urllib.parse
from dataclasses import replace

import requests
from bs4 import BeautifulSoup

from ..adapters import ADAPTERS, GENERIC, adapter_for, retailer_label
from ..scraper import BROWSER_HEADERS
from .base import Candidate
from .matching import score_candidate

logger = logging.getLogger("price_tracker.search")

DDG_HTML = "https://html.duckduckgo.com/html/"

# Which shops to search, and in what region. Override with e.g.
#   $env:SEARCH_DOMAINS = "lazada.com.my,shopee.com.my,amazon.sg"
DEFAULT_SEARCH_DOMAINS = [a.search_domain for a in ADAPTERS if a.search_domain]

# DuckDuckGo throttles rapid queries; pause between any we do make.
DELAY_BETWEEN_QUERIES = float(os.environ.get("SEARCH_QUERY_DELAY", "1.5"))

# Query budget management. The broad query costs 1 request; the per-shop fallback
# costs one per shop, which is what gets you throttled.
MAX_BROAD_RESULTS = 12
MIN_RESULTS_BEFORE_PER_SHOP = 4
PER_SHOP_FALLBACK = os.environ.get("SEARCH_PER_SHOP_FALLBACK", "1") != "0"

# Repeating a search shouldn't cost another query.
CACHE_TTL_SECONDS = float(os.environ.get("SEARCH_CACHE_TTL", "900"))
_CACHE: dict[str, tuple[float, list[Candidate]]] = {}


def _cache_get(key: str) -> list[Candidate] | None:
    entry = _CACHE.get(key)
    if not entry:
        return None
    stored_at, candidates = entry
    if time.time() - stored_at > CACHE_TTL_SECONDS:
        _CACHE.pop(key, None)
        return None
    # Hand back copies: the caller decorates candidates with prices, and that
    # must not leak into the next search.
    return [replace(c, flags=list(c.flags)) for c in candidates]


def _cache_put(key: str, candidates: list[Candidate]) -> None:
    _CACHE[key] = (time.time(), [replace(c, flags=list(c.flags)) for c in candidates])


class SearchUnavailable(Exception):
    """The search backend refused us -- distinct from 'found nothing'."""


# DuckDuckGo answers a throttled client with HTTP 202 and an "anomaly" page
# rather than an error, so an unchecked caller sees zero results and wrongly
# concludes the product doesn't exist.
BLOCK_MARKERS = ("anomaly", "unusual traffic", "are you a robot", "blocked")


def _looks_throttled(status_code: int, html: str) -> bool:
    lowered = html.lower()
    if any(marker in lowered for marker in BLOCK_MARKERS):
        return True
    return status_code == 202 and "result__a" not in html


def search_domains() -> list[str]:
    configured = os.environ.get("SEARCH_DOMAINS", "").strip()
    if configured:
        return [d.strip() for d in configured.split(",") if d.strip()]
    return DEFAULT_SEARCH_DOMAINS


def available_providers() -> list[str]:
    return ["duckduckgo"]


def _decode_ddg_url(href: str) -> str | None:
    """DDG wraps results in a redirect carrying the real URL in `uddg`."""
    if "y.js" in href or "ad_domain" in href:
        return None  # sponsored slot
    match = re.search(r"uddg=([^&]+)", href)
    url = urllib.parse.unquote(match.group(1)) if match else href
    return url if url.startswith("http") else None


def _canonical(url: str) -> str:
    """Drop tracking params and mobile hosts so the same listing dedupes."""
    parsed = urllib.parse.urlparse(url)
    host = parsed.hostname or ""
    for prefix in ("h5.", "m.", "www."):
        if host.startswith(prefix):
            host = host[len(prefix):]
    return f"{host}{parsed.path}".rstrip("/").lower()


def _search_one_domain(query: str, domain: str, limit: int, timeout: int) -> list[Candidate]:
    """Returns matching listings. Raises SearchUnavailable if we're throttled."""
    params = {"q": f"{query} site:{domain}"}
    try:
        resp = requests.post(DDG_HTML, data=params, headers=BROWSER_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Search failed for %s: %s", domain, exc)
        return []

    if _looks_throttled(resp.status_code, resp.text):
        raise SearchUnavailable(
            "The search engine is rate-limiting this app (it answers with an 'anomaly' "
            "page instead of results). Wait a few minutes and try again, search less often, "
            "or add a product by URL from the home page."
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[Candidate] = []
    for anchor in soup.select("a.result__a"):
        url = _decode_ddg_url(anchor.get("href", ""))
        if not url:
            continue
        adapter = adapter_for(url)
        if not adapter.is_product_url(url):
            continue  # category / tag / search page, not a listing
        results.append(
            Candidate(
                title=anchor.get_text(strip=True),
                url=url,
                retailer=retailer_label(url),
                provider="duckduckgo",
            )
        )
        if len(results) >= limit:
            break
    return results


def _search_broad(query: str, limit: int, timeout: int) -> list[Candidate]:
    """One unrestricted query, keeping whatever recognised shop listings come back.

    This is the cheap path: a single request instead of one per shop. Query budget
    is the binding constraint on the free endpoint, so spend it here first.
    """
    try:
        resp = requests.post(DDG_HTML, data={"q": f"{query} buy price"},
                             headers=BROWSER_HEADERS, timeout=timeout)
        resp.raise_for_status()
    except requests.RequestException as exc:
        logger.warning("Broad search failed: %s", exc)
        return []

    if _looks_throttled(resp.status_code, resp.text):
        raise SearchUnavailable(
            "The search engine is rate-limiting this app (it answers with an 'anomaly' "
            "page instead of results). Wait a while and try again, or configure a search "
            "API key. You can still add products by URL from the home page."
        )

    soup = BeautifulSoup(resp.text, "html.parser")
    results: list[Candidate] = []
    for anchor in soup.select("a.result__a"):
        url = _decode_ddg_url(anchor.get("href", ""))
        if not url:
            continue
        adapter = adapter_for(url)
        # Only shops we know, so "is this a product page?" is answerable.
        if adapter is GENERIC or not adapter.is_product_url(url):
            continue
        results.append(Candidate(title=anchor.get_text(strip=True), url=url,
                                 retailer=retailer_label(url), provider="duckduckgo"))
        if len(results) >= limit:
            break
    return results


def discover(
    query: str,
    domains: list[str] | None = None,
    per_domain: int = 3,
    timeout: int = 20,
    use_cache: bool = True,
) -> list[Candidate]:
    """Find candidate listings for `query`, best match first.

    Starts with one broad query and only falls back to per-shop queries if that
    turned up too little, because the free search endpoint throttles on query
    count -- five site-restricted queries per search exhausts it in a handful of
    searches. Prices are NOT fetched here; that's a slower step the caller drives.
    """
    key = " ".join(query.lower().split())
    if use_cache:
        cached = _cache_get(key)
        if cached is not None:
            return cached

    found: dict[str, Candidate] = {}
    throttled_error: SearchUnavailable | None = None

    def absorb(results):
        for candidate in results:
            url_key = _canonical(candidate.url)
            if url_key in found:
                continue
            candidate.score, candidate.flags = score_candidate(query, candidate.title)
            found[url_key] = candidate

    try:
        absorb(_search_broad(query, MAX_BROAD_RESULTS, timeout))
    except SearchUnavailable as exc:
        throttled_error = exc

    # Only spend extra queries if the cheap path didn't find enough.
    if len(found) < MIN_RESULTS_BEFORE_PER_SHOP and PER_SHOP_FALLBACK:
        for index, domain in enumerate(domains or search_domains()):
            time.sleep(DELAY_BETWEEN_QUERIES)
            try:
                absorb(_search_one_domain(query, domain, per_domain, timeout))
            except SearchUnavailable as exc:
                throttled_error = exc
                break  # once throttled, further queries only dig the hole deeper

    if throttled_error and not found:
        raise throttled_error

    ranked = sorted(found.values(), key=lambda c: c.score, reverse=True)
    if use_cache and ranked:
        _cache_put(key, ranked)
    return ranked
