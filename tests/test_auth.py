"""Accounts, sessions, access control and the admin page.

Offline: a throwaway SQLite file, TestClient without startup, no network.

Run: python -m tests.test_auth
"""

import sys
from datetime import timedelta

from app import auth
from app import database as db
from app import site_settings
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


def _no_network(*args, **kwargs):
    raise AssertionError(f"test_auth tried to reach the network: {args[:2]}")


# This suite is offline. Any HTTP call through requests (FX rates, shops, the
# archive) fails loudly instead of quietly depending on the network.
import requests as _requests
_requests.Session.request = _no_network


def fresh_db():
    helpers.reset_db()
    auth._failures.clear()


# --- data ------------------------------------------------------------------------------

def test_storage():
    section("Users, ownership and cascades")
    if helpers.on_postgres():
        # Postgres always starts from the current schema, so there's no upgrade
        # path to test: an unowned product stands in for one from before accounts.
        helpers.reset_db()
        db.add_product("Headphones", None)
    else:
        # A database from before accounts: products have no owner column.
        helpers.empty_db()
        conn = db.get_connection()
        conn.executescript("""
            CREATE TABLE products (id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL,
                target_price REAL, target_currency TEXT, currency TEXT, created_at TEXT NOT NULL);
            INSERT INTO products (name, created_at) VALUES ('Headphones', '2026-09-01T00:00:00+00:00');
        """)
        conn.commit()
        conn.close()
        db.init_db()
    db.init_db()
    check("existing product kept, unowned", db.get_product(1)["user_id"], None)

    admin_id, role = db.create_user("owner", auth.hash_password("x" * 8))
    check("first user is admin", role, "admin")
    check("...and owns the existing product", db.get_product(1)["user_id"], admin_id)
    user_id, role = db.create_user("bob", auth.hash_password("x" * 8))
    check("second user is a user", role, "user")
    check("...and claims nothing", [p["id"] for p in db.get_products_for_user(user_id)], [])

    try:
        db.create_user("OWNER", "h")
        taken = False
    except db.UsernameTaken:
        taken = True
    check("usernames are case-insensitive unique", taken, True)

    pid = db.add_product("Bob's", None, user_id=user_id)
    sid = db.add_source(pid, "https://www.amazon.sg/dp/B0TEST0001", None)
    db.add_snapshot(sid, 10.0, "SGD")
    db.add_session("h" * 64, user_id, "2099-01-01T00:00:00+00:00")
    db.delete_user(user_id)
    check("deleting a user deletes their products", db.get_product(pid), None)
    check("...their sources", db.get_source(sid), None)
    check("...and their sessions", db.get_session("h" * 64), None)
    check("other users untouched", db.get_product(1)["user_id"], admin_id)


# --- passwords -------------------------------------------------------------------------

def test_passwords():
    section("Passwords are salted scrypt, never plain text")
    encoded = auth.hash_password("correct-horse")
    check("verifies", auth.verify_password("correct-horse", encoded), True)
    check("wrong password", auth.verify_password("correct-hors", encoded), False)
    check_that("no plain text in the hash", "correct-horse" not in encoded)
    check("salted: two hashes differ", auth.hash_password("correct-horse") != encoded, True)
    tampered = encoded[:-4] + ("AAAA" if not encoded.endswith("AAAA") else "BBBB")
    check("tampered hash never matches", auth.verify_password("correct-horse", tampered), False)
    check("garbage never matches", auth.verify_password("x", "not-a-hash"), False)

    check("short username refused", auth.username_problem("ab") is not None, True)
    check("odd characters refused", auth.username_problem("bob smith") is not None, True)
    check("good username", auth.username_problem("bob.smith_1"), None)
    check("7-char password refused", auth.password_problem("1234567") is not None, True)
    check("8-char password ok", auth.password_problem("12345678"), None)


# --- sessions ----------------------------------------------------------------------------

def test_sessions():
    section("Sessions: hashed at rest, expire, end on sign-out or disable")
    fresh_db()
    user = auth.register("owner", "correct-horse")
    token = auth.start_session(user["id"])
    check("token identifies the user", auth.user_for_token(token)["id"], user["id"])
    conn = db.get_connection()
    stored = [r["token_hash"] for r in conn.execute("SELECT token_hash FROM sessions")]
    conn.close()
    check_that("raw token not stored", token not in stored and len(stored) == 1)

    conn = db.get_connection()
    conn.execute("UPDATE sessions SET expires_at = '2000-01-01T00:00:00+00:00'")
    conn.commit()
    conn.close()
    check("expired session rejected", auth.user_for_token(token), None)

    token = auth.start_session(user["id"])
    bob = auth.register("bob", "correct-horse")
    bob_token = auth.start_session(bob["id"])
    auth.set_disabled(bob["id"], True)
    check("disabling ends sessions", auth.user_for_token(bob_token), None)
    auth.end_session(token)
    check("sign-out ends the session", auth.user_for_token(token), None)
    check("unknown token", auth.user_for_token("nope"), None)


