"""Currency tests: which prices may be ranked, charted and compared with a target.

Every rule here exists because breaking it makes the app lie -- declaring a price
"cheapest" or a target "met" by comparing numbers in different currencies. All of
it runs offline: conversion is faked, and anything that needs the database gets a
throwaway SQLite file, never data/app.db.

Run: python -m tests.test_currency
"""

import logging
import re
import sys

from app import database as db
from app import main
from app.analysis import best_price_series, compare_sources, target_in
from tests import helpers

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


# Units per USD, like fx_rates. VND deliberately absent: "a currency with no rate".
RATES = {"USD": 1.0, "SGD": 1.28, "MYR": 4.09, "PHP": 62.8}


def fake_convert(amount, from_currency, to_currency):
    """Same contract as fx.convert, minus the database."""
    if amount is None or not from_currency or not to_currency:
        return None
    if from_currency == to_currency:
        return round(amount, 2)
    if from_currency not in RATES or to_currency not in RATES:
        return None
    return round(amount * (RATES[to_currency] / RATES[from_currency]), 2)


def converter_to(target):
    """Same contract as fx.make_converter(target)."""
    return lambda amount, from_currency: fake_convert(amount, from_currency, target)


def _sources(*retailers):
    return [{"id": i, "retailer": r, "url": f"https://{r.lower()}.example/p"}
            for i, r in enumerate(retailers, 1)]


def _latest(price, currency):
    return {"price": price, "currency": currency, "fetched_at": "t", "error": None}


def _snap(source_id, price, currency, hour):
    return {"source_id": source_id, "price": price, "currency": currency,
            "fetched_at": f"2026-09-24T{hour:02d}:00:00", "error": None}


def _by_retailer(comparison, retailer):
    return next(s for s in comparison.sources if s.retailer == retailer)


# --- a throwaway database ------------------------------------------------

helpers.use_temp_db()
fresh_db = helpers.reset_db


# --- ranking across currencies ---------------------------------------------

def test_unknown_currency_never_ranked():
    section("Unknown currency is shown but never compared")
    sources = _sources("Amazon", "Mystery")
    latest = {1: _latest(100.0, "SGD"), 2: _latest(50.0, None)}

    c = compare_sources(sources, latest, "SGD")
    mystery = _by_retailer(c, "Mystery")
    check("cheaper unknown does not win", c.cheapest.retailer, "Amazon")
    check("marked currency unknown", mystery.currency_unknown, True)
    check("not labelled off-currency", mystery.off_currency, False)
    check("no comparable price", mystery.comparable_price, None)
    check("still shown", len(c.sources), 2)

    c = compare_sources(sources, latest, "SGD",
                        to_display=converter_to("MYR"), display_currency="MYR")
    check("with display currency: unknown still not ranked",
          _by_retailer(c, "Mystery").ranking_eligible, False)
    check("with display currency: known one wins", c.cheapest.retailer, "Amazon")


def test_as_quoted_ranks_only_primary_currency():
    section("As quoted: only the product's currency is ranked")
    sources = _sources("Amazon", "LazadaMY")
    latest = {1: _latest(100.0, "SGD"), 2: _latest(200.0, "MYR")}

    c = compare_sources(sources, latest, "SGD")
    my = _by_retailer(c, "LazadaMY")
    check("foreign marked off-currency", my.off_currency, True)
    check("foreign not ranked", my.ranking_eligible, False)
    check("home currency cheapest", c.cheapest.retailer, "Amazon")
    check("mixed currency flagged", c.mixed_currency, True)
    check("nothing converted", c.converted, False)


def test_inferred_comparison_currency():
    section("No pinned currency")
    sources = _sources("A", "B")
    shared = {1: _latest(120.0, "SGD"), 2: _latest(100.0, "SGD")}
    c = compare_sources(sources, shared, None)
    check("one shared currency is compared", c.currency, "SGD")
    check("cheapest found", c.cheapest.retailer, "B")

    mixed = {1: _latest(120.0, "SGD"), 2: _latest(100.0, "MYR")}
    c = compare_sources(sources, mixed, None)
    check("mixed: nothing declared cheapest", c.cheapest, None)
    check("mixed: no comparison currency", c.currency, None)


def test_display_currency_ranking():
    section("With a display currency, listings compete after conversion")
    sources = _sources("Amazon", "LazadaMY", "ShopeeVN")
    latest = {1: _latest(100.0, "SGD"),      # ~MYR 319.53
              2: _latest(200.0, "MYR"),
              3: _latest(1000.0, "VND")}     # no rate
    c = compare_sources(sources, latest, "SGD",
                        to_display=converter_to("MYR"), display_currency="MYR")
    check("converted listing wins", c.cheapest.retailer, "LazadaMY")
    check("conversion reported", c.converted, True)
    vn = _by_retailer(c, "ShopeeVN")
    check("no-rate listing marked off-currency", vn.off_currency, True)
    check("no-rate listing not ranked", vn.ranking_eligible, False)
    check("original price untouched", _by_retailer(c, "Amazon").price, 100.0)


