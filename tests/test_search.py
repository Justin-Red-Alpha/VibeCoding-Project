"""Tests for product discovery: matching, filtering and throttle detection.

Run: python -m tests.test_search
"""

import sys

from app.adapters import adapter_for
from app.search.base import Candidate
from app.search.matching import model_tokens, score_candidate, flag_price_outliers
from app.search.providers import _canonical, _decode_ddg_url, _looks_throttled
from app.main import _discovery_summary, MIN_HEADLINE_SCORE

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


def test_model_tokens():
    section("Model number extraction")
    # Regression: squashing the whole string merged "sony" into the model number,
    # so a title with an extra word in between never matched.
    check("hyphenated model", model_tokens("Sony WH-1000XM5"), {"wh1000xm5"})
    check("extra words don't merge",
          model_tokens("Sony Singapore WH-1000XM5 Wireless"), {"wh1000xm5"})
    check("already squashed", model_tokens("Sony WH1000XM5"), {"wh1000xm5"})
    check("short noise ignored", model_tokens("Cable x1 v2"), set())
    check("no model at all", model_tokens("Wireless Headphones"), set())


def test_scoring():
    section("Match scoring")
    q = "Sony WH-1000XM5"

    exact, _ = score_candidate(q, "Sony WH-1000XM5 Wireless Noise-Cancelling Headphones")
    spaced, _ = score_candidate(q, "Sony Singapore WH-1000XM5 WH1000XM5 Wireless")
    squashed, _ = score_candidate(q, "Sony WH1000XM5 Over-Ear Bluetooth Headphones")
    check_that("exact title scores high", exact >= 0.9, f"({exact})")
    check_that("extra words still high", spaced >= 0.9, f"({spaced})")
    check_that("squashed model still matches", squashed >= 0.45, f"({squashed})")

    case, case_flags = score_candidate(q, "Carrying Case for Sony WH-1000XM5 Hard Shell Cover")
    pads, _ = score_candidate(q, "Replacement Ear Pads Cushions for Sony WH-1000XM5")
    cable, _ = score_candidate(q, "USB-C Charging Cable compatible with Sony WH-1000XM5")
    check_that("case is low confidence", case < 0.45, f"({case})")
    check_that("earpads low confidence", pads < 0.45, f"({pads})")
    check_that("cable low confidence", cable < 0.45, f"({cable})")
    check_that("accessory is explained", any("accessory" in f for f in case_flags), str(case_flags))
    # The important one: an accessory must never outrank a genuine listing.
    check_that("accessory ranks below product", case < squashed, f"({case} < {squashed})")

    xm4, xm4_flags = score_candidate(q, "Sony WH-1000XM4 Wireless Noise Cancelling Headphones")
    wf, _ = score_candidate(q, "Sony WF-1000XM5 Truly Wireless Earbuds")
    check_that("wrong generation rejected", xm4 < 0.3, f"({xm4})")
    check_that("wrong product line rejected", wf < 0.3, f"({wf})")
    check_that("mismatch is explained",
               any("model" in f for f in xm4_flags), str(xm4_flags))

    _, refurb_flags = score_candidate(q, "Sony WH-1000XM5 Refurbished Open Box")
    check_that("refurbished flagged", any("refurb" in f for f in refurb_flags), str(refurb_flags))


def _cand(price, title="Sony WH-1000XM5"):
    return Candidate(title=title, url=f"https://x.test/{price}", retailer="x",
                     provider="t", price=price, score=1.0)


def test_outliers():
    section("Price outlier flagging")
    cands = [_cand(345.0), _cand(359.0), _cand(340.0), _cand(29.0), _cand(1500.0)]
    flag_price_outliers(cands)
    cheap, dear = cands[3], cands[4]
    check_that("suspiciously cheap flagged", any("below" in f for f in cheap.flags), str(cheap.flags))
    check_that("suspiciously dear flagged", any("above" in f for f in dear.flags), str(dear.flags))
    check_that("normal price unflagged", cands[0].flags == [], str(cands[0].flags))

    # Too little data to have an opinion.
    pair = [_cand(10.0), _cand(900.0)]
    flag_price_outliers(pair)
    check("no flags below 3 prices", [c.flags for c in pair], [[], []])


def test_product_url_filter():
    section("Product URL filtering")
    cases = [
        ("https://www.lazada.sg/products/sony-x-i2322132553.html", True),
        ("https://www.lazada.sg/tag/sony-wh-1000xm5/", False),
        ("https://www.lazada.sg/shop-ce-headphones/", False),
        ("https://www.amazon.sg/Sony-WH-1000XM5/dp/B09XS7JWHH", True),
        ("https://www.amazon.sg/s?k=sony", False),
        ("https://shopee.sg/Sony-WH1000XM5-i.123.456", True),
        ("https://shopee.sg/search?keyword=sony", False),
        ("https://www.ebay.com.sg/itm/123456789", True),
        ("https://www.ebay.com.sg/sch/i.html?_nkw=sony", False),
    ]
    for url, expected in cases:
        check(url.split("/", 3)[-1][:42], adapter_for(url).is_product_url(url), expected)


