# System status

> Roll-up of every <component>/STATUS.md. Detail lives in the linked file. The
> **In flight** column comes from `openspec list --json` (as of 2026-09-25: one
> change, [`ci-cd-and-vercel-hosting`](../openspec/changes/ci-cd-and-vercel-hosting/proposal.md),
> being applied. The code and docs are done; it waits on the first CI run and
> the owner's Vercel setup).

| Component | State | Headline gap | In flight | Detail |
| --- | --- | --- | --- | --- |
| discovery | 🟡 partial | only Amazon and Lazada return results. eBay is blocked; Shopee/Qoo10 have no site search | — | [discovery/STATUS.md](discovery/STATUS.md) |
| extraction | ✅ built | Shopee API gets 403 | — | [extraction/STATUS.md](extraction/STATUS.md) |
| browser | ✅ built | ~7 s cold start on the first search after a restart | — | [browser/STATUS.md](browser/STATUS.md) |
| storage | ✅ built | the success ⊕ failure rule is held by convention | ci-cd-and-vercel-hosting (port built; Neon not yet exercised) | [storage/STATUS.md](storage/STATUS.md) |
| analysis | ✅ built | no historical FX rate | — | [analysis/STATUS.md](analysis/STATUS.md) |
| fx | ✅ built | — | — | [fx/STATUS.md](fx/STATUS.md) |
| web | ✅ built | no target edit form. SSE events not declared once | ci-cd-and-vercel-hosting (`/healthz`, `/cron/daily`, proxy: built) | [web/STATUS.md](web/STATUS.md) |
| refresh | ✅ built | rules 1 and 3 (every attempt recorded, quoted currency) untested | ci-cd-and-vercel-hosting (cron mode, daily run: built) | [refresh/STATUS.md](refresh/STATUS.md) |
| auth | ✅ built | no password change / reset; in-memory throttle | ci-cd-and-vercel-hosting (race guards on Postgres: built) | [auth/STATUS.md](auth/STATUS.md) |
| settings | ✅ built | — | ci-cd-and-vercel-hosting (fixed schedule: built) | [settings/STATUS.md](settings/STATUS.md) |
| history | 🟡 partial | Amazon only (9 prices live for the WH-1000XM5). Lazada/Shopee need BuyWhere. One suspicious USD 88 capture unchecked | ci-cd-and-vercel-hosting (deadline stop: built) | [history/STATUS.md](history/STATUS.md) |
| delivery | 🟡 built, not yet run | CI not yet run on GitHub; the first deploy waits on the owner's Vercel setup | ci-cd-and-vercel-hosting | [delivery/STATUS.md](delivery/STATUS.md) |

## Cross-cutting
- **Coherence:** Law 2 is advisory (untyped `t_sse` variants). All other laws
  PASS. See [architecture-map.md](architecture-map.md) §5.
- **Tests:** 7 offline suites: **573 checks on SQLite, 565 on Postgres** (the 8
  SQLite-only upgrade checks are skipped there), as of 2026-09-25. CI runs them on
  Ubuntu and Windows (SQLite) and against a Postgres 17 service. FX fetching has
  no tests (network only). `test_auth` and `test_hosting` block `requests`, so no
  test can reach the network by mistake.
- **Code review, 2026-09-24:** all 15 findings on the accounts/admin change
  fixed, each with a test. The concurrency ones run real threads and were checked
  against the pre-fix code (it let 40 of 40 parallel guesses through, and it ran
  two refresh batches at once).
- **External limits:** the Internet Archive blocks clients that ignore HTTP 429,
  for an hour and doubling on repeat. `history` stops on the first sign and
  pauses. Don't hand-probe web.archive.org in loops.
- **Hosting (2026-09-25):** the storage port, `Containerfile.vercel`,
  `vercel.json` (auto-deploy off, `sin1`, daily cron) and the CI workflow are
  built. Before this change, Vercel built each push as a plain Python function
  and it crashed at startup (`500 FUNCTION_INVOCATION_FAILED`, read-only
  filesystem). Vercel builds `Containerfile.vercel` only once the project's
  Container Images setting is on. Don't "fix" a crash by pointing SQLite at
  `/tmp`: the site is public, the database would reset on every scale-down, and
  the next visitor to register would become admin. It's a
  personal dev deployment; no launch is planned. The first deploy (`a237b69`,
  through Vercel's Git auto-deploy for one push) ran on Neon but as a plain
  Python function, so search had no Chromium. The container needs Container
  Images (Beta) access. The site sits behind Vercel Authentication. `vercel.json`
  is now committed ([delivery/STATUS.md](delivery/STATUS.md)).
- **Drift:** every `path:symbol` in the component maps resolves. Run
  `bash scripts/drift-check.sh` (CI runs it on every push).
