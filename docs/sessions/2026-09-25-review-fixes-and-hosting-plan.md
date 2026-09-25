# 2026-09-25 — review fixes, hosting plan, and git identity

Covers the work after `2026-09-24-user-accounts-and-admin.md`, from the 2026-09-24
code review through to 2026-09-25.

## 0. Continuation brief
Current state:
- **Code review:** all 15 findings are fixed, tested and pushed (`ef0594e`). The
  six suites pass at HEAD with 486 checks.
- **Hosting plan:** CI/CD plus Vercel hosting is **planned but not applied**, as
  OpenSpec change `ci-cd-and-vercel-hosting` (0/29 tasks, pushed in `0fca150`).
  It targets **Neon Postgres** from the Vercel Marketplace. Turso was the first
  choice and was dropped.
- **Git identity:** the history was rewritten to the work identity and
  force-pushed. **Every SHA before `0fca150` changed** (map in §3). Older logs
  quote the old SHAs.
- **Vercel:** the owner has already connected a Vercel project with Git
  auto-deploy on. Its deployments crash at startup (`500
  FUNCTION_INVOCATION_FAILED`) because SQLite can't write to Vercel's read-only
  filesystem. That's expected until the plan lands, and it's harmless: nothing
  is served.
- **Local:** nothing is running, and the Docker daemon is off.

Next step: start Docker Desktop, then apply `ci-cd-and-vercel-hosting`. Task 1.1
runs a local Postgres 17 in Docker.

Resume command/check: `openspec instructions apply --change "ci-cd-and-vercel-hosting" --json`
(with `export PATH="$PATH:/c/Users/Justin/.bun/bin"`), then read
`openspec/changes/ci-cd-and-vercel-hosting/design.md`.

## 1. Work completed

**Code review: 15 findings fixed** (`ef0594e`, previously `6c79b02`). Each fix has
a test, in `tests/test_auth.py` (`test_review_*`) and `tests/test_history.py`
(`test_admin_pause_stops_running_lookups`).

- **Concurrency:**
  - the sign-in throttle counts guesses still in flight under a lock;
  - the last-admin guard runs as one `BEGIN IMMEDIATE` transaction
    (`db.guarded_user_change`);
  - refresh batches take turns on `refresh._batch_lock`;
  - the admin "refresh all" reuses the scheduled job (`scheduler.refresh_all_now`);
  - a listing deleted mid-refresh no longer stops the batch.
- **Settings:**
  - every field is cleaned before any write;
  - only changed values are stored;
  - shops are stored as the ones switched *off*;
  - numbers render exactly (`format_number`);
  - unusable env values are listed (`ignored_env`);
  - the refresh interval reschedules only when it changes.
- **Other:**
  - "As quoted" beats the site default (`templating.display_currency_for`);
  - "Refresh my prices" runs in the background;
  - the FX button reports failed fetches (`fx.fetch_fresh_rates`);
  - pausing archive lookups stops running ones;
  - `test_auth` blocks `requests`.
- **New bug found while testing:** a refused `add_snapshot` insert left its
  transaction open, holding the write lock, so every other write got "database is
  locked". Fixed with `with conn:` plus `close()` in `finally`. Now a CLAUDE.md
  trap.

**`--reload` trap** (documented in CLAUDE.md). uvicorn 0.30.6 restarts its worker
with a Ctrl+C console event, which never reaches a server started from an agent's
background shell. It logs `Reloading...` and keeps serving old code. The pre-fix
commit behaved the same. After editing, stop and restart the server.

**CI/CD and hosting, planned** (`0fca150`). Change `ci-cd-and-vercel-hosting`:
proposal, design, tasks, and three spec deltas (`delivery-pipeline` and
`hosted-site` new; `site-administration` modified). It passes
`openspec validate --strict`.

**Git identity fixed.** All 11 commits carried the personal identity
`Bznboy <Bznsin@hotmail.com>` in a work repo pushed with the work account's
credentials.
- Added `~/.gitconfig-work` (`Justin-Red-Alpha <justin.yip@redalphacyber.com>`).
- Added an `includeIf "gitdir/i:C:/Users/Justin/GitHub Repos/VibeCoding Project/"`
  rule in `~/.gitconfig`.
- Rewrote the author and committer on all 11 commits with `git filter-branch`.
  The tree hash is unchanged (`3b6ae61`), and there's zero diff against the
  backup.