def test_sign_in_and_throttle():
    section("Sign-in: one message for every failure; guessing is stopped")
    fresh_db()
    auth.register("alice", "correct-horse")
    now = [1000.0]
    saved_clock = auth._clock
    auth._clock = lambda: now[0]
    try:
        messages = set()
        for username, password in (("alice", "wrong-pass"), ("nobody", "wrong-pass")):
            try:
                auth.authenticate(username, password)
            except auth.AuthError as exc:
                messages.add(str(exc))
        check("wrong password and unknown user look the same", messages, {"Wrong username or password."})

        calls = []
        saved_verify = auth.verify_password
        auth.verify_password = lambda p, h: calls.append(h) or False
        try:
            try:
                auth.authenticate("ghost", "whatever1")
            except auth.AuthError:
                pass
        finally:
            auth.verify_password = saved_verify
        check("unknown user still costs a hash check", calls, [auth._DUMMY_HASH])

        auth._failures.clear()
        for _ in range(5):
            try:
                auth.authenticate("alice", "wrong-pass")
            except auth.AuthError:
                pass
        try:
            auth.authenticate("ALICE", "correct-horse")
            locked = None
        except auth.AuthError as exc:
            locked = str(exc)
        check_that("5 failures lock the username (any case)", locked and "Too many" in locked, f"({locked})")
        now[0] += auth.LOCK_WINDOW_S + 1
        check("lock expires", auth.authenticate("alice", "correct-horse")["username"], "alice")
    finally:
        auth._clock = saved_clock
        auth._failures.clear()

    bob = auth.register("bob", "correct-horse")
    auth.set_disabled(bob["id"], True)
    try:
        auth.authenticate("bob", "correct-horse")
        refused = None
    except auth.AuthError as exc:
        refused = str(exc)
    check_that("disabled account refused", refused and "disabled" in refused, f"({refused})")
    auth.set_disabled(bob["id"], False)
    check("re-enabled account signs in", auth.authenticate("bob", "correct-horse")["username"], "bob")


def test_access_helpers():
    section("Only local redirects; only your own products")
    for target, expected in (("/product/3?x=1", "/product/3?x=1"), ("https://evil.example/", "/"),
                             ("//evil.example", "/"), ("/\\evil.example", "/"),
                             ("javascript:alert(1)", "/"), ("", "/"), (None, "/"),
                             ("/ok\r\nSet-Cookie: x=1", "/")):
        check(f"local_path({target!r})", auth.local_path(target), expected)

    fresh_db()
    admin = auth.register("owner", "correct-horse")
    alice = auth.register("alice", "correct-horse")
    bob = auth.register("bob", "correct-horse")
    alices = db.add_product("Alice's", None, user_id=alice["id"])
    unowned = db.add_product("Old", None)

    def status(user, pid):
        try:
            auth.product_for(user, pid)
            return 200
        except Exception as exc:
            return getattr(exc, "status_code", None)

    check("owner sees it", status(alice, alices), 200)
    check("another user: 404", status(bob, alices), 404)
    check("admin sees it", status(admin, alices), 200)
    check("missing product: same 404", status(bob, 9999), 404)
    check("unowned product: admin only", (status(admin, unowned), status(bob, unowned)), (200, 404))


def test_last_admin_guard():
    section("The site always keeps an admin")
    fresh_db()
    admin = auth.register("owner", "correct-horse")
    bob = auth.register("bob", "correct-horse")
    for label, action in (("demote", lambda: auth.change_role(admin["id"], "user")),
                          ("disable", lambda: auth.set_disabled(admin["id"], True)),
                          ("delete", lambda: auth.delete_account(admin["id"]))):
        try:
            action()
            outcome = "allowed"
        except auth.AuthError as exc:
            outcome = str(exc)
        check(f"last admin: {label} refused", outcome, "The site needs at least one admin.")
    auth.change_role(bob["id"], "admin")
    auth.change_role(admin["id"], "user")
    check("with a second admin, demotion works", db.get_user(admin["id"])["role"], "user")


# --- site settings ------------------------------------------------------------------

