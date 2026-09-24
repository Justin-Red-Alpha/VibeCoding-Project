# Design

## Context

See proposal.md for why. Current state that shapes the approach:

- **Storage.** `app/database.py` opens a fresh `sqlite3` connection per call
  through a single function, `get_connection()`. Rows are `sqlite3.Row` (read by
  name; `fetchone()[0]` in four count queries; `.keys()` in
  `main._latest_per_source`). SQLite-specific pieces, surveyed 2026-09-24:
  - the schema: `INTEGER PRIMARY KEY AUTOINCREMENT` (5 tables), `COLLATE NOCASE`
    on `users.username`, `REAL` columns;
  - `create_user` and `guarded_user_change` set `isolation_level = None` and run
    `BEGIN IMMEDIATE`, which is what closes the first-sign-up and two-admins races;
  - `cur.lastrowid` in `add_product`, `add_source`, `create_user` and the v1→v2
    migration;
  - `PRAGMA` calls in `get_connection`, `_columns` and the migration;
  - `executescript` for the schema and the migration;
  - `add_snapshot` uses `with conn:` (commit or roll back);
  - list queries order by a timestamp only, with ties broken by insertion order.

  Everything else is portable: `ON CONFLICT … DO UPDATE SET … = excluded.…`,
  `CHECK`, `REFERENCES … ON DELETE CASCADE`, `IF NOT EXISTS`, `LIMIT`. There's no
  `INSERT OR`, no date function and no bare-column `GROUP BY`.

  `app/refresh.py` catches `sqlite3.IntegrityError`, the only `sqlite3` import
  outside storage.
- **Tests.** Three suites point `DB_PATH` at a temp file themselves and reset by
  deleting it (`test_auth.fresh_db`, `test_currency`, `test_history`). Two run
  raw SQL through `get_connection`.
- **Scheduling.**
  - `main.lifespan` runs `init_db`, then `fx.refresh_rates`, then
    `start_scheduler` (one APScheduler interval job, `refresh_all`).
  - `scheduler.run_once` runs one-off background jobs in threads: the history
    backfill, "Refresh my prices", and admin refresh-all.
  - In-memory state is per process: the login throttle and the Internet Archive
    cooldown.
- **Browser.** `browser.chromium()` is the only launch point, with
  `headless=True`. It uses a Proactor loop on Windows only.
- **Proxy.** Cookie `secure` comes from `request.url.scheme`.
  `SameSitePostGuard` compares Origin/Referer against the `Host` header.
- **Platform facts (checked 2026-09-24).**
  - Vercel Hobby: Container Images (Beta) build `Dockerfile.vercel` from the
    repo. Instances are stateless, serve on `$PORT` (default 80), and scale down
    after 5 idle minutes with SIGTERM and 30 s grace. Each request is capped at
    300 s, with 2 GB and 1 vCPU. Cron runs at most once a day, ±59 min.
  - Neon via the Vercel Marketplace injects `DATABASE_URL` (pooled, through
    PgBouncer in **transaction** mode) and `DATABASE_URL_UNPOOLED` (direct). Over
    the pooler, session-level advisory locks, `SET` and SQL-level `PREPARE` don't
    work. Transaction-scoped advisory locks and protocol-level prepared statements
    do. Neon scales its compute to zero when idle.
  - Local: SQLite 3.50.4 (supports `RETURNING` and `NULLS FIRST`).
    `psycopg-binary` 3.3.6 ships cp314 wheels for Windows and Linux.

## Goals / Non-Goals

**Goals:**
- One image, built by CI and by Vercel. No drift between what's tested and what's
  hosted.
- Local behaviour and every existing test unchanged when no hosting variable is
  set.
- The storage switch is a **port with two adapters**, selected by configuration.
  Every other module keeps calling `db.*`, and the function bodies in
  `database.py` stay as they are wherever the SQL is already portable.
- The same test suites pass on both engines. Engine differences are caught by CI,
  not by users.
- The invariants hold on the host too:
  - a block or outage never looks like empty data (invariant 3, extended to the
    database);
  - the admin page never claims a schedule it can't keep;
  - the two race guards stay atomic on both engines.

**Non-Goals:**
- Preview deploys and per-branch databases.
- Moving existing `data/app.db` contents into Neon. The hosted site starts
  empty, and its first account becomes admin (accepted).
- Native Postgres timestamp types. Timestamps stay ISO-8601 text, which sorts
  and compares the same on both engines.
- An ORM or query builder (the project deliberately uses plain SQL).
- A queue service such as Vercel Queues or Workflows for background jobs.
  Best-effort threads plus the daily backstop are enough for one owner.
