# Tasks

## 1. Setup and the image spike

- [x] 1.1 Start a local Postgres 17 for development: `docker run -d --name pt-pg -p 5433:5432 -e POSTGRES_PASSWORD=postgres -e POSTGRES_DB=test postgres:17` (needs Docker Desktop running). Install `psycopg[binary]` and `psycopg-pool` into the venv. Verify: `python -c "import psycopg; psycopg.connect('postgresql://postgres:postgres@localhost:5433/test').execute('select 1')"` succeeds.
- [x] 1.2 Build a draft `Dockerfile.vercel` (python:3.14-slim-bookworm + playwright + Chromium, non-root). Verify: `docker build` succeeds locally; `docker image ls` size recorded in design.md; `docker run … python -m tests.test_shop_search` passes inside the image.

## 2. Storage port (Postgres adapter)

- [x] 2.1 Add `Backend` selection, the `DatabaseUnavailable` / `IntegrityError` types and the `Row` type to `app/database.py`. `get_connection()` picks sqlite (default, `DB_PATH`) or postgres (`DATABASE_URL`). The Postgres side is a small `Conn` wrapper over a lazily opened `psycopg_pool.ConnectionPool` (`max_size=4`, checked on checkout). It rewrites `?` to `%s`, `close()` returns the connection to the pool, and `with conn:` commits or rolls back. Verify: all six suites still pass with no env set, and a unit test shows `Row` supports `row["x"]`, `row[0]`, `.keys()` and `dict(row)`.
- [x] 2.2 Make the schema one text with `{pk}` and `{username}` tokens, and change `REAL` to `DOUBLE PRECISION`. On Postgres, `init_db` runs `CREATE EXTENSION IF NOT EXISTS citext` and the schema inside one transaction under `pg_advisory_xact_lock(SCHEMA_LOCK)`, and skips the SQLite-only v1→v2 migration and `_add_missing_columns`. Verify:
  - an existing local `data/app.db` copy still opens unchanged;
  - two threads running `init_db` at once on a fresh Postgres both succeed;
  - IDR 1234567.89 round-trips exactly on both engines.
- [x] 2.3 Replace `lastrowid` with `INSERT … RETURNING id` in `add_product`, `add_source` and `create_user`, on both engines. Add `, id` tie-breakers to every list `ORDER BY`. Verify: all six suites pass on SQLite; `grep -n lastrowid app/database.py` only matches the SQLite-only migration.
- [x] 2.4 Add `write_transaction(conn)` (SQLite: `BEGIN IMMEDIATE`; Postgres: `pg_advisory_xact_lock(USER_GUARD_LOCK)` as the first statement, READ COMMITTED, with a comment on why that order matters). Switch `create_user` and `guarded_user_change` to it, removing their `isolation_level` handling. Verify: `test_review_admins_cannot_both_demote` and the first-sign-up test pass on both engines.
- [x] 2.5 Add driver-error translation (`psycopg`/`sqlite3` `IntegrityError` → `db.IntegrityError`; `psycopg.OperationalError` → `DatabaseUnavailable`, logged without the URL). Replace `sqlite3.IntegrityError` in `app/refresh.py`. Verify: `grep -rn "import sqlite3" app` only matches `app/database.py`; `test_review_refreshes_take_turns` (a deleted listing mid-refresh) passes on both engines.
- [x] 2.6 Unify the test database setup:
  - `tests/helpers.use_temp_db()` and `reset_db()` handle both engines;
  - with `TEST_DATABASE_URL` set, they point the backend there and reset with `DROP SCHEMA public CASCADE; CREATE SCHEMA public` plus `init_db`;
  - they refuse any host but `localhost`/`127.0.0.1`, and any URL equal to `DATABASE_URL`;
  - move `test_auth.fresh_db`, `test_currency` and `test_history` off `DB_PATH.unlink()` onto `reset_db()`.

  Verify:
  - all six suites pass with no env set;
  - all six pass with `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5433/test`;
  - a test shows a non-localhost URL is refused before anything is dropped.
- [x] 2.7 Add a `DatabaseUnavailable` exception handler in `app/main.py` that renders a 503 "couldn't load your data" page. Verify: a new test makes `get_connection` raise, and checks the dashboard gives 503 with that text and never "Nothing tracked yet".