def _refused(fn, *args) -> bool:
    try:
        fn(*args)
        return False
    except ValueError:
        return True


def test_site_settings():
    section("Site settings: DB, then env, then default; invalid values refused")
    import os
    fresh_db()
    check("default refresh interval", site_settings.refresh_interval_hours(), 6)
    os.environ["REFRESH_INTERVAL_HOURS"] = "8"
    try:
        check("env fallback", site_settings.refresh_interval_hours(), 8.0)
        site_settings.save_number("refresh_interval_hours", site_settings.clean_number("refresh_interval_hours", "12"))
        check("admin value wins over env", site_settings.refresh_interval_hours(), 12.0)
    finally:
        del os.environ["REFRESH_INTERVAL_HOURS"]
    for key, bad in (("refresh_interval_hours", "0"), ("refresh_interval_hours", "abc"),
                     ("discover_per_shop", "21"), ("discover_per_shop", "2.5"),
                     ("discover_price_limit", "-1")):
        check(f"{key}={bad!r} refused", _refused(site_settings.clean_number, key, bad), True)
    check("0 price lookups allowed", site_settings.clean_number("discover_price_limit", "0"), 0.0)

    check("known shops accepted, in list order",
          site_settings.clean_search_domains(["lazada.sg", "amazon.sg", "amazon.sg"]), ["amazon.sg", "lazada.sg"])
    for bad in (["evil.example"], [], ["amazon.evil.example"], ["amazon.sg,evil.example"]):
        check(f"search domains {bad} refused", _refused(site_settings.clean_search_domains, bad), True)

    check("unknown default currency refused", _refused(site_settings.clean_currency, "XYZ"), True)
    check("currency normalised", site_settings.clean_currency("myr"), "MYR")


def test_settings_apply_without_restart():
    section("Settings take effect at once")
    from app import history, scheduler
    from app.refresh import refresh_all
    from app.search.providers import search_domains
    fresh_db()
    site_settings.save_search_domains(["amazon.sg"])
    check("search uses the new shops", search_domains(), ["amazon.sg"])

    site_settings.set_history_paused(True)
    try:
        history.schedule_backfill(1)
        check("paused: no archive lookup scheduled", scheduler._scheduler.get_job("history-1"), None)
    finally:
        site_settings.set_history_paused(False)

    scheduler._scheduler.add_job(refresh_all, "interval", hours=6, id=scheduler.REFRESH_JOB_ID)
    try:
        # The scheduler isn't started in tests, so jobs have no next_run_time yet; a
        # reschedule (which restarts the countdown) shows up as a new trigger object.
        before = scheduler._scheduler.get_job(scheduler.REFRESH_JOB_ID).trigger
        scheduler.set_refresh_interval(6)
        check_that("same interval: countdown not restarted",
                   scheduler._scheduler.get_job(scheduler.REFRESH_JOB_ID).trigger is before)
        scheduler.set_refresh_interval(12)
        job = scheduler._scheduler.get_job(scheduler.REFRESH_JOB_ID)
        check("new interval: job rescheduled", job.trigger.interval, timedelta(hours=12))
    finally:
        scheduler._scheduler.remove_all_jobs()


# --- the web layer -------------------------------------------------------------------

def _no_live_fetches():
    """Tracking would fetch real shop pages and schedule archive lookups: stub both."""
    from app import main
    saved = (main.refresh_product, main.refresh_source, main.history.schedule_backfill)
    main.refresh_product = main.refresh_source = lambda _id: None
    main.history.schedule_backfill = lambda *a, **k: None
    return lambda: setattr_many(main, saved)


def setattr_many(main, saved):
    main.refresh_product, main.refresh_source, main.history.schedule_backfill = saved


def _track(c, name, url="https://www.amazon.sg/dp/B0TEST0001"):
    r = c.post("/products", data={"name": name, "url": url})
    assert r.status_code == 303, r.text[:200]
    return int(r.headers["location"].rsplit("/", 1)[1])


