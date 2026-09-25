"""Shop-search tests: concurrency, block detection, and starting the browser.

Offline. Nothing here talks to a shop; the one check that starts Chromium renders
an in-memory page, and the requests it makes go to a closed local port.

Run: python -m tests.test_shop_search
"""

import asyncio
import json
import logging
import socket
import sys
import time
import warnings
from types import SimpleNamespace

from app import browser
from app import database as db
from app.scraper import PriceResult, ScrapeError
from app.search import site_search
from app.search.base import Candidate
from tests import helpers

# The stream reads settings; give it a throwaway database, never data/app.db.
helpers.use_temp_db()
db.init_db()

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


# --- starting the browser ---------------------------------------------------

def _closed_port() -> int:
    """A port nothing listens on: bind one, then let it go."""
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


# A request that is allowed through fails with CONNECTION_REFUSED; one we abort
# fails with ERR_FAILED. (Not port 9: Chromium refuses "unsafe" ports itself.)
CLOSED = f"http://127.0.0.1:{_closed_port()}"


async def _render_in_memory():
    failures = {}
    async with browser.chromium() as chromium:
        page = await browser.new_page(chromium)
        page.on("requestfailed", lambda r: failures.update({r.resource_type: r.failure}))
        await page.set_content(
            f'<p class="price">SGD 1.00</p><img src="{CLOSED}/x.png">'
            f'<script src="{CLOSED}/x.js"></script>',
            wait_until="load",
        )
        await page.wait_for_timeout(300)  # let the failures be reported
        text = await page.text_content(".price")
        await page.context.close()
    return text, failures


async def _spawn_subprocess():
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-c", "print('spawned')", stdout=asyncio.subprocess.PIPE
    )
    out, _ = await proc.communicate()
    return out.decode().strip()


def test_browser_survives_reload_loop_policy():
    section("Browser starts even under uvicorn --reload's loop policy")
    if sys.platform != "win32":
        print("  (Windows-only failure mode; checking the plain path instead)")
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", DeprecationWarning)  # policies are deprecated in 3.14
        previous = asyncio.get_event_loop_policy()
        if sys.platform == "win32":
            # Exactly what uvicorn 0.30 does when it runs with --reload.
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        try:
            check("subprocess can start", browser.run(_spawn_subprocess()), "spawned")
            text, failures = browser.run(_render_in_memory())
        finally:
            asyncio.set_event_loop_policy(previous)
    check("page rendered", text, "SGD 1.00")
    check("image skipped", failures.get("image"), "net::ERR_FAILED")
    check("script still requested", failures.get("script"), "net::ERR_CONNECTION_REFUSED")


# --- block detection ----------------------------------------------------------

# Shaped like what eBay actually returned on 2026-09-24: 1,831 characters.
EBAY_ERROR_PAGE = ("<html><head><title>Error Page | eBay</title></head><body>"
                   + "<p>Something went wrong.</p>" * 55 + "</body></html>")


def test_looks_blocked():
    section("A block is recognised on sight; a slow page is not mistaken for one")
    check_that("error page is small", len(EBAY_ERROR_PAGE) < 2_000, f"({len(EBAY_ERROR_PAGE)} chars)")
    check("small error page, no cards", site_search.looks_blocked(EBAY_ERROR_PAGE, 0), True)
    wall = "<html>" + "x" * 50_000 + "Robot Check</html>"
    check("large bot-check page", site_search.looks_blocked(wall, 0), True)
    still_rendering = "<html>" + "<div>layout</div>" * 70_000 + "</html>"  # ~1 MB
    check("large page, cards not rendered yet", site_search.looks_blocked(still_rendering, 0), False)
    check("small page that has cards", site_search.looks_blocked(EBAY_ERROR_PAGE, 3), False)


# --- running shops concurrently --------------------------------------------------

def _shop(name):
    return SimpleNamespace(name=name), f"{name.lower()}.example"


def _fake_run_one(delays, failing=()):
    async def run_one(adapter, domain):
        await asyncio.sleep(delays[adapter.name])
        if adapter.name in failing:
            raise failing[adapter.name]
        return [] if adapter.name == "Empty" else [f"{adapter.name} listing"]
    return run_one


