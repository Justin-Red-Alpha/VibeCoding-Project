"""Hosted mode: the storage port on both engines, the outage page, /healthz, cron
scheduling and the daily run, and the proxy (forwarded host, Secure cookie).

Offline. Runs on a temp SQLite file, or on a local Postgres when
TEST_DATABASE_URL is set (see tests/helpers.py). No shop or archive is contacted.

Run: python -m tests.test_hosting
"""

import os
import sys
import tempfile
import threading
from pathlib import Path

from app import database as db
from app import history, refresh, scheduler, site_settings
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


helpers.use_temp_db()
ENGINE = db.backend()
print(f"Engine: {ENGINE}")


def _no_network(*args, **kwargs):
    raise AssertionError(f"test_hosting tried to reach the network: {args[:2]}")


# Offline: any HTTP call through requests fails loudly.
import requests as _requests
_requests.Session.request = _no_network


class _env:
    """Set (or clear, with None) environment variables for a block."""

    def __init__(self, **values):
        self.values, self.saved = values, {}

    def __enter__(self):
        for key, value in self.values.items():
            self.saved[key] = os.environ.get(key)
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def __exit__(self, *exc):
        for key, value in self.saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _set_times(table: str, column: str, stamp: str) -> None:
    conn = db.get_connection()
    conn.execute(f"UPDATE {table} SET {column} = ?", (stamp,))
    conn.commit()
    conn.close()


# --- the storage port ------------------------------------------------------------------

def test_rows_read_like_sqlite():
    section(f"Rows read the same on both engines ({ENGINE})")
    helpers.reset_db()
    pid = db.add_product("Headphones", 300.0, "SGD")
    row = db.get_product(pid)
    check("by name", row["name"], "Headphones")
    check("by index", row[0], pid)
    check_that("keys()", {"id", "name", "target_price", "currency"} <= set(row.keys()))
    check("dict(row)", dict(row)["target_price"], 300.0)
    check("a count reads by index", db.count_users(), 0)


def test_money_keeps_every_digit():
    section("IDR 1,234,567.89 round-trips exactly (Postgres REAL would round it)")
    helpers.reset_db()
    pid = db.add_product("Laptop", 1234567.89, "IDR", target_currency="IDR")
    check("target price", db.get_product(pid)["target_price"], 1234567.89)
    sid = db.add_source(pid, "https://www.lazada.co.id/products/x-i1-s2.html", None)
    db.add_snapshot(sid, 1234567.89, "IDR", "test")
    check("snapshot price", db.get_latest_snapshot(sid)["price"], 1234567.89)
    db.save_fx_rates("USD", {"IDR": 16234.123456789})
    check("fx rate", db.get_fx_rates("USD")["IDR"], 16234.123456789)


def test_ids_and_ties():
    section("New ids come from RETURNING; equal timestamps fall back to id order")
    helpers.reset_db()
    first = db.add_product("First", None)
    second = db.add_product("Second", None)
    check_that("ids increase", second > first, f"({first}, {second})")
    check("the id is the row's", db.get_product(second)["name"], "Second")

    _set_times("products", "created_at", "2026-09-01T00:00:00+00:00")
    check("products: newest first, ties by id", [p["name"] for p in db.get_products()],
          ["Second", "First"])

    a = db.add_source(first, "https://www.amazon.sg/dp/B0TEST0001", None)
    b = db.add_source(first, "https://www.lazada.sg/products/x-i1-s2.html", None)
    _set_times("sources", "created_at", "2026-09-01T00:00:00+00:00")
    check("sources: in the order added", [s["id"] for s in db.get_sources(first)], [a, b])

    for price in (10.0, 20.0, 30.0):
        db.add_snapshot(a, price, "SGD", "test", fetched_at="2026-09-02T00:00:00+00:00")
    check("snapshots: in the order added", [s["price"] for s in db.get_snapshots(a)],
          [10.0, 20.0, 30.0])
    check("latest: the last added", db.get_latest_snapshot(a)["price"], 30.0)
    check("per product: in the order added",
          [s["price"] for s in db.get_snapshots_for_product(first)], [10.0, 20.0, 30.0])


def test_usernames_ignore_case():
    section("Usernames are unique regardless of case")
    helpers.reset_db()
    uid, _ = db.create_user("Owner", "h")
    check("found by another case", db.get_user_by_name("OWNER")["id"], uid)
    try:
        db.create_user("owner", "h")
        taken = False
    except db.UsernameTaken:
        taken = True
    check("the same name in another case is taken", taken, True)


