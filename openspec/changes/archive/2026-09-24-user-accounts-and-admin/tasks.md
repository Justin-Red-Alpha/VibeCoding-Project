# Tasks

## 1. Data

- [x] 1.1 Add `users` and `sessions` tables to `SCHEMA` and `products.user_id` (nullable, `REFERENCES users(id) ON DELETE CASCADE`) via `_add_missing_columns`, plus DB helpers (`create_user` atomic first-admin + claim, `get_user_by_name/id`, `list_users` with product counts, `set_role`, `set_disabled`, `delete_user`, sessions CRUD, `get_products_for_user`, `set_user_currency`). Verify in new `tests/test_auth.py` (temp DB) that an old DB gains the column with products intact and unowned, the first user is admin and claims them, the second is a user, and deleting a user cascades to their products and sessions

## 2. Auth core

- [x] 2.1 `app/auth.py`: `hash_password` / `verify_password` (scrypt, encoded params, `hmac.compare_digest`), username/password validation. Verify tests: round trip, wrong password, tampered hash, a hash string with no plain text in it, and the length and character rules
- [x] 2.2 Sessions: `start_session` (a token hashed at rest, 14 days), `user_for_token` (expired, disabled or unknown gives None), `end_session`, `end_all_sessions(user)`. Verify tests: an expired session is rejected, disabling ends sessions, and the DB holds no raw token
- [x] 2.3 Throttle + dummy hash: 5 failures in 15 min locks the username, success resets it, and an unknown username still runs a verify. Verify with an injected clock
- [x] 2.4 Dependencies: `current_user`, `require_user` (→ `LoginRequired` → 303 `/login?next=`), `require_admin` (403), `product_for` / `source_for` (owner or admin, else 404), `local_path`. Verify tests: `local_path` rejects `https://evil.example`, `//evil`, `/\evil` and `javascript:`; ownership gives 404 for another user's id and 200 for an admin

## 3. Site settings

- [x] 3.1 `app/site_settings.py`: typed getters (DB > env > default) and validated setters for default currency, search domains (known adapters only), refresh interval (1–168 h), per-shop limit (1–20), price-lookup limit (0–20) and history pause. Verify tests: env fallback, invalid values refused with the old value kept, unknown domain refused
- [x] 3.2 Wire the getters in at use time: `providers.search_domains`, the discover limits in `main`, `scheduler.start_scheduler` + `set_refresh_interval` (reschedule), and `history.schedule_backfill` honouring the pause. Verify tests: changing search domains changes `search_domains()` with no restart; a paused history schedules nothing; `set_refresh_interval` reschedules the job (scheduler not started: job trigger interval updated)

## 4. Account routes and pages

- [x] 4.1 `app/account.py` + `login.html` / `register.html`: GET/POST `/register` (first-run banner "the first account becomes admin"), GET/POST `/login?next=`, POST `/logout`, POST `/settings/currency` (per-user, `local_path` redirect). Verify TestClient tests: registration flow sets the cookie flags (HttpOnly, SameSite=Lax), duplicate or short password shows the error, the wrong-password message is identical for an unknown user, logout ends the session, and `next` is honoured only when local
- [x] 4.2 The same-site POST middleware. Verify: a POST with `Origin: https://evil.example` gets 403 and nothing changes; same-origin passes; no Origin passes

## 5. Access control in existing routes

- [x] 5.1 Dashboard, product page, track, add product/source, delete, refresh-one, history-lookup: require login, scope by owner via `product_for` / `source_for`, and stamp `user_id` on create. The topbar "Refresh All Now" refreshes the current user's products only. Verify tests: A can't see, change or delete B's product (404); an admin can open it; the dashboard lists only one's own products
- [x] 5.2 Discovery stays public: `/discover` + stream work anonymously using the site default currency; the track section shows "Sign in to track" for anonymous visitors; POST `/discover/track` requires login. Verify tests: anonymous GET 200, stream events arrive (search stubbed), anonymous track gives a redirect to login and creates nothing
- [x] 5.3 Per-user display currency via the context processor and `display_currency(user)`; the topbar shows the username, sign-out and (admins) an Admin link. Verify tests: two users with different currencies see different conversions; anonymous sees the site default

## 6. Admin page

- [x] 6.1 `app/admin.py` + `admin.html`: the users table (role, status, created, product count) with promote, demote, disable, enable and delete (with a confirm); the last-admin guard in `auth`. Verify tests: a user gets 403 on GET and on every POST; promote/demote changes admin access; the last admin can't be demoted, disabled or deleted; delete cascades
- [x] 6.2 The site-settings form (validated, flash messages). Verify tests: valid changes persist and apply (the search domain change is reflected on `/discover`); invalid values show an error and change nothing
- [x] 6.3 Maintenance: refresh all users' prices, refresh FX (forced), pause/resume archive lookups. Verify tests with `refresh_all` / `fx.refresh_rates` stubbed: each is called; pause makes tracking schedule nothing and the product page says "paused"

## 7. Existing tests and verification

- [x] 7.1 Add a `login(client)` helper and update the route tests in `test_currency`, `test_shop_search` and `test_history` to sign in; run all six suites with `PYTHONIOENCODING=utf-8`; verify all pass — the helper is `tests/helpers.py:client` (registers/signs in `owner`, the first account = admin)
- [x] 7.2 Restart the server; register the owner account in the browser (first = admin) and confirm the existing product moved to it; register a second user in a private window, check isolation and admin 403, and check the admin page actions. Take screenshots at 390 px and 1100 px for the login and admin pages — done on an isolated copy (:8001, temp DB) so the real first-admin slot stays free for the owner: registration → admin; a user gets 403 on /admin and 404 on another user's product; admin sees "Tracked by alice"; promote/demote works; pause shown on the product page. Real server :8000 checked read-only (Log in / Register visible; `/` → login with a "register first" banner); real DB still 0 users. Top bar tightened after the screenshots (one line at 1100 px)

## 8. Reconcile

- [x] 8.1 Docs: new `docs/auth/` and `docs/settings/` components; web, storage, refresh, history and discovery rows; architecture map (User, Session, the cookie `Trm`, the new coherence note); roll-ups; `README.md` (first run: register first; roles; admin page) and `CLAUDE.md` (auth replaces "no auth"; invariant: ownership via `product_for`; the CSRF stance)
- [x] 8.2 Run the supercharge drift check; fix dead rows; record the result — first run found 5 dead rows (the moved `set_display_currency`, the renamed `refresh_everything`, the removed `REFRESH_INTERVAL_HOURS` constant and `current_display_currency` global); fixed. Final: `0 dead / 390 refs`