def test_nothing_convertible():
    section("Display currency selected but nothing converts")
    sources = _sources("ShopeeVN")
    latest = {1: _latest(1000.0, "VND")}
    c = compare_sources(sources, latest, "VND",
                        to_display=converter_to("SGD"), display_currency="SGD")
    check("does not claim conversion", c.converted, False)
    check("nothing cheapest", c.cheapest, None)


def test_failed_fetch_not_ranked():
    section("A failed fetch is shown, never ranked")
    sources = _sources("Amazon", "Broken")
    latest = {1: _latest(100.0, "SGD"),
              2: {"price": None, "currency": None, "fetched_at": None, "error": "blocked"}}
    c = compare_sources(sources, latest, "SGD")
    broken = _by_retailer(c, "Broken")
    check("failed not eligible", broken.ranking_eligible, False)
    check("failed not currency-unknown", broken.currency_unknown, False)
    check("error kept", broken.error, "blocked")


# --- best-price history ---------------------------------------------------

def test_series_excludes_uncomparable():
    section("Best-price history only holds comparable prices")
    snaps = [
        _snap(1, 300.0, "SGD", 1), _snap(2, 50.0, None, 1),    # unknown is cheaper
        _snap(1, 310.0, "SGD", 2), _snap(3, 200.0, "MYR", 2),  # foreign is cheaper
    ]
    check("as quoted: unknown and foreign dropped",
          best_price_series(snaps, "SGD"), [300.0, 310.0])
    check("no pinned currency: dominant used",
          best_price_series(snaps, None), [300.0, 310.0])

    converted = best_price_series(snaps, "SGD", to_display=converter_to("SGD"))
    check("converted: unknown still dropped", converted[0], 300.0)
    check_that("converted: foreign competes", 62 < converted[1] < 63, f"({converted[1]})")

    vnd = [_snap(1, 300.0, "SGD", 1), _snap(2, 1.0, "VND", 1)]
    check("converted: no-rate dropped",
          best_price_series(vnd, "SGD", to_display=converter_to("SGD")), [300.0])
    check("all unknown: empty history",
          best_price_series([_snap(1, 5.0, None, 1)], None), [])


# --- storage ----------------------------------------------------------------

def _raw(sql_script):
    """Build a database by hand, the way an older version of the app left it."""
    helpers.empty_db()
    conn = db.get_connection()
    conn.executescript(sql_script)
    conn.commit()
    conn.close()


def test_upgrade_adds_target_currency():
    section("Upgrading a database from before target currencies")
    if helpers.on_postgres():
        print("  skipped: the upgrade path is SQLite-only (Postgres starts from the current schema)")
        return
    _raw("""
        CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            target_price REAL, currency TEXT, created_at TEXT NOT NULL);
        INSERT INTO products (name, target_price, currency, created_at)
            VALUES ('Headphones', 300.0, 'SGD', '2026-09-01T00:00:00+00:00');
    """)
    db.init_db()
    db.init_db()  # must be safe to run on every startup
    product = db.get_products()[0]
    check("column added", "target_currency" in product.keys(), True)
    check("existing row kept", (product["name"], product["target_price"]), ("Headphones", 300.0))
    check("legacy target has no currency", product["target_currency"], None)

    # A v1 database (url on the product) goes through the table rebuild first.
    _raw("""
        CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
            url TEXT NOT NULL, price_selector TEXT, target_price REAL, created_at TEXT NOT NULL);
        CREATE TABLE price_snapshots (id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_id INTEGER NOT NULL, price REAL, fetched_at TEXT NOT NULL, error TEXT);
        INSERT INTO products (name, url, target_price, created_at)
            VALUES ('Old', 'https://www.amazon.sg/dp/X', 99.0, '2026-01-01T00:00:00+00:00');
        INSERT INTO price_snapshots (product_id, price, fetched_at)
            VALUES (1, 120.0, '2026-01-01T00:00:00+00:00');
    """)
    db.init_db()
    product = db.get_products()[0]
    check("v1: product kept", (product["name"], product["target_price"]), ("Old", 99.0))
    check("v1: column present", product["target_currency"], None)
    check("v1: history kept", len(db.get_snapshots_for_product(product["id"])), 1)