def test_account_routes():
    section("Register, sign in, sign out, and only local redirects")
    fresh_db()
    anon = helpers.client(signed_in_as=None)
    check_that("first-run banner on register", "becomes the site's" in anon.get("/register").text)
    r = anon.post("/register", data={"username": "owner", "password": "correct-horse",
                                     "confirm": "correct-horse"})
    check("register signs in and redirects", (r.status_code, r.headers["location"]), (303, "/"))
    cookie = r.headers["set-cookie"].lower()
    check_that("cookie is HttpOnly, SameSite=Lax, Path=/",
               "httponly" in cookie and "samesite=lax" in cookie and "path=/" in cookie, f"({cookie[:90]})")
    check("first account is admin", db.get_user_by_name("owner")["role"], "admin")

    other = helpers.client(signed_in_as=None)
    for data, expected in (
        ({"username": "OWNER", "password": "correct-horse", "confirm": "correct-horse"}, "That username is taken."),
        ({"username": "bob", "password": "short", "confirm": "short"}, "Passwords must be"),
        ({"username": "bob", "password": "correct-horse", "confirm": "different-1"}, "don&#39;t match"),
    ):
        r = other.post("/register", data=data)
        check_that(f"register refused: {expected}", r.status_code == 400 and expected in r.text,
                   f"({r.status_code})")
    check("...and nothing was created", db.count_users(), 1)

    bodies = [other.post("/login", data={"username": u, "password": "wrong-pass-1"}).text
              for u in ("owner", "nobody")]
    check_that("wrong password and unknown user render the same message",
               all("Wrong username or password." in b for b in bodies))

    r = other.post("/login", data={"username": "owner", "password": "correct-horse",
                                   "next": "/discover?q=x"})
    check("local next honoured", r.headers["location"], "/discover?q=x")
    other.post("/logout")
    r = other.post("/login", data={"username": "owner", "password": "correct-horse",
                                   "next": "https://evil.example/"})
    check("foreign next ignored", r.headers["location"], "/")
    # Fresh cached rates, so choosing a currency doesn't go and fetch new ones.
    db.save_fx_rates("USD", {"USD": 1.0, "SGD": 1.28, "MYR": 4.09})
    r = other.post("/settings/currency", data={"currency": "MYR", "next_url": "//evil.example"})
    check("currency redirect stays local", r.headers["location"], "/")
    check("preference saved for this user", db.get_user_by_name("owner")["display_currency"], "MYR")

    r = other.post("/logout")
    check("sign-out redirects to login", r.headers["location"], "/login?signed_out=1")
    r = other.get("/")
    check("signed out: dashboard asks to sign in", (r.status_code, r.headers["location"]), (303, "/login?next=/"))


def test_same_site_guard():
    section("Cross-site form posts are refused")
    fresh_db()
    restore = _no_live_fetches()
    try:
        c = helpers.client()
        pid = _track(c, "Headphones")
        r = c.post(f"/products/{pid}/delete", headers={"Origin": "https://evil.example"})
        check("foreign Origin: 403", r.status_code, 403)
        check("...product still there", db.get_product(pid) is not None, True)
        r = c.post(f"/products/{pid}/delete", headers={"Referer": "https://evil.example/page"})
        check("foreign Referer: 403", r.status_code, 403)
        r = c.post(f"/products/{pid}/delete", headers={"Origin": "null"})
        check("Origin null: 403", r.status_code, 403)
        r = c.post(f"/products/{pid}/delete", headers={"Origin": "http://testserver"})
        check("same origin: allowed", r.status_code, 303)
        pid = _track(c, "Headphones 2")
        check("no Origin at all (tools): allowed", c.post(f"/products/{pid}/delete").status_code, 303)
    finally:
        restore()


def test_products_are_private():
    section("Each user's products are theirs; admins can see all")
    from app import main, scheduler
    fresh_db()
    restore = _no_live_fetches()
    try:
        owner = helpers.client("owner")
        alice = helpers.client("alice")
        bob = helpers.client("bob")
        pid = _track(alice, "Alice's headphones")
        sid = db.get_sources(pid)[0]["id"]
        check("stamped with the owner", db.get_product(pid)["user_id"], db.get_user_by_name("alice")["id"])

        for label, call in (
            ("view", lambda: bob.get(f"/product/{pid}")),
            ("delete", lambda: bob.post(f"/products/{pid}/delete")),
            ("refresh", lambda: bob.post(f"/products/{pid}/refresh")),
            ("add shop", lambda: bob.post(f"/products/{pid}/sources", data={"url": "https://www.lazada.sg/p/x"})),
            ("remove shop", lambda: bob.post(f"/sources/{sid}/delete")),
            ("archive lookup", lambda: bob.post(f"/products/{pid}/history")),
        ):
            check(f"another user's {label}: 404", call().status_code, 404)
        check("...product untouched", (db.get_product(pid) is not None, len(db.get_sources(pid))), (True, 1))

        check_that("owner's dashboard lists it", "Alice&#39;s headphones" in alice.get("/").text)
        check_that("another user's dashboard doesn't", "Alice&#39;s headphones" not in bob.get("/").text)
        page = owner.get(f"/product/{pid}")
        check_that("admin can open it, and sees whose it is",
                   page.status_code == 200 and "Tracked by <strong>alice</strong>" in page.text)
        check_that("...but it isn't on the admin's own dashboard", "Alice&#39;s headphones" not in owner.get("/").text)

        mine = _track(bob, "Bob's")
        r = bob.post("/refresh")
        check("'Refresh my prices' returns at once", r.headers["location"], "/?refreshing=1")
        bob_id = db.get_user_by_name("bob")["id"]
        job = scheduler._scheduler.get_job(f"refresh-user-{bob_id}")
        check("...queued in the background, your products only", job and job.args, ([mine],))
        bob.post("/refresh")
        jobs = [j.id for j in scheduler._scheduler.get_jobs()]
        check("...a second click doesn't start a second refresh", jobs.count(f"refresh-user-{bob_id}"), 1)
        check_that("dashboard says it's refreshing", "Refreshing your prices in the background" in bob.get("/?refreshing=1").text)
    finally:
        scheduler._scheduler.remove_all_jobs()
        restore()


