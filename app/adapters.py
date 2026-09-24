"""Per-retailer knowledge: which domain is which shop, what currency it prices
in, and where the price hides on the page.

Adding a new retailer = adding one entry to ADAPTERS. Nothing else changes.
"""

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass
class Adapter:
    name: str
    # Domain fragments that identify this retailer (matched against the hostname).
    domains: list[str]
    # CSS selectors tried in order. First one that yields a number wins.
    selectors: list[str] = field(default_factory=list)
    # Maps a hostname suffix -> currency code, so amazon.sg is SGD but amazon.com is USD.
    currency_by_domain: dict[str, str] = field(default_factory=dict)
    default_currency: str | None = None
    # True when the plain HTML genuinely does not contain the price and only a
    # real browser (or a site API) can get it. Drives the error message we show.
    needs_js: bool = False
    notes: str = ""
    # Marks a URL as an actual product page, so discovery can throw away the
    # category, tag and search pages that search engines love to return.
    product_url_re: str | None = None
    # Domain used when searching this retailer for a product by name.
    search_domain: str | None = None
    # Searching the shop's OWN search page, rendered in a browser. The result
    # cards already carry prices, so a hit here needs no product-page fetch.
    search_path: str | None = None        # e.g. "/s?k={q}"
    search_card: str | None = None        # one result card
    search_title: str | None = None       # title within a card
    search_price: str | None = None       # price within a card
    search_link: str = "a[href]"          # product link within a card
    # The shop's own id for an item (first regex group) and the canonical path
    # built from it. Lets the price archive find copies of the SAME listing filed
    # under another URL shape (Amazon: a product slug vs /dp/<ASIN>).
    item_id_re: str | None = None
    canonical_path: str | None = None     # e.g. "/dp/{id}"

    @property
    def supports_site_search(self) -> bool:
        return bool(self.search_path and self.search_card)

    def search_url(self, domain: str, query: str) -> str:
        from urllib.parse import quote_plus
        return f"https://www.{domain}{self.search_path.format(q=quote_plus(query))}"

    def is_product_url(self, url: str) -> bool:
        if not self.product_url_re:
            return True
        return re.search(self.product_url_re, url) is not None

    def currency_for(self, host: str) -> str | None:
        for suffix, code in sorted(self.currency_by_domain.items(), key=lambda kv: -len(kv[0])):
            if host.endswith(suffix):
                return code
        return self.default_currency


AMAZON = Adapter(
    name="Amazon",
    domains=["amazon."],
    selectors=[
        ".a-price .a-offscreen",
        "#corePrice_feature_div .a-offscreen",
        "#corePriceDisplay_desktop_feature_div .a-offscreen",
        "#priceblock_ourprice",
        "#priceblock_dealprice",
        "#price_inside_buybox",
    ],
    currency_by_domain={
        "amazon.com": "USD",
        "amazon.sg": "SGD",
        "amazon.co.uk": "GBP",
        "amazon.de": "EUR",
        "amazon.fr": "EUR",
        "amazon.es": "EUR",
        "amazon.it": "EUR",
        "amazon.co.jp": "JPY",
        "amazon.in": "INR",
        "amazon.com.au": "AUD",
        "amazon.ca": "CAD",
        "amazon.com.br": "BRL",
        "amazon.ae": "AED",
        "amazon.sa": "SAR",
    },
    notes="Price is in the server-rendered HTML, but Amazon serves bot checks if you poll often.",
    product_url_re=r"/(?:dp|gp/product)/[A-Z0-9]{10}",
    item_id_re=r"/(?:dp|gp/product)/([A-Z0-9]{10})",
    canonical_path="/dp/{id}",
    search_domain="amazon.sg",
    search_path="/s?k={q}",
    search_card='[data-component-type="s-search-result"]',
    # Each card has two h2s (brand, then product name); the container holds both.
    search_title='[data-cy="title-recipe"]',
    search_price=".a-price .a-offscreen",
    search_link="h2 a, a.a-link-normal",
)

