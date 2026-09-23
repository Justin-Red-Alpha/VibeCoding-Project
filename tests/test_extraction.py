"""Extraction tests against realistic page fixtures.

These cover the parsing logic, which we control. Whether a given shop lets us
fetch the page at all is a separate question (see the README's reality check).

Run: python -m tests.test_extraction
"""

import sys

from app.scraper import _extract, parse_price_number, detect_currency, looks_like_bot_wall
from app.adapters import adapter_for, shopee_ids
from app.analysis import analyze, best_price_series, compare_sources, dominant_currency

FAILURES: list[str] = []


def check(label, got, expected):
    ok = got == expected
    if not ok:
        FAILURES.append(f"{label}: got {got!r}, expected {expected!r}")
    print(f"  {'OK  ' if ok else 'FAIL'} {label}: {got!r}")


def check_that(label, condition, detail=""):
    if not condition:
        FAILURES.append(f"{label} {detail}")
    print(f"  {'OK  ' if condition else 'FAIL'} {label} {detail}")


def section(title):
    print(f"\n{title}")


# --- extraction strategies -------------------------------------------------

AMAZON_HTML = """
<html><body>
  <div id="corePrice_feature_div">
    <span class="a-price"><span class="a-offscreen">S$449.00</span></span>
  </div>
</body></html>
"""

JSON_LD_HTML = """
<html><head>
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"Thing",
 "offers":{"@type":"Offer","price":"1299.90","priceCurrency":"MYR"}}
</script>
</head><body></body></html>
"""

JSON_LD_NESTED_HTML = """
<html><head>
<script type="application/ld+json">
{"@graph":[{"@type":"BreadcrumbList"},
 {"@type":"Product","offers":{"@type":"AggregateOffer","lowPrice":"88.50","priceCurrency":"SGD"}}]}
</script>
</head><body></body></html>
"""

META_HTML = """
<html><head>
  <meta property="product:price:amount" content="2499000">
  <meta property="product:price:currency" content="IDR">
</head><body></body></html>
"""

LAZADA_EMBEDDED_HTML = """
<html><body><script>
window.__moduleData__ = {"data":{"root":{"fields":{"skuInfos":{"0":{"price":
{"salePrice":{"text":"RM1,234.00","value":1234.0}}}}}}}};
</script></body></html>
"""

SELECTOR_HTML = '<html><body><p class="price_color">£51.77</p></body></html>'


def test_extraction():
    section("Extraction strategies")

    r = _extract(AMAZON_HTML, "https://www.amazon.sg/dp/X", None, adapter_for("https://www.amazon.sg/dp/X"))
    check("amazon css selector", (r.price, r.currency, r.strategy), (449.0, "SGD", "amazon-css"))

    generic = adapter_for("https://shop.example.com/p")
    r = _extract(JSON_LD_HTML, "https://shop.example.com/p", None, generic)
    check("json-ld flat", (r.price, r.currency, r.strategy), (1299.90, "MYR", "json-ld"))

    r = _extract(JSON_LD_NESTED_HTML, "https://shop.example.com/p", None, generic)
    check("json-ld @graph/AggregateOffer", (r.price, r.currency, r.strategy), (88.50, "SGD", "json-ld"))

    r = _extract(META_HTML, "https://shop.example.com/p", None, generic)
    check("meta tag", (r.price, r.currency, r.strategy), (2499000.0, "IDR", "meta-tag"))

    lz = adapter_for("https://www.lazada.com.my/products/x-i1.html")
    r = _extract(LAZADA_EMBEDDED_HTML, "https://www.lazada.com.my/products/x-i1.html", None, lz)
    check("lazada embedded json", (r.price, r.currency), (1234.0, "MYR"))

    r = _extract(SELECTOR_HTML, "https://books.toscrape.com/x", ".price_color", generic)
    check("user selector", (r.price, r.strategy), (51.77, "your-selector"))

    # A selector that matches nothing must fall through, not crash.
    r = _extract(JSON_LD_HTML, "https://shop.example.com/p", ".nope", generic)
    check("bad selector falls through", r.strategy, "json-ld")

    # An invalid selector must not kill the fetch either.
    r = _extract(JSON_LD_HTML, "https://shop.example.com/p", "!!!", generic)
    check("invalid selector survives", r.strategy, "json-ld")

    check("no price found returns None", _extract("<html></html>", "https://x.com/p", None, generic), None)


def test_numbers():
    section("Number parsing")
    for text, expected in [
        ("$51.77", 51.77), ("S$12.90", 12.90), ("RM 1,234.56", 1234.56),
        ("Rp1.234.567", 1234567.0), ("₫1.500.000", 1500000.0), ("1.234,56 €", 1234.56),
        ("S$12.90 - S$25.90", 12.90), ("₱1,299", 1299.0), ("1,234", 1234.0),
    ]:
        check(f"parse {text}", parse_price_number(text), expected)