def test_shops_arrive_as_they_finish():
    section("Shops are searched at once and reported as each finishes")
    pairs = [_shop("Slow"), _shop("Fast"), _shop("Middle")]
    delays = {"Slow": 0.6, "Fast": 0.1, "Middle": 0.3}

    started = time.perf_counter()
    arrivals = []
    for domain, retailer, found, error in site_search._stream(
        lambda emit: site_search._gather_shops(pairs, _fake_run_one(delays), emit)
    ):
        arrivals.append((retailer, round(time.perf_counter() - started, 1)))
    total = time.perf_counter() - started

    check("completion order, not listing order", [r for r, _ in arrivals], ["Fast", "Middle", "Slow"])
    check_that("fast shop not held back", arrivals[0][1] < 0.3, f"({arrivals[0][1]} s)")
    check_that("total is the slowest shop, not the sum", total < 0.9, f"({total:.2f} s; sum is 1.0 s)")


def test_one_shop_failing():
    section("One failing shop never stops the others")
    pairs = [_shop("Good"), _shop("Broken"), _shop("Refusing"), _shop("Empty")]
    delays = {"Good": 0.05, "Broken": 0.05, "Refusing": 0.05, "Empty": 0.05}
    failing = {"Broken": ValueError("boom"),
               "Refusing": site_search.ShopRefused("Refusing refused the search.")}
    results = {retailer: (found, error) for _, retailer, found, error in site_search._stream(
        lambda emit: site_search._gather_shops(pairs, _fake_run_one(delays, failing), emit)
    )}
    check("all four reported", sorted(results), ["Broken", "Empty", "Good", "Refusing"])
    check("good shop still has results", results["Good"], (["Good listing"], None))
    check("crash shown on its own shop", results["Broken"], ([], "ValueError: boom"))
    check("refusal shown plainly", results["Refusing"], ([], "Refusing refused the search."))
    check("empty result says so", results["Empty"], ([], site_search.NO_RESULTS))


def test_browser_failure_surfaces():
    section("A browser that can't start is an error, not an empty search")

    async def job(emit):
        emit(("first.example", "First", ["listing"], None))
        raise browser.BrowserUnavailable("Could not start Chromium: test")

    got, raised = [], None
    try:
        for item in site_search._stream(job):
            got.append(item[1])
    except browser.BrowserUnavailable as exc:
        raised = str(exc)
    check("what arrived first is kept", got, ["First"])
    check("then the failure is raised", raised, "Could not start Chromium: test")


# --- the discovery stream -----------------------------------------------------------

def _stream_events(fake_search_all, fake_fetch_price):
    """Run /discover/stream with the shop search and price fetcher stubbed out."""
    from fastapi.testclient import TestClient
    from app import main

    logging.getLogger("httpx").setLevel(logging.WARNING)
    saved = (site_search.search_all, main.fetch_price)
    site_search.search_all, main.fetch_price = fake_search_all, fake_fetch_price
    try:
        started = time.perf_counter()
        # Not a context manager: startup (FX download, scheduler) must not run.
        body = TestClient(main.app).get("/discover/stream?q=headphones").text
        elapsed = time.perf_counter() - started
    finally:
        site_search.search_all, main.fetch_price = saved
    events = [json.loads(chunk[len("data: "):]) for chunk in body.split("\n\n") if chunk]
    return events, elapsed


def _unpriced(name):
    return Candidate(title=f"Sony WH-1000XM5 {name}", url=f"https://www.amazon.sg/dp/{name}",
                     retailer="Amazon", provider="site:amazon.sg", score=0.9)


def test_price_lookups_run_concurrently():
    section("Missing prices are looked up a few at a time, each shown as it lands")
    names = ["A", "B", "C", "BROKEN"]

    def fake_search_all(query, domains, per_shop=6):
        yield "amazon.sg", "Amazon", [_unpriced(n) for n in names], None

    def fake_fetch_price(url, timeout=20):
        time.sleep(0.5)
        if url.endswith("BROKEN"):
            raise ScrapeError("Amazon served a bot check.")
        return PriceResult(price=300.0, currency="SGD", strategy="stub")

    events, elapsed = _stream_events(fake_search_all, fake_fetch_price)
    prices = [e for e in events if e["type"] == "price"]
    check("one price event per lookup", len(prices), 4)
    check_that("concurrent, not one after another", elapsed < 1.5,
               f"({elapsed:.2f} s; one at a time is 2.0 s)")
    broken = [e for e in prices if e.get("error")]
    check("failure lands on its own row only", [e["error"] for e in broken],
          ["Amazon served a bot check."])
    check("others still priced", sorted(e.get("price") for e in prices if not e.get("error")),
          [300.0, 300.0, 300.0])
    check("summary still sent last", events[-1]["type"], "done")