def test_public_search():
    section("Searching is public; tracking and everything else needs an account")
    from app import main
    from app.search import site_search
    fresh_db()
    anon = helpers.client(signed_in_as=None)
    page = anon.get("/discover?q=headphones")
    check("anonymous search page", page.status_code, 200)
    check_that("...invites sign-in to track", "to track these" in page.text and 'name="target_currency"' not in page.text)
    check_that("...top bar offers Log in and Register", ">Log in</a>" in page.text and ">Register</a>" in page.text)

    saved = site_search.search_all
    site_search.search_all = lambda q, d, per_shop=6: iter([("amazon.sg", "Amazon", [], None)])
    try:
        body = anon.get("/discover/stream?q=headphones").text
    finally:
        site_search.search_all = saved
    check_that("anonymous stream works", '"type": "shop"' in body and '"type": "done"' in body)

    r = anon.post("/discover/track", data={"name": "X", "urls": ["https://www.amazon.sg/dp/B0TEST0001"]})
    check("anonymous track: sent to sign in", (r.status_code, r.headers["location"].startswith("/login")), (303, True))
    check("...nothing tracked", db.get_products(), [])
    for path in ("/", "/product/1", "/admin"):
        r = anon.get(path)
        check(f"anonymous {path}: sign in, then back", (r.status_code, r.headers["location"]),
              (303, "/login?next=" + path))


def test_currency_is_personal():
    section("Display currency is per user; visitors get the site default")
    from app import main
    fresh_db()
    db.save_fx_rates("USD", {"USD": 1.0, "SGD": 1.28, "MYR": 4.09})
    site_settings.save_default_currency("SGD")
    owner = helpers.client("owner")
    alice = helpers.client("alice")
    alice.post("/settings/currency", data={"currency": "MYR"})
    check("alice sees MYR", main.display_currency(db.get_user_by_name("alice")), "MYR")
    check("owner (no choice) sees the site default", main.display_currency(db.get_user_by_name("owner")), "SGD")
    check("anonymous sees the site default", main.display_currency(None), "SGD")
    check_that("alice's picker preselects MYR", '<option value="MYR" selected>' in alice.get("/").text)
    check_that("admin link for admins", 'href="/admin"' in owner.get("/").text)
    check_that("no admin link for users", 'href="/admin"' not in alice.get("/").text)


