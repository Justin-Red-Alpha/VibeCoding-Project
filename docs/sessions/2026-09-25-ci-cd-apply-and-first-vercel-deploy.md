# 2026-09-25 — CI/CD apply and first Vercel deploy

Follows `2026-09-25-review-fixes-and-hosting-plan.md`.

## 0. Continuation brief
Current state:
- **Change `ci-cd-and-vercel-hosting`: 26/29 applied and pushed** (`a237b69`,
  `9bbb15b`).
- **Built:**
  - the storage port (SQLite ⊕ Postgres);
  - the outage page and `/healthz`;
  - `SCHEDULER_MODE=cron` and `/cron/daily`;
  - the forwarded-host guard;
  - `Dockerfile.vercel`;
  - the CI workflow;
  - `vercel.json`;
  - a new suite, `tests/test_hosting.py`;
  - all docs.
- **Local result:** 573 checks on SQLite and 565 on Postgres, all green.
- **Production is up** on Neon from the `a237b69` deploy. It's behind Vercel
  Authentication, and the owner has registered the admin.
- **But Vercel built the plain Python runtime, not the container,** so shop search
  fails with "Could not start Chromium … Executable doesn't exist".
- **Git auto-deploy is now off** (`vercel.json`, `9bbb15b`), so production stays
  on `a237b69` until CI deploys, which needs the owner's GitHub secrets.
- The owner was about to restart VS Code so `gh` is on PATH, then
  `gh auth login`.

Next step:
1. With `gh` signed in, check the CI runs for `a237b69` and `9bbb15b`. That
   verifies tasks 4.3 and 4.4.
2. The owner is testing Vercel's Framework Preset: "Python", then "Other" if
   that doesn't work. They redeploy from the dashboard (Deployments → ⋯ →
   Redeploy), since auto-deploy is off. Then check whether the build log shows a
   container build.

