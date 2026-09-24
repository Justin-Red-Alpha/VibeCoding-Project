"""Archived price history: matching, reading, filtering and storing it honestly.

Offline. The archive is faked: a `get` callable serves fixture CDX JSON and
fixture archived pages, and a throwaway SQLite file stands in for data/app.db.

Run: python -m tests.test_history
"""

import json
import logging
import sys
import tempfile
from pathlib import Path

import requests

from app import database as db
from app import history
from app.adapters import adapter_for
from app.scraper import extract_from_html

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


# --- a throwaway database ----------------------------------------------------

_tmp = tempfile.TemporaryDirectory()
_REAL_DB, db.DB_PATH = db.DB_PATH, Path(_tmp.name) / "test.db"
assert db.DB_PATH != _REAL_DB, "tests must never touch data/app.db"


def fresh_db():
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    db.init_db()


# --- fixtures ----------------------------------------------------------------

def amazon_page(amount: str) -> str:
    """Same shape as the live Amazon page the extractor reads (corePrice block)."""
    return (f'<html><body><div id="corePrice_feature_div"><span class="a-price">'
            f'<span class="a-offscreen">{amount}</span></span></div></body></html>')


# Lazada's server HTML: the only number is `pdt_price`, the crossed-out list price.
LAZADA_ARCHIVED = ('<html><body><script>var pageData = {"pdt_price":"$589.00",'
                   '"pdt_name":"Sony WH-1000XM5"};</script></body></html>')


# --- storage ---------------------------------------------------------------------

def test_storage():
    section("Archived observations are snapshots with provenance")
    # An older database: no provenance or history columns yet.
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    conn = db.get_connection()
    conn.executescript("""
        CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            target_price REAL, currency TEXT, created_at TEXT NOT NULL);
        CREATE TABLE sources (id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
            retailer TEXT NOT NULL, url TEXT NOT NULL, price_selector TEXT, created_at TEXT NOT NULL);
        CREATE TABLE price_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
            price REAL, currency TEXT, strategy TEXT, fetched_at TEXT NOT NULL, error TEXT);
        INSERT INTO products (name, created_at) VALUES ('Headphones', '2026-09-01T00:00:00+00:00');
        INSERT INTO sources (product_id, retailer, url, created_at)
            VALUES (1, 'Amazon', 'https://www.amazon.com/dp/B09XS7JWHH', '2026-09-01T00:00:00+00:00');
        INSERT INTO price_snapshots (source_id, price, currency, strategy, fetched_at)
            VALUES (1, 300.0, 'USD', 'amazon-css', '2026-09-01T00:00:00+00:00');
    """)
    conn.commit()
    conn.close()
    db.init_db()
    db.init_db()  # idempotent

    old = db.get_snapshots(1)[0]
    check("old row kept", (old["price"], old["currency"]), (300.0, "USD"))
    check("old row reads as live", old["origin"], None)
    source = db.get_source(1)
    check("history columns added", (source["history_checked_at"], source["history_note"]), (None, None))

    ref = "https://web.archive.org/web/20240701000000id_/https://www.amazon.com/dp/B09XS7JWHH"
    db.add_snapshot(1, 196.23, "USD", "wayback:amazon-css",
                    fetched_at="2024-07-01T00:00:00+00:00", origin="wayback", origin_ref=ref)
    archived = [s for s in db.get_snapshots(1) if s["origin"] == "wayback"][0]
    check("archived keeps its capture time", archived["fetched_at"], "2024-07-01T00:00:00+00:00")
    check("ordered by observation time", [s["price"] for s in db.get_snapshots(1)], [196.23, 300.0])
    check("origin refs listed", db.get_origin_refs(1), {ref})

    db.set_history_note(1, "12 archived prices found")
    source = db.get_source(1)
    check("note stored", source["history_note"], "12 archived prices found")
    check_that("check time stored", bool(source["history_checked_at"]))


# --- reading archived HTML -----------------------------------------------------------

def test_extract_from_html():
    section("Archived HTML is read without a browser, and never for a list price")
    r = extract_from_html(amazon_page("S$449.00"), "https://www.amazon.sg/dp/B0TEST0001")
    check("amazon price read", (r.price, r.currency, r.strategy), (449.0, "SGD", "amazon-css"))
    check("lazada list price never read",
          extract_from_html(LAZADA_ARCHIVED, "https://www.lazada.sg/products/x-i123-s456.html"), None)
    check("empty page", extract_from_html("<html></html>", "https://www.amazon.com/dp/B0TEST0001"), None)


