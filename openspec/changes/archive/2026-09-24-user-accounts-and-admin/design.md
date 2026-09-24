# Design

## Context

See `proposal.md` for the motivation and the user's four decisions. What exists
today:

- **No identity anywhere.** 13 routes in `app/main.py`, all open. The dashboard
  lists every product. `CLAUDE.md` says "No auth… localhost-only personal tool".
- **One global preference.** `settings.display_currency` is read by
  `main.display_currency()` and a template global. The topbar picker writes it for
  everyone.
- **Settings in env/code:** `DISCOVER_PRICE_LIMIT` and `DISCOVER_PER_SHOP`
  (`main.py`, read at import), `REFRESH_INTERVAL_HOURS` (`scheduler.py`, read at
  import) and `SEARCH_DOMAINS` (`providers.search_domains`).
- **An existing open redirect.** `POST /settings/currency` redirects to any
  `next_url`.
- **Available without new dependencies:** `hashlib.scrypt`, `secrets`, `hmac`.
  Starlette 0.38.6's `Jinja2Templates` supports `context_processors`, so every
  page can get `user` without editing each route. Not installed:
  `itsdangerous`, `passlib`, `bcrypt`, `argon2`.

### Model delta (FRAMEWORK terms)

**§3 check: is "admin" a new object?** Write out an admin's morphisms: username,
password hash, created_at, preferences, owned products, plus the admin
capabilities. That's a `User` with extra *capabilities*, not extra data. So it's
one object with a `role` discriminator. Don't create an admins table.

**§3 check: is "session" part of `User`?** No. A user has many sessions, each
with its own expiry, so it's a genuine one-to-many relation. `Session` is its own
object.

| Kind | Item | Signature | Partiality | Semantics |
| --- | --- | --- | --- | --- |
| `Dat` | `User` | `{id, username, password_hash, role, display_currency?, disabled_at?, created_at}` | — | `role ∈ {user, admin}` is the discriminator |
| `Dat` | `Session` | `{token_hash, user → User, created_at, expires_at}` | — | the raw token lives only in the browser cookie; the DB keeps `sha256(token)` |
| `Dat` | `owner?` | `Product → User` | Partial | NULL = unowned (from before accounts). Claimed by the first admin |
| `Dat` | `display_currency?` | `User → Currency` | Partial | a personal preference. NULL = the site default |
| `Dat` | site settings | `settings[key] → value` | Partial | adds `search_domains`, `refresh_interval_hours`, `discover_per_shop`, `discover_price_limit`, `history_paused`. The existing `display_currency` key becomes the **site default** |
| `Trn` | `hash_password` / `verify_password` | `𝕊 → Hash`, `𝕊 × Hash → 𝔹` | Total | scrypt n=2¹⁴ r=8 p=1, 16-byte salt, constant-time compare |
| `Trn` | `register` | `Username × Password → User` ⊸ | Partial | admin iff there are no users. Claims unowned products |
| `Trn` | `login?` | `Username × Password → Session` ⊸ | Partial | undefined when wrong, disabled or throttled; one message for all |
| `Trn` | `current_user?` | `Cookie → User` | Partial | valid, unexpired session of an enabled user |
| `Trn` | `authorize_product?` | `User × ProductId → Product` | Partial | owner, or any admin. Otherwise 404 |
| `Trn` | `effective(key)` | `() → value` | Total | DB value if set and valid, else env, else code default |
| `Trn` | `local_path` | `𝕊 → Path` | Total | the `next` target if it's a same-site path, else `/` |

## Goals / Non-Goals

**Goals:** accounts and roles as specified, per-user isolation, an admin page for
the chosen three areas, and no new dependencies.

**Non-Goals:**
- **Email** (verification, password reset). There's no mail server; an admin can
  delete and a user can re-register. Password change for a signed-in user is also
  out, as a follow-up.
- **An all-products overview for admins** (not chosen). Admins can open any
  product by link, and the user list shows counts.
- **Synchroniser CSRF tokens in every form.** SameSite=Lax plus an Origin check
  covers browsers for a localhost tool. Revisit if the app is exposed beyond
  localhost.
- **Persistent login throttling.** It's in memory and resets on restart.

## Decisions

1. **Salted scrypt from the standard library.** Stored as
   `scrypt$16384$8$1$<salt b64>$<hash b64>`, so the parameters can be raised later
   without breaking old hashes.
   *Discarded:* bcrypt or argon2 (a new dependency for no real gain here), and
   PBKDF2 (weaker against GPU attacks at practical iteration counts).
2. **Opaque server-side sessions.** A 32-byte `secrets.token_urlsafe` goes in
   cookie `session` (HttpOnly, SameSite=Lax, Path=/, Secure when the request is
   https, max-age 14 days). The DB stores only its SHA-256, so a leaked database
   yields no usable sessions. Logout, disable and delete remove rows.
   *Discarded:* signed-cookie sessions (need `itsdangerous`, can't be revoked
   server-side) and JWTs (same revocation problem).