Resume command/check:
```bash
gh auth status && gh run list --limit 5 && gh run view <run-id> --log-failed
```
(If `gh` isn't on PATH: `"/c/Program Files/GitHub CLI/gh.exe"`.)

## 1. Work completed
- **Applied the plan** through the OpenSpec apply flow, tasks 1.1–6.2. Details
  are in the change's `design.md` under "Implementation notes".
  - **Storage:**
    - `app/database.py` is one port with two adapters (`_SqliteConn`,
      `_PgConn`, pooled by `psycopg_pool`);
    - `schema(dialect)` with `{pk}`/`{username}` tokens, `DOUBLE PRECISION`
      money and `CITEXT` usernames;
    - `RETURNING` ids and `, id` tie-breakers;
    - `write_transaction` (SQLite `BEGIN IMMEDIATE`; Postgres takes the
      advisory lock first, under pinned READ COMMITTED);
    - `_translate` to `IntegrityError`/`DatabaseUnavailable`, with redacted logs;
    - `ping`, `close_pool`, and a schema lock on concurrent `init_db`.
  - **Web:**
    - the `DatabaseUnavailable` → 503 page (standalone `unavailable.html`);
    - `/healthz`;
    - `/cron/daily` (Bearer `CRON_SECRET` compared in constant time, 404 when
      unset);
    - `SameSitePostGuard` compares against `x-forwarded-host`.
  - **Refresh:**
    - `scheduler.mode()`;
    - `daily_run` (refresh until 150 s, history sweep until 230 s);
    - `refresh.stalest_first` / `refresh_stalest`;
    - `db.get_sources_stalest_first` (`NULLS FIRST`).
  - **History:** a `stop` hook, `CUT_SHORT_REASON` (records nothing, so the next
    run resumes), and `cooling_down`.
  - **Settings:** the admin page shows "once a day, set by the host" in cron mode,
    and ignores a posted interval.
  - **Tests:**
    - `tests/helpers.py` handles both engines (`TEST_DATABASE_URL`, refuses
      non-local hosts, closes the pool after a reset);
    - `test_auth`, `test_currency`, `test_history` and `test_shop_search` moved
      onto it;
    - new suite `tests/test_hosting.py` (87 checks).
  - **Delivery:**
    - `Dockerfile.vercel` (headless shell only, non-root, `--proxy-headers`);
    - `.dockerignore`;
    - `requirements.txt` pins (playwright 1.63.0, psycopg[binary] 3.3.6,
      psycopg-pool 3.3.3);
    - `requirements-dev.txt` (httpx);
    - `.github/workflows/ci.yml` (test ×2 OS, postgres, container, gated
      deploy, health check with an optional protection bypass);
    - `scripts/drift-check.sh` (vendored);
    - `vercel.json`.
- **Docs:**
  - a new `docs/delivery/` component (ARCHITECTURE, IMPLEMENTATION, STATUS,
    suggestions, `reviews/review-ci-cd-and-vercel-hosting.md`);
  - storage, refresh, web, auth, settings and history docs reconciled;
  - `architecture-map.md`, root `IMPLEMENTATION.md` and `STATUS.md` updated;
  - README (badge, Docker, Postgres tests, the Vercel setup and table);
  - CLAUDE.md (a Hosted mode section, invariants 3 and 11 extended, 10 new
    traps).
- **graphify fixed.** It's upgraded to 0.9.67. A new `~/bin/graphify` bash
  wrapper presets `PYTHONHASHSEED=0`, so `update` stops re-running itself and
  returning early on Windows.
- **Tools installed:** GitHub CLI 2.101.0 (winget), `actionlint.exe` (scratchpad
  only), Docker Desktop started.

## 2. Decisions
| Decision | Verdict | Why |
| --- | --- | --- |
| Hosted-mode tests as a seventh suite (`test_hosting`) | kept | the plan said six; a separate suite reads better and CI shows it as its own step |
| Install `requirements-dev.txt` in the image | kept | `tests/` ships in it, and `test_shop_search` needs `TestClient`/httpx |
| Chromium headless shell only | kept | `headless=True` launches it; smaller image |
| History `stop` → `CUT_SHORT_REASON`, record nothing | kept | recording it the way a pause is recorded would mark the listing checked for good (the spec's "resumed" scenario) |
| Closing the pool after a test `DROP SCHEMA` | kept | stale prepared statements pin the dropped `citext` type |
| Owner trial: commit without `vercel.json` (Git auto-deploy on) | done for one push (`a237b69`), then ended | owner's call. It proved Neon works and exposed the Python-runtime build |
| Commit `vercel.json` (gate, cron, `sin1`) | done (`9bbb15b`) | owner: "fine to push vercel.json" |
| Health check sends `x-vercel-protection-bypass` if `VERCEL_AUTOMATION_BYPASS_SECRET` is set; a 3xx counts as protected | kept | the site is behind Vercel Authentication, and every URL 302s to `vercel.com/sso-api` |
| Password change/reset, CSRF tokens | stay on the to-do list, low priority | owner: dev mode, no launch planned (in memory) |

## 3. Tests, checks, benchmarks
| Check | Result | What it proved |
| --- | --- | --- |
| Seven suites, SQLite | 63+48+89+32+83+171+87 = **573**, all exit 0 | nothing regressed |
| Seven suites, Postgres 17.11 (`TEST_DATABASE_URL=…localhost:5433/test`) | 63+48+83+32+83+171+85 = **565** | the port works on Postgres. 8 SQLite-only upgrade checks are skipped |
| Fresh venv from both requirements files | 573 | the requirements are complete |
| Race test on Postgres with the lock removed / REPEATABLE READ / real code | 2–4 admins / 3–4 admins / exactly 1 in 10 of 10 | the test catches both regressions; lock-first plus READ COMMITTED is needed |
| Copy of the real `data/app.db` through the new `init_db` | schema and row digest identical | an existing local DB opens unchanged |
| `docker build -f Dockerfile.vercel` | 1.32 GB unpacked, ~353 MB compressed | fits Vercel Container Registry (2 GB per layer, 15 GB per image) |
| Image smoke: SQLite and Postgres, cron mode | `/healthz` 200, `/login` 200, `/cron/daily` 401 → 200, Chromium renders in the image, `Secure` cookie with `X-Forwarded-Proto: https` | the image works on both engines |
| actionlint 1.7.12 on `ci.yml` | clean | the workflow is well-formed |
| `vercel.json` against Vercel's JSON schema | no errors | the config is valid |
| Drift check | 0 dead / 562 refs | docs match the code |
| `openspec validate --strict` | valid | |
| First Vercel deploy (`a237b69`, Git auto-deploy) | app up, Neon schema created, admin registered; search: "Executable doesn't exist at /home/sbx_user…/ms-playwright/…" | Neon works; Vercel built the Python runtime, not the container |

## 4. Live handoff state
| Type | Handle / location | State | Inspect / resume | Stop / cleanup |
| --- | --- | --- | --- | --- |
| branch | `main` | clean, in sync with `origin/main` at `9bbb15b` (plus this log's commit) | `git status -sb` | none |
| CI | GitHub Actions runs for `a237b69`, `9bbb15b` | **unknown** (still running at last look; repo is private) | `gh run list --limit 5` | — |
| deployment | Vercel project (team red-alpha), production = `a237b69`, Python runtime | up; search has no Chromium; behind Vercel Authentication | owner, in the dashboard; `https://vibe-coding-project-red-alpha.vercel.app` (302 to sign-in for curl) | — |
| Vercel settings | Framework Preset | owner changing FastAPI → Python (→ Other if needed) | Deployments → latest → Build Logs | — |
| database (hosted) | Neon, via the Marketplace | has the schema and the owner's admin account | — | **never** point tests at it |
| container | `pt-pg` (postgres:17, port 5433) | running, test data only | `docker ps` | `docker rm -f pt-pg` |
| image | `price-tracker:dev` | built locally | `docker image ls price-tracker` | `docker rmi price-tracker:dev` |
| service | Docker Desktop | running | `docker info` | quit it when done |
| tool | GitHub CLI 2.101.0 | installed, **not signed in**; not on PATH in terminals opened before the install | `gh auth status` | — |
| tool | `~/bin/graphify` wrapper | active in Git Bash | `command -v graphify` | delete it if upstream stops using `os.execvpe` |
| git refs (local) | `refs/backup/pre-author-rewrite`, `refs/original/...` | still kept | `git for-each-ref refs/backup refs/original` | the owner decides |

## 5. In-flight changes (from OpenSpec)
| Change | Tasks | Status | Open tasks |
| --- | --- | --- | --- |
| `ci-cd-and-vercel-hosting` | 26/29 | in-progress | 4.3 (CI green, deploy skipped with its notice), 4.4 (drift line in the CI log), 6.3 (owner setup plus verified production deploy) |

## 6. Open items
| Priority | Item | Next action | Done when |
| --- | --- | --- | --- |
| P0 | Container not built by Vercel | owner: Framework Preset → Python/Other, then Redeploy; check Container Images (Beta) access for the red-alpha team | build log shows an image build; search renders on production |
| P0 | Tasks 4.3 and 4.4 | `gh auth login`, then `gh run list` / `gh run view --log` | all four jobs green (deploy skipped with its notice); `0 dead` in the log |
| P1 | Owner secrets | GitHub: `VERCEL_TOKEN`, `VERCEL_ORG_ID` (red-alpha Team ID), `VERCEL_PROJECT_ID`, optionally `VERCEL_AUTOMATION_BYPASS_SECRET`. Vercel: `SCHEDULER_MODE=cron`, `CRON_SECRET` | re-running CI deploys; `verify_prod` green |
| P1 | Does Vercel Cron get through Vercel Authentication? | after the first 18:00 UTC run: Settings → Cron Jobs → View Logs | 200 from `/cron/daily` (or a decision if it's 302) |
| P1 | Which header Vercel fills (`host` vs `x-forwarded-host`) | check on the first container deploy | recorded in CLAUDE.md |
| P2 | Archive the change | after 6.3: `/opsx:archive ci-cd-and-vercel-hosting` | specs merged into `openspec/specs/` |
| P2 | Password change/reset, CSRF tokens | on hold (dev mode) | — |
| P3 | Report graphify's `os.execvpe` early exit upstream | if the owner wants | — |
| P3 | Delivery suggestions (pin the base image by digest, a shared throttle, preview branches, one `run_all`) | backlog | — |

## 7. Architecture / model changes
- New component **delivery**:
  - `Loc`: GitHubRunner, CiPostgres, VercelBuild, VercelInstance, VercelEdge,
    VercelCron, NeonPooler, NeonPostgres;
  - `Trm`: `t_ci`, `t_ci_pg`, `t_deploy`, `t_edge`, `t_cron`, `t_pg`;
  - rules 1–11 (the gate; skip without credentials; the test-database guard;
    one recipe; secrets; the Container Images permission; Deployment
    Protection).
- **storage** becomes a port with two adapters (rules 7–12). **refresh** adds
  rules 6–9 (cron mode, budget, resumability). **web** adds rules 9–11. **history**
  adds rule 8. **settings** adds rule 5. **auth**'s guards now go through
  `write_transaction`.
- **Coherence:** all six laws pass (see
  `docs/delivery/reviews/review-ci-cd-and-vercel-hosting.md`).

## 8. Docs reconciled
- `docs/{storage,refresh,web,auth,settings,history}/{ARCHITECTURE,IMPLEMENTATION,STATUS}.md`
- `docs/delivery/*` (new)
- `docs/architecture-map.md`, `docs/IMPLEMENTATION.md`, `docs/STATUS.md`
- README, CLAUDE.md
- the change's `design.md` (image size, implementation notes, trial findings)
  and `tasks.md`
- memory:
  - `vibecoding-env-quirks` (graphify fix);
  - `price-tracker-project` (dev mode, no launch);
  - `git-identity-work-vs-personal` (work email verified).

**Oddity:** before `a237b69`, the trial notes in design.md and the two delivery
docs were undone by something outside the session's edits (probably an editor
buffer). They were rewritten from the files as found.

## 9. Drift check
`bash scripts/drift-check.sh` → 0 dead / 562 refs.

## 10. Files changed
- **`a237b69`** (50 files): everything in §1 except `vercel.json`.
- **`9bbb15b`:** `vercel.json`, the `ci.yml` bypass, and the trial-findings
  docs.
- **This end:** this log.
- **Outside the repo:** `~/bin/graphify` (new) and the memory files.