def test_currency():
    section("Currency detection")
    check("amazon.sg", detect_currency("$449", "https://www.amazon.sg/dp/X"), "SGD")
    check("lazada.com.my", detect_currency("RM99", "https://www.lazada.com.my/p"), "MYR")
    check("shopee.co.id", detect_currency("Rp1", "https://shopee.co.id/p"), "IDR")
    check("unknown site by symbol", detect_currency("RM99", "https://shop.example.com/p"), "MYR")
    check("unknown site by code", detect_currency("THB 50", "https://shop.example.com/p"), "THB")


def test_shopee_ids():
    section("Shopee URL parsing")
    check("standard url", shopee_ids("https://shopee.sg/Sony-WH1000XM5-i.123456.7891011"), ("123456", "7891011"))
    check("with query string", shopee_ids("https://shopee.com.my/x-i.1.2?sp_atk=abc"), ("1", "2"))
    check("not a product url", shopee_ids("https://shopee.sg/search?keyword=x"), None)


def test_bot_wall():
    section("Bot-wall detection")
    check("amazon robot check", looks_like_bot_wall("<html>Robot Check ... </html>"), True)
    check("short captcha page", looks_like_bot_wall("<html>captcha</html>"), True)
    check("real product page", looks_like_bot_wall("<html>" + "x" * 50000 + "buy now</html>"), False)


# --- comparison & decisions ------------------------------------------------

def _snap(source_id, price, currency, hour, error=None):
    return {"source_id": source_id, "price": price, "currency": currency,
            "fetched_at": f"2026-09-2{hour}T10:00:00+00:00", "error": error}


def test_comparison():
    section("Cross-retailer comparison")
    sources = [
        {"id": 1, "retailer": "Amazon", "url": "https://amazon.sg/x"},
        {"id": 2, "retailer": "Lazada", "url": "https://lazada.sg/x"},
        {"id": 3, "retailer": "Shopee", "url": "https://shopee.sg/x"},
    ]
    latest = {
        1: {"price": 449.0, "currency": "SGD", "fetched_at": "t", "error": None},
        2: {"price": 399.0, "currency": "SGD", "fetched_at": "t", "error": None},
        3: {"price": None, "currency": None, "fetched_at": None, "error": "blocked"},
    }
    c = compare_sources(sources, latest, "SGD")
    check("cheapest retailer", c.cheapest.retailer, "Lazada")
    check("dearest retailer", c.dearest.retailer, "Amazon")
    check("savings", c.savings, 50.0)
    check("savings pct", c.savings_pct, 11.1)
    check("failed source kept", len(c.sources), 3)
    check("not mixed currency", c.mixed_currency, False)

    # A PHP listing must not be declared "cheapest" just because 4000 < 449.
    latest[3] = {"price": 4000.0, "currency": "PHP", "fetched_at": "t", "error": None}
    c = compare_sources(sources, latest, "SGD")
    check("mixed currency flagged", c.mixed_currency, True)
    check("off-currency not cheapest", c.cheapest.retailer, "Lazada")
    off = [s for s in c.sources if s.retailer == "Shopee"][0]
    check("off-currency marked", off.off_currency, True)


def test_best_series():
    section("Best-price-over-time series")
    snaps = [
        _snap(1, 449.0, "SGD", 1), _snap(2, 399.0, "SGD", 1),   # day 1: best 399
        _snap(1, 429.0, "SGD", 2), _snap(2, 449.0, "SGD", 2),   # day 2: best 429
        _snap(1, 350.0, "SGD", 3), _snap(2, None, None, 3, "err"),  # day 3: best 350
    ]
    check("min per time bucket", best_price_series(snaps, "SGD"), [399.0, 429.0, 350.0])

    mixed = snaps + [_snap(3, 4000.0, "PHP", 1)]
    check("excludes other currency", best_price_series(mixed, "SGD"), [399.0, 429.0, 350.0])
    check("dominant currency", dominant_currency(mixed), "SGD")


def test_verdicts():
    section("Decision logic")
    check("no data", analyze([], None).label, "NO_DATA")
    check("too few points", analyze([10.0, 9.0], None).label, "NOT_ENOUGH_DATA")
    check("target met beats everything", analyze([10.0], 12.0).label, "BUY_NOW")
    check("flat history", analyze([10.0, 10.0, 10.0], None).label, "NEUTRAL")
    check("historically cheap", analyze([20.0, 18.0, 15.0, 10.0], None).label, "BUY_NOW")
    check("historically dear", analyze([10.0, 12.0, 15.0, 20.0], None).label, "WAIT")
    check("middling", analyze([10.0, 20.0, 30.0, 40.0, 25.0], None).label, "NEUTRAL")