3. **Role is a discriminator** (the §3 check above). Authorization is a function
   of `role`, and there's no parallel admin object.
4. **First-admin registration is atomic.** Inside `BEGIN IMMEDIATE`: count users;
   role = admin if zero; insert; `UPDATE products SET user_id = ? WHERE user_id IS
   NULL`. Two simultaneous first sign-ups can't both become admin.
5. **One ownership check for every product and source route:**
   `auth.product_for(user, product_id)` (and `source_for`). It returns the row if
   `owner = user` or `user` is an admin, and otherwise raises 404, the same as a
   missing id, so it can't be used to probe which ids exist. The dashboard,
   refresh-mine and tracking all filter or stamp by `user_id`.
6. **Dependencies and redirects.** `current_user` is an optional dependency;
   `require_user` raises `LoginRequired(next)`, which is handled as a 303 to
   `/login?next=<local path>`; `require_admin` raises 403. `local_path()`
   accepts only paths that start with `/` and not `//` or `/\`. That's used for
   sign-in and for the currency preference, and it fixes the existing open
   redirect.
7. **Same-site POST guard.** A small middleware checks state-changing methods. If
   `Origin` (or else `Referer`) is present and its host differs from the request's
   host, it returns 403. A request with neither header (curl, TestClient) passes,
   since browsers always send one on cross-site posts. SameSite=Lax is the primary
   guard; this is defence in depth.
8. **Throttle.** An in-memory map from lower-cased username to recent failure
   times. With 5 or more in 15 minutes, sign-in is refused until the oldest ages
   out. It resets on success. An unknown username still runs one scrypt against a
   fixed dummy hash, so response time doesn't reveal whether the account exists.
9. **Effective settings in one module.** `site_settings.py` has typed getters and
   validated setters. The getters are read **at use time** (per search, per
   refresh), so changes apply without a restart. The refresh interval also calls
   `scheduler.set_refresh_interval(h)`, which reschedules the live job. Search
   domains are limited to the adapters' known search domains, so an admin can't
   point discovery at an arbitrary site.
10. **Currency preference.** `main.display_currency(user)` returns the user's
    preference, else the site default, and only if FX rates are available. The
    stream gets the user through the same cookie dependency (EventSource sends
    cookies on same-origin requests). The topbar picker appears for signed-in
    users only.
11. **Routers.** `app/account.py` has `/login`, `/register`, `/logout` and
    `/settings/currency`. `app/admin.py` has `/admin` and its POST actions.
    `main.py` keeps the product and discovery routes. A template
    `context_processor` adds `user` and `display_currency` to every page.
12. **Deleting a user cascades** to their products (FK `ON DELETE CASCADE` on
    `products.user_id`) and their sessions. The admin UI confirms first. The last
    enabled admin can't be demoted, disabled or deleted, which is checked in
    `auth` so every path enforces it.
13. **History pause** is `site_settings.history_paused()`. When it's on,
    `history.schedule_backfill` returns without scheduling, and the product page
    note says "paused by an admin".

**Coherence laws to keep:**
- **Law 1.** Authorization runs where the session row is: the request thread
  reads `sessions`/`users` over `t_sql`. The browser holds only the raw token.
- **Law 2.** The cookie is a typed `Trm` (`token : UserBrowser → ServerProc`).
  The session exists in two `DataLoc`s in *deliberately different forms* (raw in
  the browser, hashed at rest).
- **Law 4.** No new cross-location reach. The admin page's actions call the same
  `Trn`s over the same channels (refresh, fx, scheduler).

## Risks / Trade-offs

- **The existing tests use open routes.** → A `login(client)` test helper
  registers the first user (admin) and keeps the cookie. The route tests in
  `test_currency`, `test_shop_search` and `test_history` use it (tasks 6.x).
- **Someone can lock an admin's username** by failing 5 times. → It lasts 15
  minutes and is in memory. Acceptable for localhost; documented.
- **The owner forgets to register first,** so someone else becomes admin.
  → README and the first-run banner say "register first". The admin can promote
  or delete accounts later.
- **SameSite=Lax + Origin isn't full CSRF protection** for very old browsers.
  → A non-goal for localhost, recorded in `CLAUDE.md` for anyone exposing the app.

## Migration Plan

- Create `users` and `sessions` in `SCHEMA`, and add `products.user_id` in
  `_add_missing_columns` (`ADD COLUMN … REFERENCES users(id) ON DELETE CASCADE`,
  nullable, no rebuild).
- Existing products stay unowned until the first admin registers, then become
  theirs.
- To roll back, revert the code. The extra tables and column are ignored.
