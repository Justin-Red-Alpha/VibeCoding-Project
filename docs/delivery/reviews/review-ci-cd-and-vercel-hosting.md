# Review — ci-cd-and-vercel-hosting

> Ran after building (2026-09-25). Checks the change against FRAMEWORK §4.5. Not a
> prose review. Scope: storage port, hosted behaviour (web, refresh, settings,
> auth, history) and the new delivery component.

## Coherence laws
- [x] 1. Placement honesty — every view still comes only from rows delivered over
      `t_sql` or `t_pg`. When that transmission fails, `DatabaseUnavailable`
      becomes the 503 page, which reads nothing from the database (it doesn't
      extend `base.html`). `tests/test_hosting.py:test_outage_is_not_empty_data`.
- [x] 2. Transmission well-typing — each new `Trm` has one `carries` type and a
      real boundary: `t_pg` (rows), `t_edge` (HTTPS plus forwarded headers),
      `t_cron` (`CronCall` with a Bearer secret), `t_ci`, `t_ci_pg`, `t_deploy`
      (delivery §7). `t_sse` is still advisory, as before (web suggestion #1).
- [x] 3. Placement totality — `daily_run` is placed on a request thread of a
      `VercelInstance` (refresh §7). `build_image` is placed on `GitHubRunner` and
      `VercelBuild`. storage's `Dat` is at `SQLite` or `NeonPostgres`. Every
      placement has a component.
- [x] 4. Dependency mediation — no module outside `app/database.py` imports a
      driver (`grep -rn "import sqlite3" app` → only `database.py`). The race
      guards reach locking only through `write_transaction`. The runner reaches
      Vercel only through `t_deploy`.
- [x] 5. Composition soundness — root map, root implementation map and root
      status point at the component docs, not restating them. The drift check
      (0 dead / 562 refs) now also runs in CI.
- [x] 6. runsAt is a relation — `ServerProc` (machine, Docker, Vercel),
      `build_image` (runner, Vercel) and storage's `Dat` (SQLite, Neon) are all
      written as multi-placed (architecture-map §4). Nothing assumes one site.

## Model delta actually shipped
Recorded in `openspec/changes/ci-cd-and-vercel-hosting/design.md` under
"Implementation notes": a seventh suite (`tests/test_hosting.py`), the image also
installing `requirements-dev.txt`, the concrete daily budget (150 s / 230 s), the
history `stop` hook with `CUT_SHORT_REASON` (absorbed by history rule 8 and
refresh rule 8), the SQLite adapter as a `sqlite3.Connection` subclass, the pool
reset in the test helper, and the `PRODUCTION_URL` variable.

Evidence the guards hold, not just pass: on Postgres, removing the advisory lock
let 2–4 of 4 racing first sign-ups become admin. Keeping the lock but switching to
REPEATABLE READ let 3–4 through. The shipped code gave exactly one admin in 10 of
10 races.

## Modeling smells swept (§3)
- **No parallel objects.** The hosted database is storage's `Dat` at a second
  `Loc`, not a twin schema. One schema text with two dialect tokens.
- **Deduced, not copied.** "Stalest" is deduced from snapshots (latest live
  `fetched_at`). "Unchecked" is `history_checked_at IS NULL`. There's no queue
  table, and nothing is stored twice.
- **One source of truth.** One image recipe for CI and host. One drift script,
  vendored with a header naming its upstream. One test-database helper for both
  engines. Open: the suite list is repeated in the two CI jobs and CLAUDE.md
  (delivery suggestion #4).