def test_admin_page():
    section("The admin page: users, settings, maintenance")
    from app import admin as admin_routes, main, scheduler
    fresh_db()
    restore = _no_live_fetches()
    try:
        owner = helpers.client("owner")
        bob = helpers.client("bob")
        alice = helpers.client("alice")
        bob_id = db.get_user_by_name("bob")["id"]
        alice_id = db.get_user_by_name("alice")["id"]
        owner_id = db.get_user_by_name("owner")["id"]
        alices = _track(alice, "Alice's")

        check("user: GET /admin forbidden", bob.get("/admin").status_code, 403)
        for path, data in ((f"/admin/users/{bob_id}/role", {"role": "admin"}),
                           (f"/admin/users/{alice_id}/disable", {}),
                           (f"/admin/users/{alice_id}/delete", {}),
                           ("/admin/settings", {"default_currency": "MYR"}),
                           ("/admin/maintenance/history", {"action": "pause"})):
            check(f"user: POST {path} forbidden", bob.post(path, data=data).status_code, 403)
        check("...nothing changed", (db.get_user(bob_id)["role"], db.get_user(alice_id)["disabled_at"],
                                     site_settings.history_paused()), ("user", None, False))

        page = owner.get("/admin")
        check_that("admin sees every user", all(n in page.text for n in ("owner", "alice", "bob")))

        owner.post(f"/admin/users/{bob_id}/role", data={"role": "admin"})
        check("promoted user can open admin", bob.get("/admin").status_code, 200)
        owner.post(f"/admin/users/{bob_id}/role", data={"role": "user"})
        check("demoted user can't", bob.get("/admin").status_code, 403)

        r = owner.post(f"/admin/users/{owner_id}/role", data={"role": "user"})
        check("last admin can't demote themselves", db.get_user(owner_id)["role"], "admin")
        owner.cookies.set("admin_error", r.cookies.get("admin_error") or "", path="/admin")
        check_that("...and is told why", "at least one admin" in owner.get("/admin").text)

        owner.post(f"/admin/users/{bob_id}/disable")
        check("disabled user is signed out", bob.get("/").status_code, 303)
        r = bob.post("/login", data={"username": "bob", "password": helpers.TEST_PASSWORD})
        check_that("...and can't sign in", r.status_code == 400 and "disabled" in r.text)
        owner.post(f"/admin/users/{alice_id}/delete")
        check("deleted user's products are gone", db.get_product(alices), None)

        # Settings: valid values are saved and applied.
        r = owner.post("/admin/settings", data={
            "default_currency": "MYR", "search_domains": ["amazon.sg", "lazada.sg"],
            "refresh_interval_hours": "12", "discover_per_shop": "4", "discover_price_limit": "3"})
        check("settings saved", (site_settings.default_currency(), site_settings.search_domains(),
                                 site_settings.refresh_interval_hours(), site_settings.discover_per_shop(),
                                 site_settings.discover_price_limit()),
              ("MYR", ["amazon.sg", "lazada.sg"], 12.0, 4, 3))
        sections = owner.get("/discover?q=x").text.count('class="card shop-section"')
        check("search now covers only the chosen shops", sections, 2)
        # All or nothing: an invalid value leaves every setting as it was.
        owner.post("/admin/settings", data={
            "default_currency": "USD", "search_domains": ["amazon.sg"],
            "refresh_interval_hours": "0", "discover_per_shop": "4", "discover_price_limit": "3"})
        check("invalid form changes nothing", (site_settings.default_currency(), site_settings.search_domains(),
                                               site_settings.refresh_interval_hours()),
              ("MYR", ["amazon.sg", "lazada.sg"], 12.0))

        # Maintenance.
        owner.post("/admin/maintenance/refresh-all")
        check("refresh-all queued in the background",
              scheduler._scheduler.get_job("refresh-all-now") is not None, True)
        scheduler._scheduler.remove_all_jobs()
        saved_fetch = admin_routes.fx._fetch_rates
        try:
            admin_routes.fx._fetch_rates = lambda: {"USD": 1.0, "SGD": 1.3}
            r = owner.post("/admin/maintenance/fx")
            check("FX fetched: says refreshed", r.headers["location"], "/admin?notice=fx")
            admin_routes.fx._fetch_rates = lambda: None  # both services down, cache present
            r = owner.post("/admin/maintenance/fx")
            check("FX failed with a cache: doesn't claim success", r.headers["location"],
                  "/admin?notice=fx_failed_cached")
            check_that("...and says so", "Still using the cached rates" in owner.get(r.headers["location"]).text)
            conn = db.get_connection()
            conn.execute("DELETE FROM fx_rates")
            conn.commit()
            conn.close()
            r = owner.post("/admin/maintenance/fx")
            check("FX failed, nothing cached", r.headers["location"], "/admin?notice=fx_failed_none")
        finally:
            admin_routes.fx._fetch_rates = saved_fetch

        owner.post("/admin/maintenance/history", data={"action": "pause"})
        check("archive lookups paused", site_settings.history_paused(), True)
        main.history.schedule_backfill = saved_backfill  # real one: must honour the pause
        pid = _track(owner, "Paused check")
        check("tracking while paused schedules nothing",
              scheduler._scheduler.get_job(f"history-{pid}"), None)
        check_that("product page says paused", "paused by an admin" in owner.get(f"/product/{pid}").text)
        owner.post("/admin/maintenance/history", data={"action": "resume"})
        check("resumed", site_settings.history_paused(), False)
    finally:
        restore()
        scheduler._scheduler.remove_all_jobs()


from app import history as _history_module
saved_backfill = _history_module.schedule_backfill


# --- fixes from the code review (2026-09-24) --------------------------------------------

