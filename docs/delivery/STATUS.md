# Delivery — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
🟡 Built; one trial deploy so far (2026-09-25). For one push (`a237b69`) the
owner tried Vercel's Git auto-deploy. Vercel built it as a **plain Python
function, not the container** (no Container Images access yet), so the app ran
on Neon (the owner registered the admin) but search had no Chromium.
`vercel.json` is now committed, so deploys go through CI again. The workflow, the image and
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
| `daily_trigger` (`vercel.json` crons) | 🟡 written | Vercel registers it at the first deploy that includes `vercel.json` (that is, via CI) |
| gate on production (rule 1) | ✅ in force | `vercel.json` committed. Until `VERCEL_TOKEN` exists nothing deploys, and production stays on `a237b69` |
| storage on Neon | ✅ works | the `a237b69` deploy started, created the schema, and took the admin sign-up |
| container on Vercel (rule 10) | ❌ not yet | needs the team's Container Images (Beta) access; the first deploy used the Python runtime |
| Deployment Protection (rule 11) | ✅ on | Vercel Authentication. The health check needs `VERCEL_AUTOMATION_BYPASS_SECRET` |
| owner setup (Container Images, Neon, `CRON_SECRET`, `SCHEDULER_MODE=cron`, secrets) | 🟡 in progress | Neon installed and work email verified (2026-09-25). The rest is listed in the README |

## Needs work
0. Get the container built by Vercel. Check that the team has Container Images
   (Beta) access and that the project's Framework Preset isn't forcing Python.
   The build log should show the image being built, not `pip install`.
1. Push, and confirm every job goes green with the deploy skipped and its notice
   visible (tasks 4.3 and 4.4).
2. Owner setup, then the first deploy. Confirm production `/healthz` returns
   `database: ok`, sign-in sets a `Secure` cookie, and Vercel's forwarded-host
   behaviour matches CLAUDE.md (task 6.3).
3. Image size is settled: Vercel's registry allows 2 GB per compressed layer and
   15 GB per image, and ours is ~353 MB compressed.
4. Check the first cron run in Vercel → Settings → Cron Jobs → View Logs. The docs
   don't say whether Vercel Authentication lets cron calls through.

## Coherence
No law fails on paper. Law 6 is explicit: `build_image` has two placements.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- In flight: `openspec/changes/ci-cd-and-vercel-hosting/`
- Specs (after archive): `openspec/specs/delivery-pipeline/`, `openspec/specs/hosted-site/`