def test_browser_failure_becomes_error_event():
    section("A browser that can't start ends the stream with an explanation")

    def fake_search_all(query, domains, per_shop=6):
        raise browser.BrowserUnavailable("Could not start Chromium: test")
        yield  # a generator, like the real one

    events, _ = _stream_events(fake_search_all, lambda url, timeout=20: None)
    check("one event", [e["type"] for e in events], ["error"])
    check_that("says the browser couldn't start", "couldn't start" in events[0]["message"],
               f"({events[0]['message'][:60]}...)")


# --- the discover page, in a real browser ----------------------------------------------

def _sse_body(*events):
    return "".join(f"data: {json.dumps(e)}\n\n" for e in events)


async def _statuses_after_stream(page_html, stream_body):
    """Load the discover page with its stream answered by `stream_body`, wait for the
    stream to end, and return each shop section's status text."""
    async with browser.chromium() as chromium:
        page = await browser.new_page(chromium)

        async def serve(route):
            url = route.request.url
            if "/discover/stream" in url:
                await route.fulfill(status=200, content_type="text/event-stream", body=stream_body)
            elif url.startswith("http://app.test/discover"):
                await route.fulfill(status=200, content_type="text/html", body=page_html)
            elif url.startswith("http://app.test/static/"):
                await route.fulfill(status=200, content_type="text/css", body="")
            else:
                await route.abort()  # CDNs etc.: offline

        await page.route("**/*", serve)
        await page.goto("http://app.test/discover?q=headphones")
        await page.wait_for_function(
            "() => !document.querySelector('#progress .spinner')", timeout=5000)
        statuses = await page.eval_on_selector_all(
            ".shop-section", "els => els.map(e => [e.dataset.domain, "
            "e.querySelector('.shop-status').textContent.trim()])")
        progress = await page.text_content("#progress")
        await page.context.close()
    return dict(statuses), progress.strip()


def test_page_never_leaves_shops_spinning():
    section("No shop is left on 'searching…'")
    from fastapi.testclient import TestClient
    from app import main
    html = TestClient(main.app).get("/discover?q=headphones").text

    shop = lambda domain, n, error=None: {"type": "shop", "domain": domain, "retailer": domain,
                                          "rows": [], "error": error}
    finished = _sse_body(shop("amazon.sg", 0), shop("lazada.sg", 0),
                         shop("ebay.com.sg", 0, "eBay refused the search."),
                         {"type": "done", "priced": 0})
    statuses, progress = browser.run(_statuses_after_stream(html, finished))
    check_that("nothing still searching", not any("searching" in s for s in statuses.values()),
               f"({statuses})")
    check_that("unsearchable shop says so", "no site search" in statuses.get("shopee.sg", ""),
               f"({statuses.get('shopee.sg')!r})")
    check("blocked shop shows why", statuses.get("ebay.com.sg"), "eBay refused the search.")

    stopped = _sse_body(shop("amazon.sg", 0),
                        {"type": "error", "message": "The browser couldn't start."})
    statuses, progress = browser.run(_statuses_after_stream(html, stopped))
    check("stopped search: progress says so", progress, "Search stopped.")
    check("stopped search: unfinished shop marked", statuses.get("lazada.sg"),
          "not searched — the search stopped")
    check_that("stopped search: nothing still searching",
               not any("searching…" in s for s in statuses.values()), f"({statuses})")


TESTS = [
    test_browser_survives_reload_loop_policy,
    test_looks_blocked,
    test_shops_arrive_as_they_finish,
    test_one_shop_failing,
    test_browser_failure_surfaces,
    test_price_lookups_run_concurrently,
    test_browser_failure_becomes_error_event,
    test_page_never_leaves_shops_spinning,
]

for test in TESTS:
    test()

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("All shop-search tests passed.")