def test_review_as_quoted_beats_site_default():
    section("Review #1: 'As quoted' is a real choice, even with a site default")
    from app import main
    fresh_db()
    db.save_fx_rates("USD", {"USD": 1.0, "SGD": 1.28, "MYR": 4.09})
    site_settings.save_default_currency("SGD")
    alice = helpers.client("alice")
    alice_row = lambda: db.get_user_by_name("alice")
    check("no choice yet: site default", main.display_currency(alice_row()), "SGD")
    alice.post("/settings/currency", data={"currency": ""})
    check("chose 'As quoted': stays as quoted", main.display_currency(alice_row()), None)
    check_that("...and the picker shows it (no currency preselected)",
               ' selected>' not in alice.get("/").text.split('name="currency"')[1].split("</select>")[0])
    alice.post("/settings/currency", data={"currency": "XYZ"})
    check("unknown code ignored, choice kept", main.display_currency(alice_row()), None)


def test_review_settings_never_freeze_config():
    section("Review #2-4: a save only stores what changed; a failed save stores nothing")
    import os
    from app.search import providers
    fresh_db()
    owner = helpers.client("owner")
    os.environ["DISCOVER_PER_SHOP"] = "10"
    try:
        form = {"default_currency": "", "search_domains": site_settings.available_shops(),
                "refresh_interval_hours": "0", "discover_per_shop": "10", "discover_price_limit": "6"}
        owner.post("/admin/settings", data=form)
        stored = {k: db.get_setting(k) for k in ("discover_per_shop", "refresh_interval_hours",
                                                 "search_domains_off", "display_currency")}
        check("failed save writes nothing at all", stored, dict.fromkeys(stored))
        os.environ["DISCOVER_PER_SHOP"] = "12"
        check("...so the env var still applies", site_settings.discover_per_shop(), 12)

        form["refresh_interval_hours"] = "8"      # the only real change
        form["discover_per_shop"] = "12"          # same as env: untouched
        owner.post("/admin/settings", data=form)
        check("valid save stores only the change",
              (db.get_setting("refresh_interval_hours"), db.get_setting("discover_per_shop"),
               db.get_setting("search_domains_off")), ("8", None, None))
    finally:
        del os.environ["DISCOVER_PER_SHOP"]

    form["search_domains"] = ["amazon.sg", "lazada.sg"]
    owner.post("/admin/settings", data=form)
    check("shops are stored as the ones switched off",
          sorted(db.get_setting("search_domains_off").split(",")), ["ebay.com.sg", "qoo10.sg", "shopee.sg"])
    providers.DEFAULT_SEARCH_DOMAINS.append("newshop.sg")
    try:
        check("a shop added to the code later is searched without an admin",
              "newshop.sg" in site_settings.search_domains(), True)
    finally:
        providers.DEFAULT_SEARCH_DOMAINS.remove("newshop.sg")

    before = site_settings.search_domains()
    owner.post("/admin/settings", data={**form, "search_domains": ["amazon.sg,evil.example"]})
    check("injected domain refused, nothing changed", site_settings.search_domains(), before)


def test_review_admin_numbers_render_exactly():
    section("Review #5: the admin form shows numbers exactly")
    fresh_db()
    owner = helpers.client("owner")
    for stored, shown in (("1.05", "1.05"), ("6", "6"), ("12.5", "12.5")):
        db.set_setting("refresh_interval_hours", stored)
        html = owner.get("/admin").text
        check_that(f"stored {stored} is shown as {shown}",
                   f'name="refresh_interval_hours" value="{shown}"' in html)
    check_that("any interval step allowed (no browser block)", 'step="any"' in html)


def test_review_ignored_env_is_reported():
    section("Review #9: an unusable env value is reported, not silently dropped")
    import os
    fresh_db()
    owner = helpers.client("owner")
    os.environ["REFRESH_INTERVAL_HOURS"] = "0.5"
    try:
        check("falls back to the default", site_settings.refresh_interval_hours(), 6)
        check_that("listed as ignored", any("REFRESH_INTERVAL_HOURS='0.5' is ignored" in p
                                            for p in site_settings.ignored_env()))
        check_that("shown on the admin page", "is ignored" in owner.get("/admin").text)
    finally:
        del os.environ["REFRESH_INTERVAL_HOURS"]