def test_url_handling():
    section("Result URL handling")
    check("mobile host dedupes with www",
          _canonical("https://h5.lazada.sg/products/x-i1.html"),
          _canonical("https://www.lazada.sg/products/x-i1.html"))
    check("query string ignored",
          _canonical("https://shopee.sg/x-i.1.2?sp_atk=abc"),
          _canonical("https://shopee.sg/x-i.1.2"))
    check("ddg redirect decoded",
          _decode_ddg_url("//duckduckgo.com/l/?uddg=https%3A%2F%2Fwww.lazada.sg%2Fp.html&rut=x"),
          "https://www.lazada.sg/p.html")
    check("sponsored result dropped",
          _decode_ddg_url("https://duckduckgo.com/y.js?ad_domain=ebay.com"), None)


def test_headline_price_ignores_poor_matches():
    section("Headline price excludes doubtful matches")
    # Regression: a search for WH-1000XM5 returned a WH-CH520 at SGD 17.69 and the
    # banner announced "best price SGD 17.69, save 96%" -- a different, cheaper
    # product presented as the deal. Only plausible matches may set the headline.
    query = "Sony WH-1000XM5"
    titles_prices = [
        ("Sony WH-1000XM5 Wireless Noise Cancelling Headphones", 311.00),
        ("Sony WH-1000XM5 Wireless Noise-Cancelling Headphones", 443.70),
        ("100% Original Sony WH-1000XM5 Noise Cancelling Headphones", 407.00),
        ("Original Sony WH-CH520 TWS Wireless Bluetooth Headphones", 17.69),
    ]
    candidates = []
    for i, (title, price) in enumerate(titles_prices):
        c = Candidate(title=title, url=f"https://shop.test/{i}", retailer="Lazada",
                      provider="t", price=price, currency="SGD")
        c.index = i
        c.score, c.flags = score_candidate(query, title)
        candidates.append(c)

    summary = _discovery_summary(candidates, None)
    check("headline is the real product", summary["best_price"], 311.00)
    check_that("outlier marked price_suspect", candidates[3].price_suspect,
               f"({candidates[3].flags})")
    check_that("wrong model excluded", summary["best_price"] != 17.69,
               f"(got {summary['best_price']})")
    check_that("no fabricated mega-saving", summary.get("savings_pct", 0) < 50,
               f"({summary.get('savings_pct')}%)")
    check_that("cheap wrong model still scored low",
               candidates[3].score < MIN_HEADLINE_SCORE, f"({candidates[3].score})")
    # It must remain visible in its shop list, just not headline the page.
    check("doubtful listing still present", len(candidates), 4)


def test_headline_ignores_suspect_price_despite_good_title():
    section("Headline excludes a matching title with an implausible price")
    # Real case: an Amazon listing titled "Sony WH-1000XM5 Wireless
    # Noise-Cancelling Headphones" priced SGD 38.60 among listings around SGD 270-440.
    # The page flags it "probably not the same item" -- so calling it the best price
    # would contradict the app's own warning and invent a 91% saving.
    query = "Sony WH-1000XM5"
    data = [
        ("Sony WH-1000XM5 Noise Cancelling Wireless Over-Ear Headphones", 269.58),
        ("Sony WH-1000XM5 Wireless Noise Cancelling Headphones", 443.70),
        ("Sony WH-1000XM5 Wireless Noise-Cancelling Headphones", 210.39),
        ("Sony WH-1000XM5 Wireless Noise-Cancelling Headphones", 38.60),
    ]
    candidates = []
    for i, (title, price) in enumerate(data):
        c = Candidate(title=title, url=f"https://shop.test/{i}", retailer="Amazon",
                      provider="t", price=price, currency="SGD")
        c.index = i
        c.score, c.flags = score_candidate(query, title)
        candidates.append(c)

    summary = _discovery_summary(candidates, None)
    check_that("suspiciously cheap one flagged", candidates[3].price_suspect,
               f"({candidates[3].flags})")
    check("headline is a plausible price", summary["best_price"], 210.39)
    check_that("not the 38.60 listing", summary["best_price"] != 38.60,
               f"(got {summary['best_price']})")
    check_that("saving stays believable", summary.get("savings_pct", 0) < 60,
               f"({summary.get('savings_pct')}%)")


def test_throttle_detection():
    section("Search throttle detection")
    # A throttled response looks like a normal page unless you check for it --
    # the failure mode is silently reporting "no products found".
    check("anomaly page", _looks_throttled(202, "<html>anomaly detected</html>"), True)
    check("unusual traffic", _looks_throttled(200, "<html>unusual traffic</html>"), True)
    check("202 with no results", _looks_throttled(202, "<html>nothing here</html>"), True)
    check("real results page",
          _looks_throttled(200, '<a class="result__a" href="x">Sony</a>'), False)


for test in (test_model_tokens, test_scoring, test_outliers,
             test_product_url_filter, test_url_handling,
             test_headline_price_ignores_poor_matches,
             test_headline_ignores_suspect_price_despite_good_title,
             test_throttle_detection):
    test()

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("All discovery tests passed.")