# --- matching -------------------------------------------------------------------------

SLUG_URL = "https://www.amazon.com/Sony-WH-1000XM5-Canceling-Headphones-Hands-Free/dp/B09XS7JWHH"


def test_archive_urls():
    section("Matching is exact: the listing's own URL and its canonical form, same host")
    amazon = adapter_for(SLUG_URL)
    check("slug URL + canonical", history.archive_urls(SLUG_URL + "?ref=sr_1_1&th=1", amazon),
          [SLUG_URL, "https://www.amazon.com/dp/B09XS7JWHH"])
    check("already canonical: listed once",
          history.archive_urls("https://www.amazon.com/dp/B09XS7JWHH?psc=1", amazon),
          ["https://www.amazon.com/dp/B09XS7JWHH"])
    check("gp/product becomes /dp on the same host",
          history.archive_urls("https://www.amazon.sg/gp/product/B0TEST0001", amazon),
          ["https://www.amazon.sg/gp/product/B0TEST0001", "https://www.amazon.sg/dp/B0TEST0001"])
    other = "https://www.qoo10.sg/item/SONY-HEADPHONES/123456?utm_source=x"
    check("other shops: stripped URL only", history.archive_urls(other, adapter_for(other)),
          ["https://www.qoo10.sg/item/SONY-HEADPHONES/123456"])


# --- the archive, faked ------------------------------------------------------------------

class FakeResponse:
    def __init__(self, status=200, text="", payload=None):
        self.status_code = status
        self.text = json.dumps(payload) if payload is not None else text

    def json(self):
        return json.loads(self.text)


class FakeArchive:
    """Serves CDX rows per URL and archived pages per capture; records everything."""

    def __init__(self, cdx=None, pages=None, cdx_error=None):
        self.cdx = cdx or {}           # url -> [(timestamp, original), ...]
        self.pages = pages or {}       # timestamp -> html | int status | Exception
        self.cdx_error = cdx_error     # Exception or int status for every CDX call
        self.calls: list[str] = []
        self.sleeps: list[float] = []
        self.now = 1000.0              # a clock the test controls
        history._cooldown_until = 0.0  # each scenario starts un-throttled

    def get(self, url, params=None, headers=None, timeout=None):
        if url == history.CDX_URL:
            self.calls.append("cdx:" + params["url"])
            if isinstance(self.cdx_error, Exception):
                raise self.cdx_error
            if isinstance(self.cdx_error, int):
                return FakeResponse(self.cdx_error, "busy")
            rows = self.cdx.get(params["url"], [])
            return FakeResponse(payload=[["timestamp", "original"]] + [list(r) for r in rows]
                                if rows else [])
        timestamp = url.split("/web/")[1].split("id_")[0]
        self.calls.append("page:" + timestamp)
        page = self.pages.get(timestamp, amazon_page("$150.00"))
        if isinstance(page, Exception):
            raise page
        if isinstance(page, int):
            return FakeResponse(page, "")
        return FakeResponse(text=page)

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds

    def lookup(self, source, adapter):
        return history.wayback_lookup(source, adapter, get=self.get, sleep=self.sleep,
                                      clock=lambda: self.now)


def _source(url):
    return {"id": 1, "url": url}