- Multi-region, static IPs, or dodging shop bot walls from datacenter IPs.

## Decisions

### D1. Storage: a connection port with two adapters (not a rewrite)
**Model delta (storage).**

| Object / morphism | Signature | Partiality | Semantics |
| --- | --- | --- | --- |
| `Backend` (Dat, config) | `sqlite(path) ⊕ postgres(url)` | Total | chosen once per process: `DATABASE_URL` set → postgres, else sqlite at `DB_PATH` |
| `connect` | `Backend → Conn` | Partial (network) | failure raises `DatabaseUnavailable` |
| `Conn` | `execute`, `executescript`, `commit`, `rollback`, `close`, `with conn:` | — | the subset of `sqlite3.Connection` the code already uses. The Postgres adapter implements it |
| `Row` | read by name, by index, `.keys()`, `dict(row)` | — | the exact uses in the code today |
| `write_transaction` | `Conn → ctx` | Partial (blocks) | the one exclusive-write primitive: SQLite `BEGIN IMMEDIATE`; Postgres `BEGIN` + `pg_advisory_xact_lock(k)` |
| `schema` | `Dialect → SQL` | Total | one schema text with two dialect tokens |
| `translate` | `DriverError → IntegrityError ⊕ DatabaseUnavailable` | Total | the app's own exception types, raised from `database` |

**Consolidation check (§3).** There's no new data object. The rows, tables and
schema are the same `Dat` in a different `Loc`: `SQLite` becomes
`SQLite ⊕ NeonPostgres`. The new parts are one config object (`Backend`), a
dialect value derived from it, and the morphisms above. `get_connection()` is
already the port. Its body becomes the adapter choice.

**Why Neon/Postgres.** The owner chose it over Turso: it's the standard engine,
installs from the Vercel Marketplace, and injects its own credentials. The cost
is a real dialect, handled as follows.

**The schema: one text, two tokens** (one source of truth for shared structure):
- `{pk}` → SQLite `INTEGER PRIMARY KEY AUTOINCREMENT`; Postgres
  `INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY`. `INTEGER` keeps the
  foreign keys' types matching; two billion rows is plenty.
- `{username}` → SQLite `TEXT NOT NULL UNIQUE COLLATE NOCASE`; Postgres
  `CITEXT NOT NULL UNIQUE`, after `CREATE EXTENSION IF NOT EXISTS citext`. With
  `citext`, `WHERE username = ?` stays case-insensitive, so no query changes.
- `REAL` becomes `DOUBLE PRECISION` everywhere. **Postgres `REAL` is 4-byte and
  keeps only about 7 digits**, so it would round an IDR price such as 1,234,567.89,
  a silent money error. SQLite reads `DOUBLE PRECISION` as its own REAL, so one
  spelling serves both. Existing local tables are untouched (`IF NOT EXISTS`).

**Queries.**
- The adapter rewrites `?` placeholders to `%s`. The survey found no `?` or `%`
  inside a SQL literal. A test runs every query in the suites on Postgres, which
  would catch one added later.
- `INSERT … RETURNING id` replaces `lastrowid` in the three live call sites, on
  **both** engines, since SQLite 3.50 supports it. One spelling, no branch.
- `fetchone()[0]` keeps working because `Row` supports index access.
- Every list `ORDER BY` gains `, id` in the same direction. SQLite breaks timestamp
  ties by insertion order, but Postgres doesn't promise an order, so tests that
  expect "in the order added" could flake there.
- `stalest_first` (D4) writes `NULLS FIRST` explicitly. The engines disagree by
  default: SQLite sorts NULLs first ascending, Postgres last.

**The race guards: `write_transaction`.** `create_user` and
`guarded_user_change` stop poking `isolation_level` and use
`with write_transaction(conn):`.
- **SQLite** is unchanged: `BEGIN IMMEDIATE` takes the database write lock before
  the count.
- **Postgres** runs `SELECT pg_advisory_xact_lock(USER_GUARD_LOCK)` as the
  transaction's **first** statement, before the count. Both functions share one
  key, so first sign-ups and admin changes serialise against each other, which
  are the races the guards exist for. The lock is transaction-scoped, so it
  works through Neon's transaction-mode pooler, and it's released at commit or
  rollback.