def test_review_parallel_guessing_is_capped():
    section("Review #10: parallel guesses can't get past the lock")
    import threading
    import time as _time
    fresh_db()
    auth.register("owner", "correct-horse")
    checked = []
    saved_verify = auth.verify_password

    def slow_verify(password, encoded):
        checked.append(1)
        _time.sleep(0.05)  # the window the old code raced in
        return False

    auth.verify_password = slow_verify
    try:
        threads = [threading.Thread(target=lambda: _swallow(auth.authenticate, "owner", "guess"))
                   for _ in range(40)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        auth.verify_password = saved_verify
        auth._failures.clear()
    check("40 parallel guesses: at most 5 were checked", len(checked) <= auth.LOCK_AFTER_FAILURES, True)


def _swallow(fn, *args):
    try:
        fn(*args)
    except Exception:
        pass


def test_review_admins_cannot_both_demote():
    section("Review #11: two admins demoting each other still leaves one")
    import threading
    for _ in range(10):
        fresh_db()
        a = auth.register("owner", "correct-horse")
        b = auth.register("bob", "correct-horse")
        auth.change_role(b["id"], "admin")
        barrier = threading.Barrier(2)

        def demote(uid):
            barrier.wait()
            _swallow(auth.change_role, uid, "user")

        threads = [threading.Thread(target=demote, args=(uid,)) for uid in (a["id"], b["id"])]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if db.count_enabled_admins() < 1:
            break
    check("an enabled admin always remains (10 races)", db.count_enabled_admins(), 1)


def test_review_refreshes_take_turns():
    section("Review #12-13: batch refreshes never overlap; a deleted listing doesn't stop a batch")
    import threading
    import time as _time
    from app import refresh, scheduler
    fresh_db()
    user = auth.register("owner", "correct-horse")
    pids = [db.add_product(f"P{i}", None, user_id=user["id"]) for i in range(3)]
    for pid in pids:
        db.add_source(pid, f"https://www.amazon.sg/dp/B0TEST000{pid}", None)

    active, peak = [0], [0]
    lock = threading.Lock()
    saved = (refresh.refresh_source, refresh.DELAY_BETWEEN_REQUESTS)

    def tracked_refresh(source_id):
        with lock:
            active[0] += 1
            peak[0] = max(peak[0], active[0])
        _time.sleep(0.03)
        with lock:
            active[0] -= 1

    refresh.refresh_source, refresh.DELAY_BETWEEN_REQUESTS = tracked_refresh, 0
    try:
        threads = [threading.Thread(target=refresh.refresh_all),
                   threading.Thread(target=refresh.refresh_products, args=(pids,))]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
    finally:
        refresh.refresh_source, refresh.DELAY_BETWEEN_REQUESTS = saved
    check("scheduled and 'my prices' refresh never run side by side", peak[0], 1)

    scheduler._scheduler.add_job(refresh.refresh_all, "interval", hours=6, id=scheduler.REFRESH_JOB_ID)
    try:
        scheduler.refresh_all_now()
        check("admin 'refresh now' reuses the scheduled job (no parallel copy)",
              [j.id for j in scheduler._scheduler.get_jobs()], [scheduler.REFRESH_JOB_ID])
    finally:
        scheduler._scheduler.remove_all_jobs()

    # A listing deleted while its price is being fetched.
    from app.scraper import PriceResult
    victim = db.get_sources(pids[0])[0]["id"]
    survivor = db.get_sources(pids[1])[0]["id"]
    saved_fetch = refresh.fetch_price

    def fetch_then_delete(url, selector=None):
        if url.endswith(f"000{pids[0]}"):
            db.delete_source(victim)
        return PriceResult(price=100.0, currency="SGD", strategy="stub")

    refresh.fetch_price, refresh.DELAY_BETWEEN_REQUESTS = fetch_then_delete, 0
    try:
        refresh.refresh_products(pids[:2])
    finally:
        refresh.fetch_price, refresh.DELAY_BETWEEN_REQUESTS = saved_fetch, saved[1]
    check("deleted mid-fetch: batch carried on to the next listing",
          [s["price"] for s in db.get_snapshots(survivor)], [100.0])


TESTS = [
    test_storage,
    test_passwords,
    test_sessions,
    test_sign_in_and_throttle,
    test_access_helpers,
    test_last_admin_guard,
    test_site_settings,
    test_settings_apply_without_restart,
    test_account_routes,
    test_same_site_guard,
    test_products_are_private,
    test_public_search,
    test_currency_is_personal,
    test_admin_page,
    test_review_as_quoted_beats_site_default,
    test_review_settings_never_freeze_config,
    test_review_admin_numbers_render_exactly,
    test_review_ignored_env_is_reported,
    test_review_parallel_guessing_is_capped,
    test_review_admins_cannot_both_demote,
    test_review_refreshes_take_turns,
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
    print("All auth tests passed.")