def test_wayback_lookup():
    section("Reading the archive: one price a month, newest 24, politely")
    canonical = "https://www.amazon.com/dp/B09XS7JWHH"
    archive = FakeArchive(
        cdx={SLUG_URL: [("20240701000000", SLUG_URL), ("20240715000000", SLUG_URL),
                        ("20240801000000", SLUG_URL)],
             canonical: [("20240720000000", canonical), ("20240901000000", canonical)]},
        pages={"20240720000000": amazon_page("$196.23"), "20240801000000": amazon_page("$180.00"),
               "20240901000000": amazon_page("$175.50")},
    )
    result = archive.lookup(_source(SLUG_URL), adapter_for(SLUG_URL))
    pages = [c for c in archive.calls if c.startswith("page:")]
    check("found", result.kind, "found")
    check("one capture per month, the latest in each",
          pages, ["page:20240901000000", "page:20240801000000", "page:20240720000000"])
    check("oldest first, prices read", [(o.observed_at[:10], o.price) for o in result.observations],
          [("2024-07-20", 196.23), ("2024-08-01", 180.0), ("2024-09-01", 175.5)])
    first = result.observations[0]
    check("provenance", (first.currency, first.strategy), ("USD", "wayback:amazon-css"))
    check("links to the archived copy", first.ref,
          "https://web.archive.org/web/20240720000000id_/" + canonical)
    check("a pause before every request after the first",
          archive.sleeps, [history.REQUEST_GAP_S] * (len(archive.calls) - 1))

    months = [(f"{2020 + i // 12}{i % 12 + 1:02d}01000000", canonical) for i in range(30)]
    archive = FakeArchive(cdx={canonical: months})
    result = archive.lookup(_source(canonical), adapter_for(canonical))
    pages = [c for c in archive.calls if c.startswith("page:")]
    check("capped at 24 captures", len(pages), 24)
    check("the newest ones", pages[0], "page:" + months[-1][0])

    lazada = "https://www.lazada.sg/products/sony-wh-1000xm5-i123-s456.html"
    archive = FakeArchive()
    result = archive.lookup(_source(lazada), adapter_for(lazada))
    check("JS-priced shop: unsupported", result.kind, "unsupported")
    check("...without touching the archive", archive.calls, [])
    check_that("...and says why", "selling price" in result.reason, f"({result.reason})")

    for label, error in (("timeout", requests.Timeout("slow")), ("HTTP 503", 503)):
        archive = FakeArchive(cdx_error=error)
        result = archive.lookup(_source(canonical), adapter_for(canonical))
        check(f"{label}: unavailable, not 'no history'", result.kind, "unavailable")
        check_that(f"{label}: says it couldn't be reached", "couldn't be reached" in result.reason,
                   f"({result.reason})")

    archive = FakeArchive(cdx={})
    check("no copies: none", archive.lookup(_source(canonical), adapter_for(canonical)).kind, "none")

    archive = FakeArchive(cdx={canonical: months[:3]},
                          pages={m[0]: "<html>no price here</html>" for m in months[:3]})
    result = archive.lookup(_source(canonical), adapter_for(canonical))
    check("copies without a price: none", result.kind, "none")
    check_that("...says copies exist", "3 copies" in result.reason, f"({result.reason})")

    archive = FakeArchive(cdx={canonical: months[:3]},
                          pages={m[0]: requests.Timeout("slow") for m in months[:3]})
    check("every copy timed out: unavailable",
          archive.lookup(_source(canonical), adapter_for(canonical)).kind, "unavailable")
    check("...each was tried (a timeout isn't a limit)",
          len([c for c in archive.calls if c.startswith("page:")]), 3)


def test_rate_limit_backoff():
    section("The first sign of rate limiting stops everything, for a while")
    canonical = "https://www.amazon.com/dp/B09XS7JWHH"
    months = [(f"2025{m:02d}01000000", canonical) for m in range(1, 7)]
    check("at most 15 requests a minute", 60 / history.REQUEST_GAP_S <= 15, True)

    for label, failure, pause in (
        ("HTTP 429", 429, history.COOLDOWN_AFTER_429_S),
        ("connection refused", requests.ConnectionError("refused"), history.COOLDOWN_AFTER_BLOCK_S),
    ):
        # The 2nd copy answers with the limit signal; copies 3..6 must never be asked for.
        archive = FakeArchive(cdx={canonical: months}, pages={months[-2][0]: failure})
        result = archive.lookup(_source(canonical), adapter_for(canonical))
        pages = [c for c in archive.calls if c.startswith("page:")]
        check(f"{label}: unavailable", result.kind, "unavailable")
        check(f"{label}: stops at once, no further copies", len(pages), 2)
        check_that(f"{label}: says it's pausing", "pausing lookups" in result.reason, f"({result.reason})")

        calls_before = len(archive.calls)
        again = history.wayback_lookup(_source(canonical), adapter_for(canonical),
                                       get=archive.get, sleep=archive.sleep, clock=lambda: archive.now)
        check(f"{label}: next lookup during the pause sends nothing",
              (again.kind, len(archive.calls) - calls_before), ("unavailable", 0))

        archive.now += pause + 1
        archive.pages = {}
        later = history.wayback_lookup(_source(canonical), adapter_for(canonical),
                                       get=archive.get, sleep=archive.sleep, clock=lambda: archive.now)
        check(f"{label}: after the pause, lookups resume", later.kind, "found")

    archive = FakeArchive(cdx_error=429)
    archive.lookup(_source(canonical), adapter_for(canonical))
    check("429 on the index: one request, then stop", archive.calls, ["cdx:" + canonical])


