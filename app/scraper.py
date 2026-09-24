"""Price extraction.

Different shops hide the price in different places, so we try a series of
strategies and take the first that yields a number:

  1. Retailer API   -- Shopee's HTML is an empty shell; we read the item API
                       whose ids are right there in the product URL.
  2. Your selector  -- if you supplied a CSS selector, you know best.
  3. Adapter CSS    -- known-good selectors for that retailer.
  4. JSON-LD        -- schema.org Product data, published for machines to read.
  5. Meta tags      -- og:price:amount / product:price:amount / itemprop=price.
  6. Embedded JSON  -- Lazada et al. ship the price in a script blob.
  7. Headless browser (optional) -- only if Playwright is installed.
"""

import json
import re
from dataclasses import dataclass
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .adapters import adapter_for, currency_for, shopee_ids

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-SG,en;q=0.9,en-US;q=0.8",
    "Cache-Control": "no-cache",
}

# Longest symbols first so "S$" and "NT$" win over a bare "$".
CURRENCY_SYMBOLS: list[tuple[str, str]] = [
    ("US$", "USD"), ("NT$", "TWD"), ("HK$", "HKD"), ("S$", "SGD"), ("A$", "AUD"),
    ("RM", "MYR"), ("Rp", "IDR"), ("₱", "PHP"), ("₫", "VND"), ("฿", "THB"),
    ("£", "GBP"), ("€", "EUR"), ("¥", "JPY"), ("₹", "INR"), ("$", "USD"),
]
ISO_CODE_RE = re.compile(r"\b(USD|SGD|MYR|IDR|PHP|VND|THB|GBP|EUR|JPY|INR|AUD|TWD|HKD|CAD)\b")
NUMBER_RE = re.compile(r"\d[\d., \s]*\d|\d")


class ScrapeError(Exception):
    pass


# Phrases that mean "we served you a bot check, not the product page". Worth
# detecting separately: the fix is completely different from a missing selector.
BOT_WALL_MARKERS = [
    "enter the characters you see below",
    "type the characters you see in this image",
    "robot check",
    "make sure you're not a robot",
    "to discuss automated access",
    "automated access to amazon data",
    "unusual traffic from your computer",
    "access to this page has been denied",
    "checking your browser before accessing",
    "cf-browser-verification",
    "please verify you are a human",
]


def looks_like_bot_wall(html: str) -> bool:
    lowered = html.lower()
    if any(marker in lowered for marker in BOT_WALL_MARKERS):
        return True
    # A page this small mentioning a captcha is a challenge page, not a listing.
    return "captcha" in lowered and len(html) < 20_000


@dataclass
class PriceResult:
    price: float
    currency: str | None
    strategy: str


def parse_price_number(text: str) -> float:
    """Parse a price out of messy text, handling both 1,234.56 (US/SG/MY) and
    1.234.567 (ID/VN) grouping.

    For a price *range* like "S$12.90 - S$25.90" this returns the first (lowest)
    number, which is the cheapest variant on offer.
    """
    match = NUMBER_RE.search(text)
    if not match:
        raise ScrapeError(f"No number found in '{text.strip()[:80]}'")

    raw = re.sub(r"[\s ]", "", match.group(0))
    last_dot, last_comma = raw.rfind("."), raw.rfind(",")

    if last_dot == -1 and last_comma == -1:
        return float(raw)

    # Whichever separator comes last is the candidate decimal point.
    if last_dot > last_comma:
        dec_pos, thousands = last_dot, ","
    else:
        dec_pos, thousands = last_comma, "."

    # It is only a decimal point if 1-2 digits follow it; otherwise every
    # separator is grouping (Rp1.234.567).
    if len(raw) - dec_pos - 1 in (1, 2):
        integer = raw[:dec_pos].replace(thousands, "").replace(".", "").replace(",", "")
        return float(f"{integer or 0}.{raw[dec_pos + 1:]}")

    return float(re.sub(r"[.,]", "", raw))


def detect_currency(text: str, url: str) -> str | None:
    """Domain knowledge wins (amazon.sg is always SGD); otherwise read the text."""
    from_domain = currency_for(url)
    if from_domain:
        return from_domain
    iso = ISO_CODE_RE.search(text.upper())
    if iso:
        return iso.group(1)
    for symbol, code in CURRENCY_SYMBOLS:
        if symbol in text:
            return code
    return None


# --- strategies -----------------------------------------------------------

def _from_selector(soup: BeautifulSoup, selector: str) -> str | None:
    try:
        element = soup.select_one(selector)
    except Exception:  # an invalid CSS selector shouldn't kill the whole fetch
        return None
    if element is None:
        return None
    text = element.get_text(" ", strip=True) or element.get("content", "")
    return text or None


def _walk_for_price(node) -> tuple[str, str | None] | None:
    """Depth-first search through decoded JSON-LD for an offers price."""
    if isinstance(node, dict):
        for key in ("price", "lowPrice", "highPrice"):
            if key in node and node[key] not in (None, ""):
                return str(node[key]), node.get("priceCurrency")
        for value in node.values():
            found = _walk_for_price(value)
            if found:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _walk_for_price(item)
            if found:
                return found
    return None


