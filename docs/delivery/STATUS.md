# Delivery — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
🟡 Built, not yet run where it lives (2026-09-25). The workflow, the image and
`vercel.json` exist and are checked locally: all seven suites pass on SQLite and
on a local Postgres 17, the image builds and passes its smoke test on both
engines, actionlint is clean, and `vercel.json` passes Vercel's schema. Still to
happen: the first GitHub Actions run, then the owner's Vercel setup and the first
production deploy.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| `ci_test` (Ubuntu + Windows), `ci_postgres`, `drift_check` | 🟡 written | green locally; the first CI run is pending a push |
| `build_image`, `smoke` | ✅ built | local Docker 29.7.2: `/healthz` 200 (SQLite and Postgres), `/login` 200, Chromium renders in the image |
| `deploy?` gate, skip-with-notice | 🟡 written | skips until `VERCEL_TOKEN` exists |
| `verify_prod` | 🟡 written | needs the first deploy |
| `daily_trigger` (`vercel.json` crons) | 🟡 written | Vercel reads it at the first deploy |
| owner setup (Container Images, Neon, `CRON_SECRET`, `SCHEDULER_MODE=cron`, secrets) | 🟡 in progress | Neon installed and work email verified (2026-09-25). The rest is listed in the README |

## Needs work
1. Push, and confirm every job goes green with the deploy skipped and its notice
   visible (tasks 4.3 and 4.4).
2. Owner setup, then the first deploy. Confirm production `/healthz` returns
   `database: ok`, sign-in sets a `Secure` cookie, and Vercel's forwarded-host
   behaviour matches CLAUDE.md (task 6.3).
3. Confirm Vercel accepts a 1.32 GB image. If not, the fallback is a remote
   browser behind `browser.chromium` (an owner decision, per design.md).

## Coherence
No law fails on paper. Law 6 is explicit: `build_image` has two placements.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- In flight: `openspec/changes/ci-cd-and-vercel-hosting/`
- Specs (after archive): `openspec/specs/delivery-pipeline/`, `openspec/specs/hosted-site/`