# --- filtering and storing -------------------------------------------------------------------

def _obs(price, currency, month):
    return history.Observation(
        price=price, currency=currency, observed_at=f"2024-{month:02d}-01T00:00:00+00:00",
        strategy="wayback:amazon-css",
        ref=f"https://web.archive.org/web/2024{month:02d}01000000id_/https://www.amazon.com/dp/B0TEST0001")


def _amazon_product():
    fresh_db()
    product_id = db.add_product("Headphones", target_price=None)
    source_id = db.add_source(product_id, "https://www.amazon.com/dp/B0TEST0001", None)
    db.add_snapshot(source_id, 300.0, "USD", "amazon-css")
    return product_id, source_id


def test_backfill_source():
    section("Only usable, new archived prices are stored, and the note says what happened")
    product_id, source_id = _amazon_product()
    found = history.HistoryResult("found", observations=[
        _obs(280.0, "USD", 7), _obs(310.0, "USD", 8),
        _obs(30.0, "USD", 9),     # a tenth of the median: an accessory or used unit
        _obs(290.0, "GBP", 10),   # the archive crawler saw another currency
    ])
    lookup = lambda source, adapter: found

    history.backfill_source(source_id, lookups=[lookup])
    archived = [s for s in db.get_snapshots(source_id) if s["origin"] == "wayback"]
    check("kept the plausible, same-currency ones", [s["price"] for s in archived], [280.0, 310.0])
    check("stored as archived with their capture time",
          [(s["fetched_at"][:7], s["currency"]) for s in archived], [("2024-07", "USD"), ("2024-08", "USD")])
    check("note", db.get_source(source_id)["history_note"],
          "Internet Archive: 2 archived prices, 2024-07 to 2024-08 (2 new). "
          "Excluded: 1 implausible, 1 in another currency.")

    history.backfill_source(source_id, lookups=[lookup])
    check("re-run adds nothing", len([s for s in db.get_snapshots(source_id) if s["origin"]]), 2)
    check_that("re-run note says 0 new", "(0 new)" in db.get_source(source_id)["history_note"])

    for kind, reason in (("none", "The Internet Archive has no copies of this listing."),
                         ("unavailable", "The Internet Archive couldn't be reached (timeout)."),
                         ("unsupported", "Archived copies of Lazada pages don't include the selling price.")):
        _, source_id = _amazon_product()
        history.backfill_source(source_id, lookups=[lambda s, a, k=kind, r=reason: history.HistoryResult(k, reason=r)])
        check(f"{kind}: note is the reason", db.get_source(source_id)["history_note"], reason)
        check(f"{kind}: nothing stored", [s["origin"] for s in db.get_snapshots(source_id) if s["origin"]], [])


def test_scheduling():
    section("One background lookup per product")
    from app import scheduler
    product_id, source_id = _amazon_product()
    extra = db.add_source(product_id, "https://www.amazon.com/dp/B0TEST0002", None)
    try:
        history.schedule_backfill(product_id)
        history.schedule_backfill(product_id)
        jobs = [j.id for j in scheduler._scheduler.get_jobs()]
        check("asking twice leaves one job", jobs.count(f"history-{product_id}"), 1)
    finally:
        scheduler._scheduler.remove_all_jobs()

    seen = []
    saved = history.backfill_source
    history.backfill_source = lambda sid, lookups=None: seen.append(sid)
    try:
        history.backfill_product(product_id)
        check("every listing looked up, in order", seen, [source_id, extra])
        db.set_history_note(source_id, "Internet Archive: 3 archived prices")
        seen.clear()
        history.backfill_product(product_id, only_unchecked=True)
        check("automatic run skips listings already checked", seen, [extra])
    finally:
        history.backfill_source = saved


# --- the product page and verdict ------------------------------------------------------

def _archive(source_id, price, when):
    db.add_snapshot(source_id, price, "USD", "wayback:amazon-css", fetched_at=when,
                    origin="wayback", origin_ref=f"https://web.archive.org/web/{when[:10].replace('-', '')}000000id_/x")


