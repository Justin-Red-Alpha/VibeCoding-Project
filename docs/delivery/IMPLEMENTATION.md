# Delivery — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).
> Bare file names (`Containerfile.vercel`, `vercel.json`) are cited in prose because
> the drift check skips references without a directory.

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| `Image` | `Containerfile.vercel`: python:3.14-slim-bookworm, Chromium headless shell, non-root `app`, `CMD uvicorn … --proxy-headers` | `Containerfile.vercel` (bare name) | built |
| build context | excludes `.venv`, `data/`, `docs/`, `openspec/`, `.claude/`, `.codex/`, `graphify-out/`, `.env` | `.dockerignore` (bare name) | built |
| host config | no Git auto-deploy, region `sin1`, daily cron | `vercel.json` (bare name) | built |
| runtime deps (pinned) | playwright 1.63.0, psycopg[binary] 3.3.6, psycopg-pool 3.3.3 | `requirements.txt` (bare name) | built |
| test deps | httpx (TestClient) | `requirements-dev.txt` (bare name) | built |
| `DeployCredentials?` | three repository secrets | `.github/workflows/ci.yml:VERCEL_TOKEN` | built (secrets: owner) |
| production URL for the check | optional repository variable | `.github/workflows/ci.yml:PRODUCTION_URL` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `ci_test` | `Commit × OS → CheckResult` | `.github/workflows/ci.yml:test` | built |
| `ci_postgres` | `Commit → CheckResult` | `.github/workflows/ci.yml:postgres` | built |
| test database: local throwaway only | `URL → ()` (raises) | `tests/helpers.py:check_test_database_url` | built |
| reset on either engine | `() → ()` | `tests/helpers.py:reset_db` | built |
| `drift_check` | `Docs × Code → CheckResult` | `scripts/drift-check.sh:VENDORED` | built |
| `build_image` + `smoke` | `Commit → Image → CheckResult` | `.github/workflows/ci.yml:container` | built |
| `deploy?` (gated, skips without credentials) | `Commit → Deployment` | `.github/workflows/ci.yml:deploy` | built |
| `verify_prod` | `Deployment → HealthReport` | `.github/workflows/ci.yml:healthz` | built |
| `daily_trigger` → the route | `CronCall → Report` | `app/main.py:cron_daily` | built |
| `HealthReport` | `() → {app, database}` | `app/main.py:healthz` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. the gate (`needs`, `if: push to main`) | `.github/workflows/ci.yml:needs` | the first push to `main` (see STATUS) |
| 1. no Git auto-deploy | `vercel.json` (`git.deploymentEnabled: false`) | Vercel JSON schema check (task 4.5) |
| 2. skipped with a notice without credentials | `.github/workflows/ci.yml:Deploy` | the first push to `main` |
| 3. tests never touch the hosted database | `tests/helpers.py:check_test_database_url` | `tests/test_hosting.py:test_test_database_guard` |
| 4. one recipe; no data or secrets in the image | `.dockerignore`, `Containerfile.vercel` | local `docker run … ls` (2026-09-25) and the `container` job |
| 4. forwarded headers trusted (Secure cookie) | `Containerfile.vercel` (`--proxy-headers`) | local: `X-Forwarded-Proto: https` → `Secure` (2026-09-25) |
| 5. secrets never logged | `app/database.py:_redact` | `tests/test_hosting.py:test_healthz` |
| 6. one step per suite | `.github/workflows/ci.yml:test_hosting` | actionlint 1.7.12 (clean) |
| 7. drift check in CI | `.github/workflows/ci.yml:drift` | the first push to `main` |
| 8. daily cron, bounded run | `app/scheduler.py:daily_run` | `tests/test_hosting.py:test_daily_run_budget` |

## Notes / divergences
- **Seven suites, not six.** The plan said six. The hosted-mode checks got their
  own suite, `tests/test_hosting.py`, so CI runs seven steps per job.
- **`requirements-dev.txt` is installed in the image** (httpx only), because
  `tests/` ships in it for the smoke test's in-image `test_shop_search`.
- **Chromium's headless shell only** (`playwright install --only-shell`):
  `headless=True` launches it, and it keeps the image at 1.32 GB unpacked
  (~353 MB compressed, measured 2026-09-25).
- `verify_prod` uses the deployment's own URL unless the repository variable
  `PRODUCTION_URL` is set. If Vercel's deployment protection answers 401/403 on
  the generated URL, the job says to set it.