def test_driver_errors_are_translated():
    section("Driver errors become the app's own types")
    helpers.reset_db()
    try:
        db.add_snapshot(999, 1.0, "SGD")
        raised = None
    except Exception as exc:  # noqa: BLE001 -- the type is what's under test
        raised = type(exc)
    check("a refused insert raises db.IntegrityError", raised, db.IntegrityError)
    pid = db.add_product("Still writable", None)
    check_that("...and leaves nothing locked", db.get_product(pid) is not None)


def test_init_db_on_concurrent_cold_starts():
    section("Two instances creating the schema at once both succeed")
    errors = []
    for _ in range(5):
        helpers.empty_db()
        barrier = threading.Barrier(4)

        def start():
            try:
                barrier.wait()
                db.init_db()
            except Exception as exc:  # noqa: BLE001
                errors.append(repr(exc))

        threads = [threading.Thread(target=start) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    check("no start failed (5 rounds x 4)", errors, [])
    check("the schema works", db.count_users(), 0)


def test_first_sign_up_race():
    section("Racing first sign-ups make exactly one admin")
    admins = []
    for _ in range(10):
        helpers.reset_db()
        barrier = threading.Barrier(4)

        def sign_up(name):
            barrier.wait()
            db.create_user(name, "h")

        threads = [threading.Thread(target=sign_up, args=(f"user{i}",)) for i in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        admins.append(sum(1 for u in db.list_users() if u["role"] == "admin"))
    check("one admin every time (10 races x 4)", admins, [1] * 10)


def test_existing_sqlite_database_unchanged():
    section("A database made by the previous version opens unchanged")
    if helpers.on_postgres():
        print("  skipped: SQLite files only")
        return
    helpers.empty_db()
    conn = db.get_connection()
    conn.executescript(db.schema("sqlite").replace("DOUBLE PRECISION", "REAL"))
    conn.execute("INSERT INTO products (name, target_price, currency, created_at) "
                 "VALUES ('Old', 99.5, 'SGD', '2026-09-01T00:00:00+00:00')")
    conn.commit()
    before = [tuple(r) for r in conn.execute("SELECT sql FROM sqlite_master ORDER BY name")]
    conn.close()
    db.init_db()
    conn = db.get_connection()
    after = [tuple(r) for r in conn.execute("SELECT sql FROM sqlite_master ORDER BY name")]
    conn.close()
    check("schema untouched", after, before)
    check("row kept", (db.get_products()[0]["name"], db.get_products()[0]["target_price"]),
          ("Old", 99.5))


def test_test_database_guard():
    section("Tests refuse to erase anything but a local throwaway database")
    for url, allowed in [
        ("postgresql://u:p@ep-cool-1.ap-southeast-1.aws.neon.tech/neondb", False),
        ("postgresql://postgres:postgres@db.example.com:5432/test", False),
        ("postgresql://postgres:postgres@localhost:5433/test", True),
        ("postgresql://postgres:postgres@127.0.0.1:5432/test", True),
    ]:
        try:
            helpers.check_test_database_url(url, production_url="")
            ok = True
        except helpers.UnsafeTestDatabase:
            ok = False
        check(f"{url.split('@')[1].split('/')[0]}", ok, allowed)
    local = "postgresql://postgres:postgres@localhost:5433/test"
    try:
        helpers.check_test_database_url(local, production_url=local)
        same = True
    except helpers.UnsafeTestDatabase:
        same = False
    check("the same URL as DATABASE_URL", same, False)

    before = (db.DATABASE_URL, db.DB_PATH)
    with _env(TEST_DATABASE_URL="postgresql://u:p@ep-cool-1.aws.neon.tech/neondb"):
        try:
            helpers.use_temp_db()
            refused = False
        except helpers.UnsafeTestDatabase:
            refused = True
    check("use_temp_db refuses a remote URL", refused, True)
    check("...before switching to it", db.DATABASE_URL, before[0])
    db.DATABASE_URL, db.DB_PATH = before


# --- outages -----------------------------------------------------------------------------

class _dead_database:
    """Point the port at a database that doesn't answer."""

    def __enter__(self):
        self.saved = (db.DATABASE_URL, db.DB_PATH, db.POOL_TIMEOUT_S)
        if helpers.on_postgres():
            db.POOL_TIMEOUT_S = 1.0
            db.DATABASE_URL = "postgresql://postgres:postgres@127.0.0.1:1/test"  # nothing listens
        else:
            blocker = Path(tempfile.mkdtemp()) / "a-file"
            blocker.write_text("not a directory")
            db.DB_PATH = blocker / "test.db"  # its parent is a file: can't be opened

    def __exit__(self, *exc):
        db.DATABASE_URL, db.DB_PATH, db.POOL_TIMEOUT_S = self.saved


def test_outage_is_not_empty_data():
    section("A database outage is a 503, never an empty dashboard")
    helpers.reset_db()
    c = helpers.client()
    owner = db.get_user_by_name("owner")
    db.add_product("Headphones", None, user_id=owner["id"])
    check("dashboard shows the product", "Headphones" in c.get("/").text, True)

    with _dead_database():
        try:
            db.get_connection().close()
            raised = None
        except Exception as exc:  # noqa: BLE001
            raised = type(exc)
        check("the port raises DatabaseUnavailable", raised, db.DatabaseUnavailable)
        r = c.get("/")
        check("dashboard: 503", r.status_code, 503)
        check_that("...says the data couldn't be loaded", "couldn't load your data" in r.text)
        check_that("...never 'Nothing tracked yet'", "Nothing tracked yet" not in r.text)
        check("...asks to retry later", r.headers.get("retry-after"), "30")

    r = c.get("/")
    check("database back: the product again", (r.status_code, "Headphones" in r.text), (200, True))


def test_healthz():
    section("/healthz says whether the app and database answer, and nothing else")
    helpers.reset_db()
    c = helpers.client(signed_in_as=None)
    r = c.get("/healthz")
    check("healthy", (r.status_code, r.json()), (200, {"app": "ok", "database": "ok"}))
    with _dead_database():
        r = c.get("/healthz")
    check("database down", (r.status_code, r.json()), (503, {"app": "ok", "database": "unreachable"}))
    leaks = [w for w in ("postgres", "sqlite", "neon", "@", "127.0.0.1") if w in r.text.lower()]
    check("no backend, host or credentials in the body", leaks, [])


# --- scheduling -------------------------------------------------------------------------

def test_scheduler_mode():
    section("SCHEDULER_MODE: in-process keeps the interval job; cron adds none")
    from apscheduler.schedulers.background import BackgroundScheduler
    saved = scheduler._scheduler
    try:
        for value, expected_mode, expect_job in [(None, "in-process", True), ("", "in-process", True),
                                                 ("cron", "cron", False), ("CRON", "cron", False)]:
            with _env(SCHEDULER_MODE=value):
                scheduler._scheduler = BackgroundScheduler()
                scheduler.start_scheduler()
                check(f"{value!r}: mode", scheduler.mode(), expected_mode)
                check(f"{value!r}: interval job",
                      scheduler._scheduler.get_job(scheduler.REFRESH_JOB_ID) is not None, expect_job)
                if expected_mode == "cron":
                    scheduler.run_once("probe", lambda: None)
                    check("cron: run_once still queues jobs",
                          scheduler._scheduler.get_job("probe") is not None
                          or scheduler._scheduler.running, True)
                scheduler.stop_scheduler()
    finally:
        scheduler._scheduler = saved


def _tracked_sources(n):
    pid = db.add_product("Tracked", None)
    return pid, [db.add_source(pid, f"https://www.amazon.sg/dp/B0TEST000{i}", None) for i in range(n)]


def test_stalest_first():
    section("The daily refresh starts with the listings checked longest ago")
    helpers.reset_db()
    pid, (a, b, c, d, e) = _tracked_sources(5)
    db.add_snapshot(b, 10.0, "SGD", "test", fetched_at="2026-09-20T10:00:00+00:00")
    db.add_snapshot(c, 10.0, "SGD", "test", fetched_at="2026-09-20T09:00:00+00:00")
    db.add_snapshot(d, None, error="blocked", fetched_at="2026-09-20T08:00:00+00:00")
    db.add_snapshot(d, 9.0, "SGD", "wayback:x", fetched_at="2026-09-21T00:00:00+00:00",
                    origin="wayback", origin_ref="https://web.archive.org/x")
    db.add_snapshot(e, 9.0, "SGD", "wayback:x", fetched_at="2026-09-21T00:00:00+00:00",
                    origin="wayback", origin_ref="https://web.archive.org/y")
    check("never checked first (by id), then oldest live check; archived rows don't count",
          refresh.stalest_first(), [a, e, d, c, b])


class _FakeClock:
    """Moves on `step` seconds each time a price check runs."""

    def __init__(self, step):
        self.now, self.step = 1000.0, step

    def __call__(self):
        return self.now


def _stub_checks(clock=None):
    """refresh_source stand-in: records the listing and stores a live check."""
    checked = []

    def fake(source_id):
        checked.append(source_id)
        db.add_snapshot(source_id, 1.0, "SGD", "test")
        if clock is not None:
            clock.now += clock.step

    return checked, fake


def test_daily_run_budget():
    section("The daily run stops starting checks at its deadline; the next run carries on")
    helpers.reset_db()
    pid, ids = _tracked_sources(6)
    clock = _FakeClock(step=60)  # each check "takes" a minute
    checked, fake = _stub_checks(clock)
    saved = refresh.refresh_source, refresh.DELAY_BETWEEN_REQUESTS
    refresh.refresh_source, refresh.DELAY_BETWEEN_REQUESTS = fake, 0
    saved_sources = history.HISTORY_SOURCES
    history.HISTORY_SOURCES = [lambda source, adapter, stop=None: history.HistoryResult("none", reason="fake")]
    try:
        report = scheduler.daily_run(clock=clock)
        check("checks started before the deadline (0, 60, 120 s < 150 s)", report["refreshed"], 3)
        check("...the rest left for next time", report["refresh_left"], 3)
        check("...stalest first", checked, ids[:3])
        clock.now += 86400
        checked.clear()
        scheduler.daily_run(clock=clock)
        check("the next run starts with the ones it didn't reach", checked, ids[3:])
    finally:
        refresh.refresh_source, refresh.DELAY_BETWEEN_REQUESTS = saved
        history.HISTORY_SOURCES = saved_sources


def test_cut_short_lookup_is_resumed():
    section("An archive lookup stopped by the deadline records nothing and is resumed")
    helpers.reset_db()
    pid, (sid,) = _tracked_sources(1)
    cut = lambda source, adapter, stop=None: history.HistoryResult(  # noqa: E731
        "unavailable", reason=history.CUT_SHORT_REASON)
    history.backfill_source(sid, lookups=[cut], stop=lambda: True)
    check("cut short: still unchecked", db.get_source(sid)["history_checked_at"], None)
    check("...so the daily sweep will resume it", db.get_products_with_unchecked_sources(), [pid])

    captures = [(f"2025{m:02d}01000000", "https://www.amazon.sg/dp/B0TEST0000") for m in (1, 2, 3)]
    fetched = []

    class _Resp:
        status_code, text = 200, "[captures]"

        def json(self):
            return [["timestamp", "original"], *captures]

    def get(url, *args, **kwargs):
        if "id_/" in url:
            fetched.append(url)
        return _Resp()

    result = history.wayback_lookup(
        db.get_source(sid), history.adapter_for("https://www.amazon.sg/"),
        get=get, sleep=lambda s: None, stop=lambda: len(fetched) >= 1, paused=lambda: False)
    check("wayback: one of three copies fetched, then stopped", len(fetched), 1)
    check("wayback stops before its next request", result.reason, history.CUT_SHORT_REASON)


def test_cron_endpoint():
    section("/cron/daily: the host's secret or nothing")
    helpers.reset_db()
    pid, ids = _tracked_sources(2)
    checked, fake = _stub_checks()
    looked_up = []

    def lookup(source, adapter, stop=None):
        looked_up.append(source["id"])
        return history.HistoryResult("none", reason="No copies (fake).")

    saved = refresh.refresh_source, refresh.DELAY_BETWEEN_REQUESTS, history.HISTORY_SOURCES
    refresh.refresh_source, refresh.DELAY_BETWEEN_REQUESTS = fake, 0
    history.HISTORY_SOURCES = [lookup]
    c = helpers.client(signed_in_as=None)
    try:
        with _env(CRON_SECRET=None):
            check("no secret configured: no such page", c.get("/cron/daily").status_code, 404)
        with _env(CRON_SECRET="s3cret-value"):
            check("no Authorization", c.get("/cron/daily").status_code, 401)
            check("wrong secret", c.get("/cron/daily", headers={"Authorization": "Bearer nope"}).status_code, 401)
            check("secret without Bearer",
                  c.get("/cron/daily", headers={"Authorization": "s3cret-value"}).status_code, 401)
            check("...and refused calls did no work", (checked, looked_up), ([], []))

            site_settings.set_history_paused(True)
            r = c.get("/cron/daily", headers={"Authorization": "Bearer s3cret-value"})
            check("paused: runs", r.status_code, 200)
            check("...prices checked, stalest first", checked, ids)
            check("...but no archive request", looked_up, [])
            check("...and says so", r.json()["history_paused"], True)

            site_settings.set_history_paused(False)
            checked.clear()
            r = c.get("/cron/daily", headers={"Authorization": "Bearer s3cret-value"})
            check("unpaused: interrupted lookups resumed", sorted(looked_up), sorted(ids))
            check("...and recorded", [db.get_source(s)["history_note"] for s in ids],
                  ["No copies (fake)."] * 2)
            check("report", {k: r.json()[k] for k in ("refreshed", "refresh_left", "history_products",
                                                       "history_products_left")},
                  {"refreshed": 2, "refresh_left": 0, "history_products": 1, "history_products_left": 0})
    finally:
        refresh.refresh_source, refresh.DELAY_BETWEEN_REQUESTS, history.HISTORY_SOURCES = saved


# --- behind the proxy ------------------------------------------------------------------

def test_forwarded_host():
    section("The cross-site guard compares against the public host behind the proxy")
    helpers.reset_db()
    c = helpers.client()
    proxied = {"host": "internal-1234.vercel.internal", "x-forwarded-host": "deals.example.app"}
    r = c.post("/logout", headers={**proxied, "origin": "https://deals.example.app"})
    check("own form, internal host header: accepted", r.status_code, 303)
    helpers.sign_in(c, "owner")
    r = c.post("/logout", headers={**proxied, "origin": "https://evil.example"})
    check("cross-site origin: still refused", r.status_code, 403)
    check_that("...with the usual message", "submitted from another website" in r.text)
    r = c.post("/logout", headers={"origin": "http://testserver"})
    check("no forwarded host: same host as today", r.status_code, 303)
    helpers.sign_in(c, "owner")
    r = c.post("/logout", headers={"origin": "https://evil.example"})
    check("no forwarded host: cross-site refused", r.status_code, 403)


def test_secure_cookie_over_https():
    section("Over HTTPS the session cookie is Secure and HttpOnly")
    from fastapi.testclient import TestClient
    from app import main
    helpers.reset_db()
    secure = TestClient(main.app, base_url="https://testserver", follow_redirects=False)
    r = secure.post("/register", data={"username": "owner", "password": helpers.TEST_PASSWORD,
                                       "confirm": helpers.TEST_PASSWORD})
    cookie = r.headers.get("set-cookie", "")
    check("https: Secure", "secure" in cookie.lower(), True)
    check("https: HttpOnly", "httponly" in cookie.lower(), True)
    plain = TestClient(main.app, follow_redirects=False)
    r = plain.post("/login", data={"username": "owner", "password": helpers.TEST_PASSWORD})
    check("plain http (local): not Secure", "secure" in r.headers.get("set-cookie", "").lower(), False)


# --- admin page -------------------------------------------------------------------------

def test_admin_schedule_display():
    section("Admin page: the host's daily schedule instead of an interval it can't keep")
    helpers.reset_db()
    owner = helpers.client()
    with _env(SCHEDULER_MODE=None):
        page = owner.get("/admin").text
        check("in-process: interval field", 'name="refresh_interval_hours"' in page, True)
    with _env(SCHEDULER_MODE="cron"):
        page = owner.get("/admin").text
        check("cron: no interval field", 'name="refresh_interval_hours"' in page, False)
        check_that("cron: says the host sets it", "once a day, set by the host" in page)
        r = owner.post("/admin/settings", data={
            "default_currency": "MYR", "search_domains": ["amazon.sg"],
            "refresh_interval_hours": "12", "discover_per_shop": "5", "discover_price_limit": "4"})
        check("save: accepted", r.headers["location"], "/admin?notice=settings")
        check("interval posted anyway: nothing stored", db.get_setting("refresh_interval_hours"), None)
        check("...other settings saved", site_settings.default_currency(), "MYR")
        r = owner.post("/admin/settings", data={
            "default_currency": "MYR", "search_domains": ["amazon.sg"],
            "refresh_interval_hours": "0", "discover_per_shop": "5", "discover_price_limit": "4"})
        check("an out-of-range interval isn't even checked", r.headers["location"], "/admin?notice=settings")


TESTS = [
    test_rows_read_like_sqlite,
    test_money_keeps_every_digit,
    test_ids_and_ties,
    test_usernames_ignore_case,
    test_driver_errors_are_translated,
    test_init_db_on_concurrent_cold_starts,
    test_first_sign_up_race,
    test_existing_sqlite_database_unchanged,
    test_test_database_guard,
    test_outage_is_not_empty_data,
    test_healthz,
    test_scheduler_mode,
    test_stalest_first,
    test_daily_run_budget,
    test_cut_short_lookup_is_resumed,
    test_cron_endpoint,
    test_forwarded_host,
    test_secure_cookie_over_https,
    test_admin_schedule_display,
]

if __name__ == "__main__":
    for test in TESTS:
        test()
    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S):")
        for f in FAILURES:
            print("  -", f)
        sys.exit(1)
    print(f"All hosting tests passed ({ENGINE}).")