def test_current_price_is_live_only():
    section("The current price comes only from live checks")
    from app import main
    product_id, source_id = _amazon_product()          # live: USD 300 (now)
    _archive(source_id, 150.0, "2099-01-01T00:00:00+00:00")  # newer than the live check
    view = main._product_view(db.get_product(product_id))
    check("newer archived copy isn't the current price", view["comparison"].sources[0].price, 300.0)
    check_that("...but it is in the history", 150.0 in view["series"], f"({view['series']})")

    fresh_db()
    product_id = db.add_product("Headphones", target_price=None)
    source_id = db.add_source(product_id, "https://www.amazon.com/dp/B0TEST0001", None)
    db.add_snapshot(source_id, None, error="Amazon served a bot check.")
    for month, price in ((7, 280.0), (8, 290.0)):
        _archive(source_id, price, f"2024-{month:02d}-01T00:00:00+00:00")
    view = main._product_view(db.get_product(product_id))
    listing = view["comparison"].sources[0]
    check("only archived prices: no current price", listing.price, None)
    check("...the live error is shown", listing.error, "Amazon served a bot check.")
    check("...archived prices still form the history", view["series"], [280.0, 290.0])


def test_verdict_uses_archived_history():
    section("A new product gets a trend verdict from its archived history")
    from app import main
    product_id, source_id = _amazon_product()          # 1 live check, USD 300
    prices = [320, 340, 310, 360, 355, 330, 345, 365, 350, 325, 335, 370]
    for month, price in enumerate(prices, start=1):
        _archive(source_id, float(price), f"2025-{month:02d}-01T00:00:00+00:00")
    verdict = main._product_view(db.get_product(product_id))["verdict"]
    check("13 observations", verdict.stats.get("num_observations"), 13)
    check("a real verdict, not 'not enough data'", verdict.label, "BUY_NOW")  # 300 is the lowest seen


def _client():
    from fastapi.testclient import TestClient
    from app import main
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return TestClient(main.app, follow_redirects=False), main


def test_routes_schedule_lookups():
    section("Tracking a listing schedules a lookup; the button re-checks everything")
    fresh_db()
    client, main = _client()
    scheduled = []
    saved = (main.history.schedule_backfill, main.refresh_product, main.refresh_source)
    main.history.schedule_backfill = lambda pid, only_unchecked=True: scheduled.append((pid, only_unchecked))
    main.refresh_product = main.refresh_source = lambda _id: None  # no live fetches
    try:
        r = client.post("/products", data={"name": "H", "url": "https://www.amazon.com/dp/B0TEST0001"})
        check("add product: redirects at once", r.status_code, 303)
        product_id = db.get_products()[0]["id"]
        client.post("/discover/track", data={"name": "H2", "urls": ["https://www.amazon.com/dp/B0TEST0002"]})
        client.post(f"/products/{product_id}/sources", data={"url": "https://www.amazon.com/dp/B0TEST0003"})
        r = client.post(f"/products/{product_id}/history")
        check("button: redirects back", (r.status_code, r.headers["location"]), (303, f"/product/{product_id}"))
        track_id = db.get_products()[0]["id"]
        check("each route scheduled exactly once", scheduled,
              [(product_id, True), (track_id, True), (product_id, True), (product_id, False)])
        check("unknown product: 404", client.post("/products/999/history").status_code, 404)
    finally:
        main.history.schedule_backfill, main.refresh_product, main.refresh_source = saved


def test_product_page_shows_provenance():
    section("The product page shows where history came from")
    product_id, source_id = _amazon_product()
    _archive(source_id, 280.0, "2024-07-01T00:00:00+00:00")
    db.set_history_note(source_id, "Internet Archive: 1 archived price, 2024-07 to 2024-07 (1 new).")
    unchecked = db.add_source(product_id, "https://www.amazon.com/dp/B0TEST0002", None)
    client, _ = _client()
    html = client.get(f"/product/{product_id}").text
    check_that("archived row marked", 'class="archived-chip"' in html)
    check_that("links to the archived copy", 'href="https://web.archive.org/web/20240701000000id_/x"' in html)
    check_that("the note is shown", "Internet Archive: 1 archived price" in html)
    check_that("an unchecked listing says so", "not looked up yet" in html)
    check_that("the re-check button is there", f'action="/products/{product_id}/history"' in html)


TESTS = [
    test_storage,
    test_extract_from_html,
    test_archive_urls,
    test_wayback_lookup,
    test_rate_limit_backoff,
    test_backfill_source,
    test_scheduling,
    test_current_price_is_live_only,
    test_verdict_uses_archived_history,
    test_routes_schedule_lookups,
    test_product_page_shows_provenance,
]

for test in TESTS:
    test()

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("All history tests passed.")