- Force-pushed with `--force-with-lease`.
- Saved memory `git-identity-work-vs-personal`.

**Vercel 500 diagnosed** (see §3).

## 2. Decisions
| Decision | Verdict | Why |
| --- | --- | --- |
| Host on Vercel via Container Images (`Dockerfile.vercel`) | kept | shop search needs Chromium, which the plain Python runtime can't hold; one image serves CI and Vercel |
| Vercel's plain Python runtime (zero-config) | discarded | no Chromium; it's what's deployed now, and it crashes |
| Publish the image to GHCR | discarded | Vercel builds from the repo, so a registry copy adds nothing |
| Database: Neon Postgres from the Vercel Marketplace | **kept (owner's final choice)** | the standard engine; injects `DATABASE_URL`; free plan |
| Database: Turso / libSQL | discarded (owner switched to Neon) | would have kept the SQLite dialect; it was the first choice |
| Keep data in the image, or SQLite in `/tmp` | discarded | Vercel disks are read-only apart from an ephemeral `/tmp`; data would vanish on scale-down, and since the site is public, the next registrant would become admin |
| Deploys: GitHub Actions + Vercel CLI after every job passes | kept | a failing test blocks the deploy; `vercel.json` sets `git.deploymentEnabled: false` |
| Deploys: Vercel Git integration | discarded | deploys even when tests fail (it's on now, and that's why the crashing deploys exist) |
| Vercel plan: Hobby | kept | cron at most once a day (±59 min); 300 s per request |
| First account becomes admin on the hosted site | accepted | personal project |
| Postgres race guards: `pg_advisory_xact_lock` as the first statement, READ COMMITTED | kept | works through Neon's transaction-mode PgBouncer; REPEATABLE READ would reopen the race |
| SERIALIZABLE isolation with retries | discarded | retry loops in two functions, harder to test |
| One schema text with `{pk}` and `{username}` tokens | kept | one source of truth; `DOUBLE PRECISION` everywhere, because Postgres `REAL` would round IDR prices |
| Two schema files, or `lower(username)` indexes | discarded | would drift, or would need changes to queries on one engine only |
| Identity: work, via `includeIf` scoped to this repo only | kept (owner) | the owner also chose to leave the sibling repo `advertising-data-analytics` untouched: it's on the work account but still commits as personal, **deliberately** |
| Rewrite all 11 commits and force-push | done (owner approved) | solo private repo, one branch; backups kept locally |
| Settings store the shops switched *off* | kept | a shop added to `ADAPTERS` is searched automatically |

## 3. Tests, checks, benchmarks
| Check | Result | What it proved |
| --- | --- | --- |
| Six suites at `0fca150` (`PYTHONIOENCODING=utf-8 python -m tests.<suite>`) | all exit 0: extraction 63, search 48, currency 89, shop_search 32, history 83, auth 171 = **486** | nothing regressed |
| New tests against the pre-fix code (swapped in from `git show`) | old throttle checked **40 of 40** parallel guesses (fixed: ≤ 5); without `_batch_lock`, two batches overlapped (peak 2) | the concurrency tests catch the real bugs |
| `openspec validate ci-cd-and-vercel-hosting --strict` | valid | the plan is well-formed |
| Drift check | 0 dead / 441 refs | docs match the code |
| `psycopg-binary` wheels | 3.3.6 has cp314 wheels for `win_amd64` and `manylinux_2_17_x86_64` | the Postgres driver works on Python 3.14 |
| The app on **Python 3.12** in a clean uv venv | compiles; imports; `/login` 200 on a writable disk | Vercel's default 3.12 isn't the cause of the 500 |
| Startup when `data/` can't be created | lifespan raises and startup crashes | matches the Vercel `FUNCTION_INVOCATION_FAILED` (read-only `/var/task`, `data/` not in the repo) |
| `--reload` on the pre-fix commit (throwaway worktree, port 8011) | hangs the same way | the reload hang is the environment, not the code |
| Read-only check of `data/app.db` | 1 admin, 0 unowned products, 1 product | the owner registered; last log's P1 is resolved |
| Graph refresh | 1664 nodes, 3494 edges, 115 communities (`graphify-out/`, 2026-09-25) | the graph tracks `ef0594e`'s code. The `graphify` / `graphify.exe` launchers are broken (uv shim points at a missing script); run `"$APPDATA/uv/tools/graphifyy/Scripts/python.exe" -m graphify update .` instead |

**SHA map for the 2026-09-24 history rewrite.** Older logs quote the left
column; the same commits now have the right one.

| Old | New | Subject |
| --- | --- | --- |
| `6d59985` | `485981a` | Initial commit: price drop decision tracker |
| `64fb4fa` | `531a230` | Set up OpenSpec and graphify for the supercharge workflow |
| `64f5e0d` | `f3cd47a` | Add session handoff log for 2026-09-23 |
| `9a3fc71` | `9d26d5a` | Codex Luna implemented currency fixes |
| `e137385` | `c2d1ec7` | adding supercharge skill to codex |
| `b821d90` | `3747927` | Add target-price currency and cut shop search from 30s to 8s |
| `7fd8901` | `2bef1f2` | Add session handoff log for 2026-09-24 |
| `9aaceba` | `427186b` | Add supercharge docs tree so the drift check has something to verify |
| `0e2ff68` | `df7dc02` | Add archived price history from the Internet Archive |
| `d59bb0f` | `a80740a` | Add user accounts, roles and an admin page |
| `6c79b02` | `ef0594e` | Fix the 15 code-review findings on accounts and the admin page |

## 4. Live handoff state
| Type | Handle / location | State | Inspect / resume | Stop / cleanup |
| --- | --- | --- | --- | --- |
| branch | `main` | clean, in sync with `origin/main` at `0fca150` (plus this log's commit, unpushed) | `git status -sb` | none |
| git refs (local only) | `refs/backup/pre-author-rewrite`, `refs/original/refs/heads/main` → `6c79b02` | kept as the pre-rewrite safety net | `git for-each-ref refs/backup refs/original` | when the owner is satisfied: `git update-ref -d refs/backup/pre-author-rewrite && git update-ref -d refs/original/refs/heads/main` |
| git config (outside repo) | `~/.gitconfig` `includeIf` + `~/.gitconfig-work` | active | `git config user.email` in this repo → work; in `advertising-data-analytics` → personal | to broaden the rule, change its path to `C:/Users/Justin/GitHub Repos/` |
| process | uvicorn on port 8000 | **stopped** (none running) | `Get-NetTCPConnection -LocalPort 8000 -State Listen` | none |
| service | Docker Desktop daemon | **not running** | `docker ps` | start Docker Desktop before task 1.1 |
| deployment | Vercel project (owner's), Git auto-deploy **on** | production deploys **crash**: `500 FUNCTION_INVOCATION_FAILED`, e.g. request `sin1::jndht-1790241414821-ac25ee0b7419` | Vercel dashboard → project → Logs → search the request id (expect `OSError … Read-only file system` from `database.init_db`) | fixed by the plan; optionally turn Git auto-deploy off in the dashboard now |
| database (hosted) | Neon via Vercel Marketplace | **unknown** whether installed yet | Vercel project → Storage / env vars (`DATABASE_URL` present?) | the owner sets up; the current code ignores `DATABASE_URL` |
| data | `data/app.db` | the owner's real DB (1 admin) | read-only queries only | **never register or reset it** (invariant 11) |
| artifact | scratchpad `venv312` (Python 3.12 uv venv) | disposable | — | delete any time |

## 5. In-flight changes (from OpenSpec)
| Change | Tasks | Status | Next ready artifact |
| --- | --- | --- | --- |
| `ci-cd-and-vercel-hosting` | 0/29 | in-progress (planning complete) | none; all four artifacts done, next is **apply** |

## 6. Open items
| Priority | Item | Doc/code reference | Next action | Done when |
| --- | --- | --- | --- | --- |
| P0 | Apply the CI/CD and hosting plan | `openspec/changes/ci-cd-and-vercel-hosting/tasks.md` | start Docker Desktop, then `/opsx:apply ci-cd-and-vercel-hosting` | 29/29 tasks; CI green; production `/healthz` → `database: ok` |
| P1 | Owner: verify `justin.yip@redalphacyber.com` on the `Justin-Red-Alpha` GitHub account | GitHub → Settings → Emails | add and verify the email | commits on GitHub show the work avatar |
| P1 | Owner: Vercel and Neon setup | design.md "Migration Plan" | enable Container Images; install Neon (Singapore, PG 17, preview branching off); set `CRON_SECRET` and `SCHEDULER_MODE=cron`; add GitHub secrets `VERCEL_TOKEN`, `VERCEL_ORG_ID`, `VERCEL_PROJECT_ID` | the deploy job stops skipping and production `/healthz` returns 200 |
| P2 | Confirm the 500's cause in Vercel runtime logs | §4 deployment row | search the request id in Vercel Logs | log shows the read-only-FS `OSError` (or record what it shows instead) |
| P2 | Re-clone any other copy of the repo | SHAs changed (§3) | delete and re-clone elsewhere | no clone holds the old history |
| P2 | Drop the local backup refs | §4 git refs row | the owner confirms, then the `update-ref -d` commands | the refs are gone |
| P2 | No password change / reset | `docs/auth/STATUS.md` | "change password" form | tested form |
| P2 | CSRF tokens before wider exposure | `docs/auth/STATUS.md` | per-form tokens | tested |
| on hold | Archived-history follow-ups (USD 88 check, BuyWhere) | `docs/history/STATUS.md` | resume when the owner says so | — |
| P3 | Broken `graphify` launcher | §3 graph row | `uv tool install --reinstall graphifyy`, then `graphify update .` | `graphify --help` runs from Git Bash |
| P3 | Carried items | `docs/STATUS.md`, `docs/suggestions.md` | — | — |

## 7. Architecture / model changes
- **Built and reconciled in `ef0594e`:**
  - `db.guarded_user_change` (atomic check-and-write);
  - `add_snapshot` rollback semantics;
  - `refresh._batch_lock` and `_record`;
  - `scheduler.refresh_all_now` and `REFRESH_JOB_ID`;
  - `site_settings`: `clean_*`/`save_*`, the `search_domains_off` object, `ignored_env`;
  - `history._paused` and `PAUSED_REASON`;
  - `templating.display_currency_for` (NULL = default, '' = as quoted).

  No coherence law changed.
- **Planned, not built** (see the change's design.md):
  - storage becomes a port with SQLite ⊕ Postgres adapters (`Backend`, `Row`,
    `write_transaction`, `translate`);
  - a new `delivery` component;
  - new `Loc` atoms: GitHub runner, Vercel instance, edge, cron, Neon pooler,
    Neon Postgres;
  - new `Trm` atoms: `t_ci`, `t_edge`, `t_cron`, `t_pg`;
  - `SCHEDULER_MODE = in-process ⊕ cron`.

## 8. Docs reconciled
| Doc | Change |
| --- | --- |
| `docs/STATUS.md` | In-flight column filled for storage, web, refresh, auth, settings. New "Hosting (2026-09-25)" note on the crashing Vercel deploys and why `/tmp` isn't a fix |
| docs for settings, auth, refresh, history, web, fx, storage (ARCHITECTURE / IMPLEMENTATION / STATUS) | review-fix rows, rules and tests (committed in `ef0594e`) |
| `README.md` | admin settings text, background "Refresh my prices", ignored env values (`ef0594e`) |
| `CLAUDE.md` | traps: failed SQLite write must roll back, check-then-act races, settings store only changes, `--reload` from a background shell (`ef0594e`) |
| memory | new `git-identity-work-vs-personal`; `MEMORY.md` index updated |

## 9. Drift check
`bash ~/.claude/skills/supercharge/scripts/drift-check.sh` → 0 dead / 441 refs.
Clean.

## 10. Files changed
- **Committed and pushed** (`ef0594e`):
  - code: `app/account.py`, `admin.py`, `auth.py`, `database.py`, `fx.py`,
    `history.py`, `main.py`, `refresh.py`, `scheduler.py`, `site_settings.py`,
    `templating.py`;
  - templates: `app/templates/admin.html`, `index.html`;
  - tests: `tests/test_auth.py`, `test_history.py`;
  - docs: `README.md`, `CLAUDE.md`, `docs/STATUS.md`, and the component docs.
- **Committed and pushed** (`0fca150`): `openspec/changes/ci-cd-and-vercel-hosting/`
  (7 files).
- **This end:** `docs/STATUS.md` and this log.
- **Outside the repo:** `~/.gitconfig` (the `includeIf` block), `~/.gitconfig-work`
  (new), and memory files.