def test_target_currency_round_trip():
    section("Target currency is stored as entered")
    fresh_db()
    with_currency = db.add_product("A", target_price=800.0, target_currency="MYR")
    without = db.add_product("B", target_price=300.0)
    check("stored MYR", db.get_product(with_currency)["target_currency"], "MYR")
    check("stored None", db.get_product(without)["target_currency"], None)
    check("amount stored as entered", db.get_product(with_currency)["target_price"], 800.0)


# --- target price -------------------------------------------------------------

def test_target_in():
    section("Target restated in the history's currency")
    check("same currency unchanged", target_in(300.0, "SGD", "SGD", fake_convert), 300.0)
    check("MYR target into SGD", target_in(800.0, "MYR", "SGD", fake_convert), 250.37)
    check("no rate -> not comparable", target_in(800.0, "VND", "SGD", fake_convert), None)
    check("unknown target currency", target_in(800.0, None, "SGD", fake_convert), None)
    check("unknown history currency", target_in(800.0, "SGD", None, fake_convert), None)
    check("no target", target_in(None, "SGD", "SGD", fake_convert), None)


def _tracked(price, currency, target, target_currency=None):
    """A product with one listing and one successful fetch, as refresh leaves it."""
    product_id = db.add_product("Headphones", target_price=target,
                                target_currency=target_currency)
    source_id = db.add_source(product_id, "https://www.amazon.sg/dp/X", None)
    db.add_snapshot(source_id, price, currency, strategy="test")
    db.set_product_currency(product_id, currency)
    return product_id


def _view(product_id, display=None):
    db.set_setting("display_currency", display)
    return main._product_view(db.get_product(product_id))


def _with_rates():
    fresh_db()
    db.save_fx_rates("USD", RATES)


def test_target_in_view():
    section("Target applied to the verdict in the history's currency")
    _with_rates()

    # MYR 800 is ~SGD 250. Read as SGD 800 it would falsely say BUY NOW.
    v = _view(_tracked(300.0, "SGD", 800.0, "MYR"))
    check("MYR 800 vs SGD 300: not met", v["verdict"].label, "NOT_ENOUGH_DATA")
    check("target shown in its own currency", v["target_currency"], "MYR")
    check("equivalent shown for this view", v["target_display_price"], 250.37)
    check("target applied", v["target_not_applied"], False)

    v = _view(_tracked(300.0, "SGD", 1000.0, "MYR"))  # ~SGD 312.96
    check("MYR 1000 vs SGD 300: met", v["verdict"].label, "BUY_NOW")

    v = _view(_tracked(300.0, "SGD", 300.0))
    check("legacy target: product currency", v["target_currency"], "SGD")
    check("legacy target: applied as entered", v["verdict"].label, "BUY_NOW")
    check("legacy target: no duplicate figure", v["target_display_price"], None)

    # Without rates a foreign target can't be compared: show it, don't use it.
    conn = db.get_connection()
    conn.execute("DELETE FROM fx_rates")
    conn.commit()
    conn.close()
    v = _view(_tracked(300.0, "SGD", 1000.0, "MYR"))
    check("no rate: not applied", v["target_not_applied"], True)
    check("no rate: verdict ignores target", v["verdict"].label, "NOT_ENOUGH_DATA")
    v = _view(_tracked(300.0, "SGD", 300.0, "SGD"))
    check("no rate, same currency: still applied", v["verdict"].label, "BUY_NOW")


def test_display_currency_does_not_move_verdict():
    section("Switching display currency never changes a target verdict")
    _with_rates()
    at_target = _tracked(300.0, "SGD", 300.0, "SGD")
    below_target = _tracked(300.0, "SGD", 299.0, "SGD")
    for display in (None, "MYR", "USD"):
        check(f"met exactly, shown in {display}", _view(at_target, display)["verdict"].label,
              "BUY_NOW")
        check(f"not met, shown in {display}", _view(below_target, display)["verdict"].label,
              "NOT_ENOUGH_DATA")

    product = db.get_product(at_target)
    check("stored target unchanged", (product["target_price"], product["target_currency"]),
          (300.0, "SGD"))
    db.set_setting("display_currency", None)


def test_chart_points():
    section("Chart lines never mix currencies")
    snaps = [_snap(1, 300.0, "SGD", 1), _snap(1, 409.0, "MYR", 2),
             _snap(1, 50.0, None, 3), _snap(1, 1.0, "VND", 4),
             {**_snap(1, None, "SGD", 5), "error": "blocked"}]
    as_quoted = main._chart_points(snaps, None, "SGD", fake_convert)
    check("as quoted: only the product's currency", [p for _, p in as_quoted], [300.0])

    converted = main._chart_points(snaps, "SGD", "SGD", fake_convert)
    check("converted: foreign restated, unknown and no-rate dropped",
          [p for _, p in converted], [300.0, 128.0])
    check("timestamps kept", converted[1][0], "2026-09-24T02:00:00")
    check("no primary currency: nothing plotted as quoted",
          main._chart_points(snaps, None, None, fake_convert), [])