## 3. Hosted behaviour

- [x] 3.1 Add `GET /healthz` (`SELECT 1` through the port; `{"app","database"}`; 200/503; no URL, host or backend name). Verify: tests for the healthy and database-down cases, including a check that the body contains no `postgres`, `sqlite`, `neon` or `@` strings.
- [x] 3.2 Add `SCHEDULER_MODE` to `app/scheduler.py` (`mode()`; in cron mode `start_scheduler` adds no interval job, but `run_once` still works). Verify: a test for each mode checks the job list.
- [x] 3.3 Add `refresh.stalest_first` (latest live check `NULLS FIRST`, then id) and a deadline-bounded daily refresh that shares `_batch_lock`. Verify tests, on both engines:
  - never-checked listings come first, then oldest live check;
  - archived snapshots don't count as checks;
  - a fake clock past the deadline stops *starting* checks and leaves the rest.
- [x] 3.4 Add `GET /cron/daily` in `app/main.py`: a Bearer `CRON_SECRET` compared in constant time, 404 when unset. It runs the refresh, then `backfill_product(only_unchecked=True)` for products with unchecked sources, unless paused. Verify tests:
  - wrong or missing secret → refused with no fetch;
  - unset secret → 404;
  - right secret → stalest refreshed and unchecked history looked up;
  - paused → no archive call.
- [x] 3.5 Make `SameSitePostGuard` compare against `x-forwarded-host` when present. Verify tests:
  - a same-site post with `x-forwarded-host` = public host and an internal `host` is accepted;
  - a cross-site Origin is still refused;
  - no header → today's behaviour.
- [x] 3.6 Handle the secure cookie behind the proxy (uvicorn `--proxy-headers` in the image; no code change expected). Verify: a TestClient request with `base_url="https://…"` gets a `Secure` cookie. The container smoke job in 4.3 confirms the header path.
- [x] 3.7 Admin schedule display: `admin_page` passes `schedule_fixed`; the template shows "Once a day, set by the host"; `save_settings` ignores the interval in cron mode. Verify tests: in cron mode the page has no interval input, and a POST including `refresh_interval_hours` stores nothing for it while other fields save.

## 4. Container and CI

- [x] 4.1 Finalise `Dockerfile.vercel` and `.dockerignore`:
  - CMD `uvicorn … --host 0.0.0.0 --port ${PORT:-80} --proxy-headers --forwarded-allow-ips="*"`;
  - exclude `.venv`, `data/`, `docs/`, `openspec/`, `.claude/`, `.codex/`, `graphify-out/` and `.env`.

  Verify: the built image contains no `.env` or `data/` (`docker run … ls`), and `/healthz` returns 200 from `docker run -p`, both with no `DATABASE_URL` (SQLite) and with it pointed at the local Postgres.
- [x] 4.2 Update the requirements:
  - `requirements.txt`: pin `playwright==1.63.0`, `psycopg[binary]` and `psycopg-pool`;
  - add `requirements-dev.txt` (`httpx`).

  Verify: a fresh venv installed from both files runs all six suites.
- [x] 4.3 Add `.github/workflows/ci.yml`, run on push to main and on pull requests, with four jobs:
  - `test`: ubuntu + windows, Python 3.14. Install, `playwright install --with-deps chromium`, `compileall`, the six suites as separate steps, and the drift check on ubuntu;
  - `postgres`: ubuntu, a `postgres:17` service with a health check, `TEST_DATABASE_URL` set to it, and the six suites as separate steps;
  - `container`: build, `/healthz`, `/login`, and in-image `tests.test_shop_search`;
  - `deploy`: main pushes only, after the other three; skip with a notice when `VERCEL_TOKEN` is empty, otherwise `vercel deploy --prod` (pinned CLI) and curl production `/healthz`.

  Verify: push to main and all jobs go green, with deploy skipped and the notice visible in the log.