# --- currency conversion ---------------------------------------------------

def _fake_converter(rates, target):
    """Stand-in for fx.make_converter, so these tests don't hit the network."""
    def to_display(amount, from_currency):
        if amount is None or not from_currency:
            return None
        if from_currency == target:
            return round(amount, 2)
        if from_currency not in rates or target not in rates:
            return None
        return round(amount * (rates[target] / rates[from_currency]), 2)
    return to_display


RATES = {"USD": 1.0, "SGD": 1.28, "MYR": 4.09, "PHP": 62.8}


def test_conversion_comparison():
    section("Comparison with currency conversion")
    sources = [
        {"id": 1, "retailer": "Lazada SG", "url": "https://lazada.sg/x"},
        {"id": 2, "retailer": "Lazada MY", "url": "https://lazada.com.my/x"},
        {"id": 3, "retailer": "Shopee PH", "url": "https://shopee.ph/x"},
    ]
    latest = {
        1: {"price": 345.50, "currency": "SGD", "fetched_at": "t", "error": None},
        2: {"price": 1558.00, "currency": "MYR", "fetched_at": "t", "error": None},
        3: {"price": 19999.0, "currency": "PHP", "fetched_at": "t", "error": None},
    }
    to_sgd = _fake_converter(RATES, "SGD")
    c = compare_sources(sources, latest, "SGD", to_display=to_sgd, display_currency="SGD")

    check("conversion reported", c.converted, True)
    check("comparison currency", c.comparison_currency, "SGD")
    # MYR 1558 ~ SGD 487; PHP 19999 ~ SGD 407; so SG at 345.50 wins.
    check("cheapest across currencies", c.cheapest.retailer, "Lazada SG")
    check("dearest across currencies", c.dearest.retailer, "Lazada MY")
    check_that("savings in display currency", c.savings and 130 < c.savings < 150, f"({c.savings})")

    my = [s for s in c.sources if s.retailer == "Lazada MY"][0]
    check_that("converted figure present", my.display_price and 480 < my.display_price < 495,
               f"({my.display_price})")
    check("original price untouched", my.price, 1558.00)
    check("original currency untouched", my.currency, "MYR")
    check("foreign listing now comparable", my.off_currency, False)


def test_conversion_without_rates():
    section("Comparison when a rate is missing")
    sources = [
        {"id": 1, "retailer": "Lazada SG", "url": "https://lazada.sg/x"},
        {"id": 2, "retailer": "Shopee VN", "url": "https://shopee.vn/x"},
    ]
    latest = {
        1: {"price": 345.50, "currency": "SGD", "fetched_at": "t", "error": None},
        2: {"price": 8500000.0, "currency": "VND", "fetched_at": "t", "error": None},
    }
    # VND deliberately absent from RATES.
    c = compare_sources(sources, latest, "SGD",
                        to_display=_fake_converter(RATES, "SGD"), display_currency="SGD")
    vnd = [s for s in c.sources if s.retailer == "Shopee VN"][0]
    check("unconvertible marked off-currency", vnd.off_currency, True)
    check("unconvertible never wins", c.cheapest.retailer, "Lazada SG")


def test_series_with_conversion():
    section("Best-price series with conversion")
    snaps = [
        _snap(1, 345.50, "SGD", 1), _snap(2, 1558.0, "MYR", 1),   # SGD 345.50 vs ~487
        _snap(1, 400.00, "SGD", 2), _snap(2, 1200.0, "MYR", 2),   # SGD 400 vs ~375 -> MY wins
    ]
    series = best_price_series(snaps, "SGD", to_display=_fake_converter(RATES, "SGD"))
    check("two buckets", len(series), 2)
    check_that("bucket 1 takes SGD listing", abs(series[0] - 345.50) < 0.01, f"({series[0]})")
    check_that("bucket 2 takes converted MYR", 370 < series[1] < 380, f"({series[1]})")

    # Without a converter, foreign prices are skipped entirely (old behaviour).
    plain = best_price_series(snaps, "SGD")
    check("unconverted ignores foreign", plain, [345.50, 400.00])


for test in (test_extraction, test_numbers, test_currency, test_shopee_ids, test_bot_wall,
             test_comparison, test_best_series, test_verdicts,
             test_conversion_comparison, test_conversion_without_rates, test_series_with_conversion):
    test()

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("All extraction, comparison and decision tests passed.")