LAZADA = Adapter(
    name="Lazada",
    domains=["lazada."],
    selectors=[
        # Current markup (2026). The salePrice node is what you'd actually pay;
        # originalPrice is the struck-through one, so never match that.
        ".pdp-v2-product-price-content-salePrice",
        ".pdp-v2-product-price-content-salePrice-amount",
        # Older markup, kept as a fallback.
        ".pdp-price_type_normal",
        ".pdp-price",
    ],
    currency_by_domain={
        "lazada.sg": "SGD",
        "lazada.com.my": "MYR",
        "lazada.co.id": "IDR",
        "lazada.com.ph": "PHP",
        "lazada.vn": "VND",
        "lazada.co.th": "THB",
    },
    needs_js=True,
    notes=(
        "Server HTML only carries the crossed-out list price; the price you'd actually "
        "pay is rendered client-side, so Lazada needs Playwright."
    ),
    product_url_re=r"/products/.*-i\d+",
    search_domain="lazada.sg",
    search_path="/catalog/?q={q}",
    search_card='[data-qa-locator="product-item"]',
    search_title=".RfADt a, .RfADt",
    search_price=".ooOxS",
)

SHOPEE = Adapter(
    name="Shopee",
    domains=["shopee."],
    selectors=[],  # Class names are obfuscated and rotate -- selectors are useless here.
    currency_by_domain={
        "shopee.sg": "SGD",
        "shopee.com.my": "MYR",
        "shopee.co.id": "IDR",
        "shopee.ph": "PHP",
        "shopee.vn": "VND",
        "shopee.co.th": "THB",
        "shopee.tw": "TWD",
        "shopee.com.br": "BRL",
    },
    needs_js=True,
    notes="HTML is an empty shell. We read the item API that the page itself calls.",
    product_url_re=r"-i\.\d+\.\d+",
    search_domain="shopee.sg",
)

EBAY = Adapter(
    name="eBay",
    domains=["ebay."],
    selectors=[
        ".x-price-primary .ux-textspans",
        "#prcIsum",
        "#mm-saleDscPrc",
        "[itemprop='price']",
    ],
    currency_by_domain={
        "ebay.com": "USD",
        "ebay.co.uk": "GBP",
        "ebay.de": "EUR",
        "ebay.com.au": "AUD",
        "ebay.com.sg": "SGD",
        "ebay.com.my": "MYR",
    },
    notes="Server-rendered and scraper-friendly. The most reliable of the big marketplaces.",
    product_url_re=r"/itm/\d+",
    search_domain="ebay.com.sg",
    search_path="/sch/i.html?_nkw={q}",
    search_card="li.s-item, li.s-card",
    search_title=".s-item__title, .s-card__title",
    search_price=".s-item__price, .s-card__price",
)

QOO10 = Adapter(
    name="Qoo10",
    domains=["qoo10."],
    selectors=["#price_dc", ".price", "strong.dc_price"],
    currency_by_domain={"qoo10.sg": "SGD", "qoo10.my": "MYR"},
    product_url_re=r"/g/\d+",
    search_domain="qoo10.sg",
)

ADAPTERS: list[Adapter] = [AMAZON, LAZADA, SHOPEE, EBAY, QOO10]

# A stand-in for any site we have no specific knowledge of. The generic
# strategies (JSON-LD, meta tags, a user-supplied selector) still apply.
GENERIC = Adapter(name="Other", domains=[], selectors=[])


def adapter_for(url: str) -> Adapter:
    host = (urlparse(url).hostname or "").lower()
    for adapter in ADAPTERS:
        if any(fragment in host for fragment in adapter.domains):
            return adapter
    return GENERIC


def retailer_label(url: str) -> str:
    """A name to show in the UI. For shops we don't have an adapter for, the
    hostname beats a generic "Other" -- you need to know *which* shop it is."""
    adapter = adapter_for(url)
    if adapter is not GENERIC:
        return adapter.name
    host = (urlparse(url).hostname or "unknown").lower()
    return host[4:] if host.startswith("www.") else host


def currency_for(url: str) -> str | None:
    host = (urlparse(url).hostname or "").lower()
    return adapter_for(url).currency_for(host)


# --- Shopee ---------------------------------------------------------------

SHOPEE_ID_RE = re.compile(r"-i\.(\d+)\.(\d+)")


def shopee_ids(url: str) -> tuple[str, str] | None:
    """Shopee product URLs end in `-i.<shop_id>.<item_id>`, which is exactly what
    its item API wants. Returns (shop_id, item_id)."""
    match = SHOPEE_ID_RE.search(url)
    if not match:
        return None
    return match.group(1), match.group(2)