- [x] 4.4 Vendor `scripts/drift-check.sh` from the supercharge skill, with an upstream note in its header. Verify: `bash scripts/drift-check.sh` locally prints `0 dead`, and the same line appears in the CI log.
- [x] 4.5 Add `vercel.json`:
  - `git.deploymentEnabled: false`;
  - `regions: ["sin1"]`;
  - `crons: [{ "path": "/cron/daily", "schedule": "0 18 * * *" }]` (02:00 SGT).

  Verify: a JSON-schema check (`$schema` https://openapi.vercel.sh/vercel.json) accepts it, and the cron schedule is daily (Hobby-valid).

  Held back for one push (`a237b69`, owner, 2026-09-25) to try Vercel's Git auto-deploy, then committed the same day.

## 5. Docs (supercharge reconcile)

- [x] 5.1 Create `docs/delivery/` (ARCHITECTURE, IMPLEMENTATION, STATUS, suggestions). The ARCHITECTURE covers:
  - `Loc`: GitHub runner, Vercel instance, Vercel edge, Vercel cron, Neon pooler, Neon Postgres;
  - `Trm`: `t_ci`, `t_edge`, `t_cron`, `t_pg`;
  - the gate rule;
  - one image for CI and host.

  Verify: every IMPLEMENTATION row names a real `file:symbol` or workflow job, and the drift check passes.
- [x] 5.2 Update the docs of each component touched:
  - storage: the port and two adapters, the dialect tokens, `write_transaction` with its lock-first/READ COMMITTED rule, `RETURNING`, tie-breakers, error translation, the 503 rule;
  - refresh: `SCHEDULER_MODE`, the daily run, stalest-first, the budget;
  - settings: the fixed schedule in cron mode;
  - web: `/healthz`, `/cron/daily`, the guard's forwarded host;
  - auth: the Secure cookie behind the proxy; the race guards now through `write_transaction`.

  Each component gets updated ARCHITECTURE, IMPLEMENTATION and STATUS rows. Verify: the drift check reports 0 dead.
- [x] 5.3 Update `docs/architecture-map.md` (new `Loc`/`Trm` atoms, §5 checklist) and `docs/STATUS.md` (a delivery row, new test counts). Verify: each new atom appears in exactly one component's §7.
- [x] 5.4 Update the README:
  - a CI badge;
  - "Run with Docker";
  - "Hosting on Vercel", with the owner setup steps and the env var table (`DATABASE_URL` from Neon, `CRON_SECRET`, `SCHEDULER_MODE`; values never written down);
  - the Hobby daily-refresh note;
  - running the tests against local Postgres (`TEST_DATABASE_URL`).

  Verify: the README steps match `vercel.json` and the workflow.
- [x] 5.5 Update CLAUDE.md:
  - the hosted-mode section: the storage port, the dialect rules (the tokens, `DOUBLE PRECISION` never `REAL`, `RETURNING`, id tie-breakers, `NULLS FIRST`), `write_transaction`, cron mode;
  - invariant 3 extended: a DB outage is never empty data;
  - invariant 11 extended: tests never touch the hosted database, and the helper refuses non-localhost URLs;
  - the new traps: Postgres `REAL` precision, the lock-before-count rule, concurrent `CREATE TABLE`, image size, background threads on Vercel, the forwarded host;
  - the Running section: Docker, local Postgres, `TEST_DATABASE_URL`.

  Verify: each rule appears once, and the "Open / known-incomplete" section is updated.

## 6. Verify and hand over

- [x] 6.1 Run all six suites locally on SQLite and on the local Postgres, plus the drift check. Verify: all pass on both; record the check counts in docs/STATUS.md.
- [x] 6.2 Build and run the image locally with `SCHEDULER_MODE=cron`, `CRON_SECRET` and `DATABASE_URL` (local Postgres) set. Verify: `/healthz` returns 200, `/cron/daily` without the secret returns 401, and with the secret returns 200 with a report; the tables exist in the local Postgres afterwards.
- [ ] 6.3 Hand the owner the setup checklist:
  - a Vercel project with Container Images;
  - Neon installed from the Vercel Marketplace (Singapore if offered, Postgres 17, preview branching off), which injects `DATABASE_URL`;
  - `CRON_SECRET` and `SCHEDULER_MODE=cron`;
  - the three GitHub secrets.

  After their first deploy, confirm production `/healthz` returns 200, sign-in sets a Secure cookie, and the hosted `x-forwarded-host` behaviour matches what's recorded in CLAUDE.md. Verify: `/healthz` shows `database: ok` on the production URL.