def _from_json_ld(soup: BeautifulSoup) -> tuple[str, str | None] | None:
    for script in soup.find_all("script", type="application/ld+json"):
        if not script.string:
            continue
        try:
            data = json.loads(script.string)
        except (ValueError, TypeError):
            continue
        found = _walk_for_price(data)
        if found:
            return found
    return None


META_PRICE_KEYS = [
    ("property", "product:price:amount"),
    ("property", "og:price:amount"),
    ("itemprop", "price"),
    ("name", "twitter:data1"),
]
META_CURRENCY_KEYS = [
    ("property", "product:price:currency"),
    ("property", "og:price:currency"),
    ("itemprop", "priceCurrency"),
]


def _from_meta(soup: BeautifulSoup) -> tuple[str, str | None] | None:
    price = None
    for attr, value in META_PRICE_KEYS:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            price = tag["content"]
            break
    if price is None:
        return None
    currency = None
    for attr, value in META_CURRENCY_KEYS:
        tag = soup.find("meta", attrs={attr: value})
        if tag and tag.get("content"):
            currency = tag["content"]
            break
    return price, currency


# NOTE: Lazada's server HTML carries `pdt_price`, which is the crossed-out LIST
# price, not what you'd pay -- on a test item it read $589.00 while the page sold
# it for $345.50. It is deliberately NOT matched here: reporting a list price as
# the selling price would inflate every comparison and invent savings that don't
# exist. Lazada's real price is rendered client-side, so it needs a browser.
EMBEDDED_PRICE_PATTERNS = [
    re.compile(r'"salePrice"\s*:\s*\{[^{}]*?"text"\s*:\s*"([^"]+)"'),
    re.compile(r'"priceText"\s*:\s*"([^"]{1,30})"'),
    re.compile(r'"salePrice"\s*:\s*"?([\d.,]+)"?'),
    re.compile(r'"price"\s*:\s*"([^"]{1,30})"'),
]


def _from_embedded_json(html: str) -> str | None:
    """Lazada (and friends) render client-side but ship the price in a script blob.

    Those blobs are often JSON encoded *inside* a JS string, so the quotes arrive
    escaped (\\"pdt_price\\":\\"$589.00\\"). Try the raw text first, then a
    de-escaped copy, so both forms are covered.
    """
    for candidate_html in (html, html.replace('\\"', '"')):
        for pattern in EMBEDDED_PRICE_PATTERNS:
            match = pattern.search(candidate_html)
            if match:
                return match.group(1)
    return None


def _shopee_api(url: str, timeout: int) -> PriceResult | None:
    """Shopee product URLs end in -i.<shop>.<item>, which its own item API takes.

    Prices come back in "micros" (cents x 1000), hence the /100000.
    """
    ids = shopee_ids(url)
    if not ids:
        raise ScrapeError(
            "Shopee URL is missing the -i.<shop_id>.<item_id> part. "
            "Copy the full product URL from the address bar."
        )
    shop_id, item_id = ids
    host = urlparse(url).hostname

    endpoints = [
        f"https://{host}/api/v4/pdp/get_pc?item_id={item_id}&shop_id={shop_id}",
        f"https://{host}/api/v4/item/get?itemid={item_id}&shopid={shop_id}",
    ]
    headers = {**BROWSER_HEADERS, "Referer": url, "X-API-SOURCE": "pc",
               "Accept": "application/json"}

    last_problem = "no price field in the API response"
    blocked = False
    for endpoint in endpoints:
        try:
            resp = requests.get(endpoint, headers=headers, timeout=timeout)
            if resp.status_code in (403, 429):
                blocked = True
                last_problem = f"HTTP {resp.status_code}"
                continue
            resp.raise_for_status()
            payload = resp.json()
        except (requests.RequestException, ValueError) as exc:
            last_problem = f"{type(exc).__name__}: {exc}"
            continue

        for key in ("price", "price_min"):
            micros = _find_key(payload, key)
            if isinstance(micros, (int, float)) and micros > 0:
                return PriceResult(
                    price=round(micros / 100_000, 2),
                    currency=currency_for(url),
                    strategy="shopee-api",
                )

    if blocked:
        raise ScrapeError(
            f"Shopee refused the request ({last_problem}). Shopee blocks automated access from "
            "most networks, so this source may never work from here -- it is not a setup mistake "
            "on your side. Shopee's own Open Platform API is the supported route."
        )
    raise ScrapeError(f"Shopee API did not return a price ({last_problem})")


def _find_key(node, target: str):
    if isinstance(node, dict):
        if target in node and isinstance(node[target], (int, float)):
            return node[target]
        for value in node.values():
            found = _find_key(value, target)
            if found is not None:
                return found
    elif isinstance(node, list):
        for item in node:
            found = _find_key(item, target)
            if found is not None:
                return found
    return None


