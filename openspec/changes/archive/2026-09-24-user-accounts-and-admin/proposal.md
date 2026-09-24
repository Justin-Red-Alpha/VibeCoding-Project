# Proposal

## Why

The app is a single-user localhost tool with no accounts. Anyone who can reach it
can see and change every tracked product and every setting. The user wants people
to register and log in, with two roles: **user** (the default) and **admin**, who
gets an extra page to adjust the site. Several settings that belong on that page
are fixed in code or environment variables today: the default currency, the shops
searched, the refresh interval and the discovery limits.

The user's decisions (2026-09-24):
- **Per-user products.** Each user sees only what they track; admins can open
  anyone's.
- **Admin page:** manage users, site settings, maintenance actions.
- **First sign-up becomes admin;** open registration after that.
- **Search is public.** Tracking, dashboards, product pages and admin need login.
- The archived-price-history follow-ups are **on hold**. The shipped feature stays
  as it is, and admins can pause its automatic lookups.

## What Changes

- **Accounts:**
  - register (username + password), log in, log out;
  - the **first account becomes admin**, and every later one is a **user**;
  - passwords are hashed with salted scrypt (Python standard library, no new
    dependency);
  - sessions are random tokens in an HttpOnly, SameSite=Lax cookie, stored hashed
    in SQLite, and expire after 14 days;
  - repeated failed logins lock the username for 15 minutes.
- **Per-user data:**
  - products belong to the user who tracked them, and users see and change only
    their own;
  - an admin can open any product;
  - existing products are given to the first admin when they register;
  - "Show prices in" becomes a **personal preference**. Anonymous visitors see the
    site default.
- **Access rules:**
  - Deal search (`/discover` and its stream) is public.
  - The dashboard, product pages, tracking, adding shops and refresh require login.
  - The admin page requires the admin role.
  - Anonymous visitors are sent to login and then back where they were, with
    local redirects only.
- **Admin page** (`/admin`):
  - **users:** list, promote or demote, disable or enable, delete. The last active
    admin is protected.
  - **site settings:** default display currency, shops searched, refresh interval,
    discovery limits. They take effect without a restart, and the environment
    variables become fallbacks.
  - **maintenance:** refresh every user's prices now, refresh FX rates now, pause
    or resume automatic archive lookups.
- **Hardening that comes with cookies:**
  - cross-site form posts are rejected (an Origin check);
  - the existing open redirect in `POST /settings/currency` (`next_url`) is fixed.
- **BREAKING (local):** pages that were open now need an account. The first
  person to register becomes admin, so the owner should register first.

## Capabilities

### New Capabilities
- `user-accounts`: registering, logging in and out, roles, the first admin, failed-login lockout, disabled accounts.
- `access-control`: what anonymous visitors, users and admins can see and do; per-user products and preferences; safe redirects and same-site form posts.
- `site-administration`: the admin page (user management, site settings, maintenance actions).

### Modified Capabilities
- none. `shop-search` still holds unchanged, since search stays public.
  `price-history-backfill` gains a pause switch, which is additive: when paused,
  no lookup is scheduled.

## Impact

- **Schema** (all additive):
  - new tables `users` and `sessions`;
  - `products.user_id` (nullable; NULL = unowned, claimed by the first admin);
  - new keys in `settings`.
- **Code:**
  - new: `app/auth.py` (hashing, sessions, throttle, user dependencies),
    `app/site_settings.py` (effective settings: DB > env > default),
    `app/account.py` (login, register, logout, preferences) and `app/admin.py`
    (admin page routes);
  - changed: `app/main.py` (per-user queries, ownership checks, user-aware
    currency, Origin middleware, local-only redirects), `app/database.py`,
    `app/scheduler.py` (reschedule on change), `app/search/providers.py` (search
    domains from settings) and `app/history.py` (pause switch);
  - templates: new login/register/admin pages; the topbar shows the account and
    admin link.
- **Tests:**
  - new `tests/test_auth.py`;
  - existing route tests in `test_currency`, `test_shop_search` and
    `test_history` log in first.
- **Docs:** new `docs/auth/` and `docs/settings/` components; the web, storage
  and refresh maps; the roll-ups; `README.md` (first-run: register first) and
  `CLAUDE.md` (no longer "no auth").
- **No new dependencies.**
