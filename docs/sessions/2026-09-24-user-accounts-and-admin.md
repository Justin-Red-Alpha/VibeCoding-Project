# 2026-09-24 — user accounts and admin

## 0. Continuation brief

Current state: **accounts, roles and an admin page are built, verified and
archived**. OpenSpec `2026-09-24-user-accounts-and-admin`, 19/19.

- People register and sign in. The first account is the **admin**; everyone
  after that is a **user**.
- Products are per user.
- Deal search stays public.
- Admins get `/admin`: users, site settings, maintenance.
- The archived-price-history follow-ups are **on hold** (user's decision). The
  shipped feature stays, and admins can pause its lookups.
- 451 offline checks pass. The drift check is `0 dead / 390 refs`.

**The owner has not registered yet.** The real `data/app.db` has 0 users, and 1
product is waiting to be claimed by the first admin.

Next step: the owner registers at `http://127.0.0.1:8000/register`. It must be
the owner, because the first account becomes admin and claims existing products.

Resume command/check: `python -m tests.test_auth` (142 OK), then
`.venv\Scripts\python.exe -c "import sqlite3;print(sqlite3.connect('data/app.db').execute('select username, role from users').fetchall())"`.

---

## 1. Work completed

- **New modules:**
  - `app/auth.py`: scrypt hashing, sessions (only a SHA-256 of the token is
    stored), throttle, `require_user` / `require_admin`, `product_for` /
    `source_for`, `local_path`, and admin actions with the last-admin guard
  - `app/site_settings.py`: DB > env > default, validated
  - `app/templating.py`: shared Jinja setup; `user` and `display_pref` on every
    page
  - `app/account.py`: register, login, logout, personal currency
  - `app/admin.py`: the users, settings and maintenance routes
- **Changed:**
  - `database.py`: `users` and `sessions` tables; `products.user_id`; an atomic
    first-admin `create_user`
  - `main.py`: every product route goes through ownership checks; dashboard
    per user; `SameSitePostGuard`; `LoginRequired` redirects to login; the
    discover limits come from settings; `/refresh` refreshes only your own
    products
  - `scheduler.py`: interval from settings; `set_refresh_interval`
  - `providers.search_domains` now delegates to settings
  - `history.schedule_backfill` honours the pause
  - templates: login, register and admin pages; the top bar; discover asks
    anonymous visitors to sign in to track
- **Tests:**
  - new `tests/test_auth.py` (142 checks) and `tests/helpers.py` (temp DB plus a
    signed-in TestClient)
  - `test_currency` and `test_history` now sign in
- **Docs:**
  - new `docs/auth/` and `docs/settings/` components;
  - the storage, web and refresh maps, the architecture map and the roll-ups;
  - README (first run: register first; roles; admin page) and CLAUDE.md
    (invariants 10 and 11, the auth stance, the data model).

## 2. Decisions

| Decision | Verdict | Why |
| --- | --- | --- |
| Per-user products (user) | **kept** | Admins can open any product by link; they have no all-products overview |
| Admin page scope (user) | **users, settings, maintenance** | "All tracked products" not chosen |
| First sign-up becomes admin (user) | **kept** | Atomic `BEGIN IMMEDIATE`; claims unowned products |
| Search stays public (user) | **kept** | Tracking and everything else need sign-in |
| An admins table | discarded | §3: an admin is a `User` with `role`, not a separate object |
| bcrypt / argon2 / passlib | discarded | A new dependency; stdlib `hashlib.scrypt` is enough |
| Signed-cookie sessions / JWT | discarded | Can't be revoked server-side. Opaque tokens, hashed at rest |
| Per-form CSRF tokens | deferred | SameSite=Lax plus an Origin/Referer guard for localhost. Recorded for exposure |
| `@app.middleware` for the guard | discarded | Pure ASGI, so the SSE stream is never buffered |
| Register the owner during live verification | **refused** | It would have taken the admin slot and the owner's product. Verified on an isolated copy (:8001, temp DB) |
| "Refresh my prices" in the top bar | moved to *My products* | The top bar wrapped to two lines at 1100 px |

## 3. Tests, checks

| Check | Result |
| --- | --- |
| 6 suites | 63 + 48 + 89 + 32 + 77 + **142** = **451 OK** |
| Browser, isolated copy | register gives admin; user gets 403 on `/admin` and 404 on another user's product; admin sees "Tracked by alice"; promote and demote work; pause is shown |
| Browser, real :8000 (read-only) | Log in and Register visible; `/` redirects to login with a "register first" banner; DB still 0 users |
| Drift | 5 dead rows (moved or renamed symbols) fixed, then `0 dead / 390 refs` |

## 4. Live handoff state

| Type | Handle | State | Inspect | Stop |
| --- | --- | --- | --- | --- |
| process | uvicorn `--reload` :8000 | running, new code | `Get-NetTCPConnection -LocalPort 8000 -State Listen` | stop uvicorn **and** its multiprocessing child (CLAUDE.md trap) |
| data | `data/app.db` | migrated (users, sessions, `products.user_id`); **0 users**; 1 unowned product | query above | — |
| incident | the session timed out mid-apply | **all code from the first attempt was rolled back** (only the OpenSpec folder survived). Re-applied from context; the same tests pass | — | a WIP backup was kept in the scratchpad (`wip/`) afterwards |
| external | web.archive.org block from ~14:00 | likely lifted; don't probe in a loop | one request after 1 h+ | — |

## 5. In-flight changes

None. Archived: `2026-09-24-user-accounts-and-admin` → specs `user-accounts`,
`access-control`, `site-administration`.

## 6. Open items

| Priority | Item | Next action | Done when |
| --- | --- | --- | --- |
| P1 | Owner hasn't registered | The owner registers first at `/register` | `users` has the owner as admin, and the product is claimed |
| P2 | No password change / reset | A "change password" form for signed-in users | Tested form |
| P2 | CSRF tokens / HTTPS before any exposure beyond localhost | See `docs/auth/STATUS.md` | — |
| on hold | Archived-history follow-ups (USD 88 check, BuyWhere) | Resume when the user says so | — |
| P3 | Carried items | `docs/STATUS.md`, `docs/suggestions.md` | — |

## 7. Architecture / model changes

- **New components** `auth` and `settings`.
- **Dat:** `User` (with a `role` discriminator), `Session`, and
  `Product.owner?`.
- **Trm:** `t_cookie : UserBrowser → ServerProc`.
- **New invariants 10 and 11:**
  - every product or source route goes through `product_for` / `source_for`;
  - the first account is the admin, so nothing may register on the real DB in
    tests.
- **Coherence:** unchanged, with no failures. Law 2 is still advisory for SSE.

## 8. Docs reconciled

- `docs/auth/*` and `docs/settings/*` (new)
- `docs/{storage,web,refresh}/IMPLEMENTATION.md`
- `docs/architecture-map.md`, `docs/IMPLEMENTATION.md`, `docs/STATUS.md`
- `README.md`, `CLAUDE.md`, `openspec/config.yaml`

## 9. Drift check

`0 dead / 390 refs`.

## 10. Files changed

This commit contains the code, tests, docs, OpenSpec archive and specs listed
above, and this log.
