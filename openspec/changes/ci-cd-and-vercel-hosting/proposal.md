# Proposal

## Why

Nothing checks a change before it lands. The six offline suites (486 checks) only
run when someone remembers to run them, and only on Windows. The app also runs
only on its owner's machine. The owner now wants CI, a container image, and a
first move to hosting on Vercel.

Vercel can now run a repo's `Dockerfile.vercel` as a Function (Container Images,
Beta, checked 2026-09-24). That matters because the core feature, shop search,
needs Chromium, which Vercel's plain Python runtime can't hold. So one image can
serve both CI and hosting.

Vercel instances are **stateless**, though. They scale down after 5 idle minutes
and lose their disk, so the SQLite file, the in-process scheduler and the
background jobs all need a hosted counterpart. Vercel has no database of its own;
databases come from its Marketplace. The owner chose **Neon** (Postgres), which
installs into the Vercel project and injects its connection settings itself.

## What Changes

- **CI (GitHub Actions)** on every push to `main` and every pull request:
  - byte-compile everything;
  - run the six offline suites on Ubuntu and Windows (Python 3.14, with
    Playwright's Chromium);
  - run the suites again on Ubuntu against a real **Postgres** service container,
    the same engine production uses;
  - run the docs drift check. The script is copied into the repo, since today it
    lives only in `~/.claude`.
- **Container:** one `Dockerfile.vercel` (Python 3.14, Playwright + Chromium, a
  non-root user). CI builds it, starts it and smoke-tests it: a page loads and
  Chromium renders inside it. Vercel builds the same file. No GHCR publishing:
  Vercel builds from the repo, so a second registry copy would add nothing.
- **Gated deploys:** after every CI job passes on a push to `main`, a deploy job
  ships to Vercel production with the Vercel CLI. Vercel's own Git auto-deploy is
  switched off, so a failing test always blocks a deploy. The job skips cleanly,
  with a notice, until the repo has a `VERCEL_TOKEN` secret.
- **Hosted database (Neon Postgres via the Vercel Marketplace):**
  - the storage layer gains one connection port with two adapters: the local
    SQLite file (unchanged default) and Postgres, chosen by `DATABASE_URL`;
  - one schema serves both engines, with two dialect differences (the id column
    and case-insensitive usernames);
  - `BEGIN IMMEDIATE` race guards become one write-transaction primitive:
    SQLite keeps `BEGIN IMMEDIATE`, and Postgres takes a transaction-scoped
    advisory lock, so the two-admins and first-sign-up races stay closed;
  - new ids come from `RETURNING` (on both engines) instead of `lastrowid`;
  - list queries gain an id tie-breaker, so order is identical on both engines;
  - driver errors are translated into the app's own error types, so no caller
    imports `sqlite3`;
  - an unreachable database is reported as an outage, never shown as an empty
    site.
- **Hosted scheduling (Vercel Hobby):**
  - a daily Vercel Cron call to a secret-protected endpoint replaces the
    in-process 6-hour timer when `SCHEDULER_MODE=cron`;
  - it refreshes the stalest listings first within a time budget below Vercel's
    300 s limit, then finishes any archive lookups left undone;
  - background jobs stay best-effort, and the daily run is their backstop.
- **Behind Vercel's proxy:** trust forwarded headers, so the sign-in cookie is
  `Secure` over HTTPS and the cross-site form guard compares against the public
  host name.
- **Health check:** `GET /healthz` reports that the app and its database answer,
  without exposing configuration.
- **Admin page honesty:** when refreshes are scheduled by the host, the refresh
  interval is shown as the host's fixed daily schedule, not as an editable
  setting it can't honour.
- **Dependencies:**
  - `requirements.txt` gains `playwright`, `psycopg[binary]` and `psycopg-pool`
    (pinned; Python 3.14 wheels confirmed for Windows and Linux);
  - a new `requirements-dev.txt` holds test-only packages (`httpx`, which
    `TestClient` needs).
- **Out of scope:**
  - preview deploys. Neon can give each preview its own database copy, which
    makes them safe later, but they're a separate change;
  - per-form CSRF tokens and a persistent login throttle, deferred while this
    stays a personal site;
  - moving existing local data into Neon;
  - storing timestamps as a native Postgres type (they stay ISO text, as now).

## Capabilities

### New Capabilities
- `delivery-pipeline`: every change is checked on two operating systems and on
  the production database engine, the container is built and smoke-tested, and
  only a fully green `main` reaches production.
- `hosted-site`: how the app behaves on stateless hosting:
  - data survives restarts;
  - outages are reported, not hidden;
  - scheduled work is authenticated, bounded and resumable;
  - cookies and the cross-site guard work behind the host's proxy;
  - there's a health check.

### Modified Capabilities
- `site-administration`: the refresh interval setting says when the host fixes
  the schedule (daily on Vercel Hobby), instead of claiming an interval it can't
  keep.

## Impact

- **New files:**
  - `.github/workflows/ci.yml`
  - `Dockerfile.vercel`, `.dockerignore`
  - `vercel.json` (cron, region, no Git auto-deploy)
  - `requirements-dev.txt`
  - `scripts/drift-check.sh`
  - `docs/delivery/` (new component: ARCHITECTURE, IMPLEMENTATION, STATUS,
    suggestions)
- **Changed code:**
  - `app/database.py`: the connection port, the Postgres adapter (pooled), the
    shared schema with dialect tokens, the write-transaction primitive,
    `RETURNING` ids, id tie-breakers, error translation;
  - `app/refresh.py`: stops catching `sqlite3.IntegrityError` directly;
  - `app/main.py`: `/healthz`, the cron endpoint, the DB-outage response;
  - `app/scheduler.py`: `SCHEDULER_MODE`;
  - `app/refresh.py` and `app/history.py`: time-budgeted and resumable sweeps;
  - `app/admin.py` and `app/templates/admin.html`: fixed-schedule display.
- **Tests:**
  - one reset helper that works on both engines replaces the "delete the DB
    file" resets in `test_auth`, `test_currency` and `test_history`;
  - with `TEST_DATABASE_URL` set, every suite runs against Postgres. The helper
    refuses any host but localhost, because the reset drops the schema;
  - new tests for the cron endpoint (auth, budget, stalest-first), `/healthz`,
    the outage response, and proxy-header cookies and guard.
- **Docs:** README (CI badge, Docker, hosting setup), CLAUDE.md (hosted mode,
  the dialect rules, the new traps), storage, refresh and settings docs, and the
  architecture map (new `Loc` and `Trm` atoms: GitHub runner, Vercel instance,
  Neon, cron).
- **Owner setup (can't be done from here):**
  - create the Vercel project and enable Container Images (Beta);
  - install Neon from the Vercel Marketplace (Singapore region if offered,
    Postgres 17, preview branching off for now). It injects `DATABASE_URL`
    itself;
  - set `CRON_SECRET` and `SCHEDULER_MODE=cron` in Vercel;
  - add `VERCEL_TOKEN`, `VERCEL_ORG_ID` and `VERCEL_PROJECT_ID` to the GitHub
    repo's secrets.
- **Known risks, verified early in tasks:**
  - whether Vercel's container size limit fits a Chromium image;
  - whether background threads keep running after a response on container
    Functions;
  - concurrent cold starts racing on `CREATE TABLE IF NOT EXISTS` (Postgres can
    reject this);
  - shops blocking datacenter IPs (already reported honestly, invariant 3).