def _render_with_playwright(url: str, timeout: int, adapter=None) -> str | None:
    """Render the page in a real browser. Optional -- returns None if Playwright
    isn't installed, so the caller can fall back to a clear error message.

    Shops like Lazada only paint the real (discounted) price after their scripts
    run, so this waits for the price node rather than guessing a sleep duration.
    """
    try:
        import playwright.async_api  # noqa: F401
    except ImportError:
        return None
    from . import browser  # imports this module, so not at the top

    return browser.run(_render(url, timeout, adapter))


async def _render(url: str, timeout: int, adapter) -> str:
    from .browser import chromium, new_page

    async with chromium() as instance:
        page = await new_page(instance)
        await page.goto(url, timeout=timeout * 1000, wait_until="load")

        # Prefer waiting for the actual price element over a fixed sleep.
        for selector in (adapter.selectors if adapter else []):
            try:
                await page.wait_for_selector(selector, timeout=8000)
                break
            except Exception:
                continue
        else:
            await page.wait_for_timeout(6000)

        return await page.content()


# --- entry point ----------------------------------------------------------

def fetch_price(url: str, selector: str | None = None, timeout: int = 20) -> PriceResult:
    """Fetch the current price for `url`. Raises ScrapeError with a readable
    reason so a failed source is recorded rather than crashing a batch refresh."""
    adapter = adapter_for(url)

    if adapter.name == "Shopee":
        return _shopee_api(url, timeout)

    try:
        resp = requests.get(url, headers=BROWSER_HEADERS, timeout=timeout)
        html = resp.text
    except requests.RequestException as exc:
        raise ScrapeError(f"Request failed: {exc}") from exc

    if resp.status_code >= 400:
        # Big retailers dress up blocks as 404s and 503s, so read the body
        # before believing the status code.
        if looks_like_bot_wall(html):
            raise ScrapeError(
                f"{adapter.name} returned HTTP {resp.status_code} with a bot-check page. "
                "The shop is refusing automated access from this network -- the product may "
                "well exist. Not something a different selector can fix."
            )
        raise ScrapeError(f"Request failed: HTTP {resp.status_code} for {url}")

    result = _extract(html, url, selector, adapter)
    if result is not None:
        return result

    # Last resort: render the page in a real browser, if one is available.
    rendered = _render_with_playwright(url, timeout, adapter)
    browser_used = rendered is not None
    if rendered:
        result = _extract(rendered, url, selector, adapter, rendered=True)
        if result is not None:
            return result
        if looks_like_bot_wall(rendered):
            raise ScrapeError(
                f"{adapter.name} served a bot check even in a real browser. This shop is "
                "refusing automated access from this network."
            )

    if looks_like_bot_wall(html):
        raise ScrapeError(
            f"{adapter.name} served a bot check instead of the product page, so there is no "
            "price to read. This is the shop blocking automated access, not a selector problem "
            "-- a different selector won't help. Try again later, check the price manually, or "
            "use the shop's official API if you have access to one."
        )
    if adapter.needs_js:
        if browser_used:
            raise ScrapeError(
                f"Rendered {adapter.name} in a browser but found no price element. The listing "
                "may be unavailable or out of stock, or the shop changed its markup "
                "(the selectors live in app/adapters.py)."
            )
        raise ScrapeError(
            f"{adapter.name} renders prices with JavaScript and no price was found in the "
            "raw HTML. Install Playwright (pip install playwright && playwright install chromium) "
            "to let the tracker render the page."
        )
    raise ScrapeError(
        "Could not find a price on the page. Try supplying a CSS selector for the "
        "price element (right-click the price -> Inspect -> Copy selector)."
    )


def _extract(html: str, url: str, selector: str | None, adapter, rendered: bool = False):
    soup = BeautifulSoup(html, "html.parser")
    suffix = "+browser" if rendered else ""

    candidates: list[tuple[str, str, str | None]] = []  # (strategy, text, currency)

    if selector:
        text = _from_selector(soup, selector)
        if text:
            candidates.append(("your-selector", text, None))

    for adapter_selector in adapter.selectors:
        text = _from_selector(soup, adapter_selector)
        if text:
            candidates.append((f"{adapter.name.lower()}-css", text, None))
            break

    json_ld = _from_json_ld(soup)
    if json_ld:
        candidates.append(("json-ld", json_ld[0], json_ld[1]))

    meta = _from_meta(soup)
    if meta:
        candidates.append(("meta-tag", meta[0], meta[1]))

    embedded = _from_embedded_json(html)
    if embedded:
        candidates.append(("embedded-json", embedded, None))

    for strategy, text, currency in candidates:
        try:
            price = parse_price_number(text)
        except ScrapeError:
            continue
        if price <= 0:
            continue
        return PriceResult(
            price=price,
            currency=currency or detect_currency(text, url),
            strategy=strategy + suffix,
        )
    return None