- **Isolation must stay READ COMMITTED** (Postgres's default). Each statement
  then sees rows committed before it started, so the count after the lock sees
  the other transaction's commit. Under REPEATABLE READ the snapshot would be
  taken by the lock statement itself, *before* the wait. The count would then
  miss the other commit and the race would reopen. A comment at the lock says so,
  and the existing concurrency tests run on Postgres in CI.

**Connections.** A Postgres connection costs a TLS handshake, so the Postgres
adapter uses `psycopg_pool.ConnectionPool` (lazy open, `max_size=4`, checked on
checkout so connections dropped by Neon's scale-to-zero are replaced). It uses
the pooled `DATABASE_URL`, as Neon recommends for serverless. `Conn.close()`
returns the connection to the pool instead of closing it. SQLite still opens a
connection per call, as now.

**Errors.**
- `psycopg.IntegrityError` and `sqlite3.IntegrityError` → `db.IntegrityError`
  (`refresh._record` and `create_user`'s `UsernameTaken` catch this).
- `psycopg.OperationalError` → `DatabaseUnavailable`.
- A failed statement aborts a Postgres transaction. `with conn:` and
  `write_transaction` roll back before the error propagates, and the pool resets
  a returned connection. This keeps the `add_snapshot` rule ("roll back before
  anything else writes") true on both engines.
- Routes let `DatabaseUnavailable` reach one exception handler, which renders a
  503 page ("couldn't load your data"). It never renders an empty list.

**Schema creation on a cold start.** Two Vercel instances starting at once can
both run `CREATE TABLE IF NOT EXISTS`, and Postgres can reject the second with a
duplicate-type error. `init_db` on Postgres therefore runs the schema inside one
transaction after `pg_advisory_xact_lock(SCHEMA_LOCK)`. The SQLite-only v1→v2
migration and `_add_missing_columns` are skipped on Postgres, whose database
always starts from the current schema. Invariant 8 is unaffected.

*Alternatives:*
- Two separate schema files: they would drift. Rejected in favour of tokens.
- `lower(username)` indexes instead of `citext`: every username query would need
  changing on one engine only.
- SERIALIZABLE isolation with retries instead of advisory locks: retry loops in
  two functions, harder to test.
- The direct (unpooled) URL: fine for one instance, but Neon recommends the
  pooled one for serverless.
- An ORM: against the project's deliberate "plain SQL" choice.

### D2. One image: `Dockerfile.vercel`, built by CI and by Vercel
- Base `python:3.14-slim-bookworm` (Debian 12, which Playwright supports).
- Steps: `pip install -r requirements.txt`, then
  `python -m playwright install --with-deps chromium` (the headless shell), then
  copy `app/` and `tests/`, then run as a non-root user. `psycopg[binary]` bundles
  libpq, so no extra system package is needed.
- `CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-80} --proxy-headers
  --forwarded-allow-ips="*"`. There's no `--reload` in the image, so the Windows
  reload traps don't apply.
- The file name is the one Vercel detects with zero config. CI and local use
  `docker build -f Dockerfile.vercel`.
- `tests/` ships in the image so the CI smoke job runs `tests.test_shop_search`
  *inside* the image, proving Chromium works there. It's small, and tests are
  never served.
- `.dockerignore` excludes `.venv`, `data/`, `docs/`, `openspec/`, `.claude/`,
  `.codex/`, `graphify-out/` and `.env`.

*Alternatives:*
- A plain `Dockerfile` plus `vercel.json` `services` naming it: more config.
- The Playwright base image: pins Python 3.12, while local and CI use 3.14.
- GHCR publishing: dropped, because Vercel builds from the repo.

### D3. CI: GitHub Actions, one workflow, four jobs
`.github/workflows/ci.yml`, run on `push: main` and `pull_request`.

1. **`test`**
   - matrix `ubuntu-latest` and `windows-latest`, Python 3.14, pip cache;
   - install `requirements.txt` plus `requirements-dev.txt`, then
     `playwright install --with-deps chromium`;
   - `python -m compileall -q app tests`;
   - the six suites on SQLite, each its own step so a failure names the suite,
     with `PYTHONIOENCODING=utf-8`;
   - `bash scripts/drift-check.sh` on Ubuntu.
2. **`postgres`** (Ubuntu only, since service containers don't run on Windows
   runners):
   - a `postgres:17` service container with a health check;
   - `TEST_DATABASE_URL=postgresql://postgres:postgres@localhost:5432/test`;
   - the six suites again, each its own step.
3. **`container`** (needs `test` and `postgres`, Ubuntu):
   - `docker build -f Dockerfile.vercel`;
   - start the image and poll `/healthz` until it returns 200;
   - check `/login` returns 200;
   - `docker run … python -m tests.test_shop_search`.
4. **`deploy`** (needs the other three, only on `push` to `main`):
   - if `VERCEL_TOKEN` is empty, print a notice and exit 0 (spec: "No
     credentials yet");
   - otherwise `npx vercel@<pinned> deploy --prod --token …` with
     `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID`, so Vercel builds the image;
   - then `curl` the production `/healthz`.

`vercel.json` sets `"git": {"deploymentEnabled": false}` so pushes can't bypass
the gate.

**The test database guard.** `tests/helpers.use_temp_db()` is the one entry
point for every suite:
- **SQLite:** a temp file, as now.
- **`TEST_DATABASE_URL` set:** the backend points there. Reset runs
  `DROP SCHEMA public CASCADE; CREATE SCHEMA public` and then `init_db`.
  Because that erases everything, the helper **refuses to run unless the URL's
  host is `localhost` or `127.0.0.1`**, and refuses if it equals `DATABASE_URL`.
  Invariant 11 grows to cover this: tests never touch the hosted database.

The three suites that set `DB_PATH` and delete the file themselves switch to
`use_temp_db()` and `reset_db()`.

**The drift check is vendored** to `scripts/drift-check.sh`, with a header
naming its upstream, so CI doesn't depend on `~/.claude`. The supercharge
workflow keeps calling its own copy locally. Both are the same file.

### D4. Scheduling: `SCHEDULER_MODE = in-process ⊕ cron`
**Model delta (refresh).**

| Object / morphism | Signature | Partiality | Semantics |
| --- | --- | --- | --- |
| `SchedulerMode` (Dat, config) | `in-process ⊕ cron` | Total | env `SCHEDULER_MODE`, default `in-process` |
| `daily_run` | `Secret × Budget → Report` | Partial (auth) | the cron endpoint: refresh the stalest first, then backfill the unchecked |
| `stalest_first` | `() → Source*` | Total | order by latest *live* snapshot time `NULLS FIRST`, then id |
| `within_budget` | `Source* × deadline → Source*` | Total | stops *starting* new checks at `deadline − margin` |

- **In-process** (local, Docker): exactly today's behaviour.
- **Cron:**
  - `start_scheduler` starts the APScheduler instance, which `run_once` still
    uses for best-effort jobs, but adds **no interval job**;
  - `vercel.json` `crons` calls `GET /cron/daily` once a day;
  - the endpoint needs `Authorization: Bearer $CRON_SECRET`, compared in
    constant time. With no secret configured it's a 404.
- **Budget.** The route holds its request open for the work. The deadline is
  `start + 240 s`, leaving 60 s under Vercel's 300 s. Refresh gets the first
  part. The remaining time goes to `history.backfill_product(only_unchecked=True)`
  for products with unchecked sources, unless paused. The backfill already stops
  cleanly on pause and on the archive's 429.
- **Resumability comes from stored state, not a queue.** A cut-off check leaves
  the source "stale". A cut-off lookup leaves `history_checked_at` NULL. Both are
  picked up next time. The state is deduced, not stored twice (§6.3).
- The daily run and `refresh_all` share `_batch_lock`, so turn-taking still
  holds within an instance.

*Alternatives:*
- Keeping APScheduler on Vercel: instances scale to zero, so the timer would
  never fire reliably.
- Vercel Queues or Workflows: more moving parts than one owner needs.

### D5. Behind the proxy
- uvicorn `--proxy-headers --forwarded-allow-ips="*"` in the image only. Vercel
  is the sole ingress, so `request.url.scheme` becomes `https` and the cookie is
  `Secure`.
- `SameSitePostGuard` compares against `x-forwarded-host` when present, else
  `host`. This works because uvicorn doesn't rewrite `host` from forwarded
  headers, and Vercel may send the internal host there.
- Locally there's no `x-forwarded-host`, so the guard behaves as today.
- *Risk:* a direct client could send a forged `x-forwarded-host`. But the guard
  defends a **browser's** cross-site post, and a browser can't set that header on
  a form post. The protection is unchanged.

### D6. `/healthz` and the admin schedule display
- `/healthz` runs `SELECT 1` through the port. It returns `{"app": "ok",
  "database": "ok"|"unreachable"}` with 200 or 503, and never the URL, the host
  or the backend name.
- `admin_page` passes `schedule_fixed = scheduler.mode() == "cron"`, and the
  template swaps the interval input for text.
- In cron mode, `save_settings` skips the interval field entirely: it isn't
  cleaned or stored (spec: "Interval posted anyway").

### §4.5 coherence laws this change must keep
- **1. Placement honesty.** Views still come only from rows delivered over
  `t_sql`, whether `SQLite` or `NeonPostgres`. The 503 page is the honest
  placement when `t_sql` fails.
- **2. Transmission well-typing.** New `Trm` atoms, each with one payload type:
  - `t_pg` (rows over TLS, ServerProc ⇄ NeonPooler ⇄ NeonPostgres);
  - `t_cron` (authenticated trigger, VercelCron → ServerProc);
  - `t_edge` (HTTPS, UserBrowser ⇄ VercelEdge ⇄ ServerProc);
  - `t_ci` (source, GitHub → Runner).
- **3. Placement totality.**
  - `ServerProc` gains a hosted placement, `VercelInstance`;
  - the daily run is placed in a request thread, and best-effort jobs in
    scheduler threads;
  - `runsAt` is written down for each.
- **4. Dependency mediation.** Nothing reaches the database except through
  `get_connection`, and nothing reaches Chromium except through
  `browser.chromium`. Both ports are unchanged in shape. The race guards reach
  locking only through `write_transaction`.
- **5. Composition soundness.** A new `docs/delivery/` component. The storage,
  refresh and settings maps gain rows. The drift check runs in CI, which makes
  this law mechanically enforced.

## Risks / Trade-offs

- **[A dialect difference slips through]** (ordering, NULL placement, float
  precision, case rules) → The same six suites run on real Postgres 17 in CI on
  every push. The decisions above cover the known differences, and each has a
  test that fails on the wrong engine: the id tie-breaker, `NULLS FIRST`, the
  `DOUBLE PRECISION` round-trip of an IDR price, and case-insensitive usernames.
- **[The race guards weaken on Postgres]** → `test_review_admins_cannot_both_demote`
  and the first-sign-up test run on Postgres. The lock-first, READ COMMITTED rule
  is written at the lock site.
- **[Tests erase a real database]** → The helper refuses any non-localhost URL,
  and refuses a URL equal to `DATABASE_URL`. The CI Postgres job only ever
  receives the service container's URL.
- **[Vercel rejects the image size]** Chromium plus its libraries make an image
  of about 1 GB. The Function size limits say 500 MB for Python and 5 GB for
  Large Functions (Beta), and container images inherit "Function limits" → an
  early deploy settles it. If it's rejected, the fallback is shop search via a
  remote browser (`connect_over_cdp`) behind `browser.chromium`. That would be a
  new decision for the owner.
- **[Background threads freeze after a response on container Functions]** → The
  daily run is the backstop, and the UI already says "reload in a minute". The
  worst case is that archived history arrives the next day.
- **[Cold start]** Pulling the image plus Chromium's first launch took about 15 s
  locally, and Neon's compute also wakes from zero (typically well under a
  second) → accepted for a personal site. The first request after idle is slow.
  Region `sin1` with Neon in Singapore keeps the database round-trips short.
- **[Shops block datacenter IPs]** → They're already reported as blocked, never
  as empty (invariant 3). Discovery quality on the host may be lower than at home.
- **[In-memory state is per instance]** (login throttle, archive cooldown) →
  Accepted for one owner and recorded. A persistent throttle is already listed
  in auth STATUS as needed before wider exposure.
- **[Secrets in logs]** → `DATABASE_URL` holds a password. It's passed only as
  env, never logged or echoed by the workflow, and `/healthz` never reveals it.
  The driver's connection errors are logged without the URL.

## Migration Plan

1. Merge the CI and container work first. The deploy job stays skipped until the
   owner adds secrets, so `main` stays green meanwhile.
2. The owner sets up:
   - a Vercel project with Container Images enabled and region `sin1`;
   - Neon from the Vercel Marketplace: Singapore region if offered, Postgres 17
     to match CI, preview branching **off** for now. It injects `DATABASE_URL`
     and `DATABASE_URL_UNPOOLED` itself, so neither is typed by hand;
   - the Vercel env vars `CRON_SECRET` and `SCHEDULER_MODE=cron`;
   - the GitHub secrets `VERCEL_TOKEN`, `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID`.
3. The next green push to `main` deploys. The first request creates the schema.
   Register the admin account on the hosted site first.
4. **Rollback:** promote the previous deployment in Vercel (instant). The data
   stays in Neon, and Neon's point-in-time restore covers a bad write. Local use
   is unaffected throughout: no `DATABASE_URL` means SQLite and in-process
   scheduling.

## Open Questions

- The exact pins for `psycopg[binary]` and `psycopg-pool` (3.3.6 and 3.3.3 were
  current on 2026-09-24) and the Vercel CLI. They're chosen when the files are
  written, and don't change the approach.
- Whether Vercel forwards the public host in `host` or `x-forwarded-host`. D5
  handles both, and the first deploy confirms which (a task records the answer
  in CLAUDE.md).
- Whether Neon offers Singapore on the Marketplace, and its default Postgres
  major version. Chosen at setup; CI pins 17 to match.