# --- forms and pages ------------------------------------------------------------

def _client():
    """Signed in as the site's first account (the admin), which may see every product.
    Not used as a context manager, so the app's startup (FX download, scheduler)
    never runs. Refreshing a new product would fetch real shop pages: stub it, and
    the archive lookup too."""
    from tests import helpers
    main.refresh_product = lambda product_id: None
    main.history.schedule_backfill = lambda *a, **k: None
    return helpers.client("owner")


def _product_count():
    return len(db.get_products())


def _latest_target():
    product = db.get_products()[0]  # newest first
    return product["target_price"], product["target_currency"]


def test_forms_store_target_currency():
    section("Forms store the target's currency")
    fresh_db()
    client = _client()
    form = {"name": "Headphones", "url": "https://www.amazon.sg/dp/X"}

    r = client.post("/products", data={**form, "target_price": "800", "target_currency": "MYR"})
    check("add: redirected", r.status_code, 303)
    check("add: MYR stored", _latest_target(), (800.0, "MYR"))

    client.post("/products", data={**form, "target_price": "300", "target_currency": ""})
    check("add: shop's currency stored as None", _latest_target(), (300.0, None))

    client.post("/products", data={**form, "target_price": "", "target_currency": "MYR"})
    check("add: no target, no currency", _latest_target(), (None, None))

    before = _product_count()
    r = client.post("/products", data={**form, "target_price": "800", "target_currency": "XYZ"})
    check("add: unknown currency rejected", r.status_code, 400)
    check("add: nothing created", _product_count(), before)

    track = {"name": "Headphones", "urls": ["https://www.lazada.sg/p/X"]}
    client.post("/discover/track", data={**track, "target_price": "1000", "target_currency": "myr"})
    check("track: currency stored, normalised", _latest_target(), (1000.0, "MYR"))

    before = _product_count()
    r = client.post("/discover/track", data={**track, "target_price": "1", "target_currency": "XYZ"})
    check("track: unknown currency rejected", r.status_code, 400)
    check("track: nothing created", _product_count(), before)


def _target_select(html):
    match = re.search(r'<select name="target_currency".*?</select>', html, re.S)
    return match.group(0) if match else ""


def _selected_option(select_html):
    match = re.search(r'<option value="([^"]*)"\s*selected>', select_html)
    return match.group(1) if match else ""  # nothing marked -> the first, "Shop's currency"


def test_forms_default_to_display_currency():
    section("Target currency defaults to what the user is looking at")
    fresh_db()
    client = _client()
    for display, expected in (("MYR", "MYR"), (None, "")):
        db.set_setting("display_currency", display)
        # The track form only renders with a query. Rendering is offline: the
        # search itself runs in /discover/stream, which only the browser calls.
        for path in ("/", "/discover?q=headphones"):
            select = _target_select(client.get(path).text)
            check_that(f"{path}: selector present", bool(select))
            check(f"{path} shown in {display}: preset", _selected_option(select), expected)
    db.set_setting("display_currency", None)


def test_product_page_shows_both_figures():
    section("Product page shows the target as entered and as compared")
    _with_rates()
    product_id = _tracked(300.0, "SGD", 800.0, "MYR")
    html = _client().get(f"/product/{product_id}").text
    check_that("target in its own currency", "MYR 800.00" in html)
    check_that("equivalent in the history's currency", "SGD 250.37 for this view" in html)
    check_that("no 'not applied' warning", "not used in the verdict" not in html)


TESTS = [
    test_unknown_currency_never_ranked,
    test_as_quoted_ranks_only_primary_currency,
    test_inferred_comparison_currency,
    test_display_currency_ranking,
    test_nothing_convertible,
    test_failed_fetch_not_ranked,
    test_series_excludes_uncomparable,
    test_upgrade_adds_target_currency,
    test_target_currency_round_trip,
    test_target_in,
    test_target_in_view,
    test_display_currency_does_not_move_verdict,
    test_chart_points,
    test_forms_store_target_currency,
    test_forms_default_to_display_currency,
    test_product_page_shows_both_figures,
]

for test in TESTS:
    test()

print("\n" + "=" * 60)
if FAILURES:
    print(f"{len(FAILURES)} FAILURE(S):")
    for f in FAILURES:
        print("  -", f)
    sys.exit(1)
print("All currency tests passed.")
