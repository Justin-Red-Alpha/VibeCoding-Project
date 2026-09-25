# Settings — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built (2026-09-24). Everything that used to be an environment variable or a
module constant is now an admin setting, and applies without a restart.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| default currency, shops, refresh interval, discovery limits | ✅ built | env vars remain as fallbacks |
| pause / resume archive lookups | ✅ built | the "data on hold" switch |
| refresh-all and FX maintenance actions | ✅ built | refresh-all runs the scheduled job early; FX reports a failed fetch |
| saves write only changes; invalid form writes nothing; bad env values listed | ✅ built | after the 2026-09-24 code review |
| host-fixed schedule (`SCHEDULER_MODE=cron`) shown, interval ignored | ✅ built | 2026-09-25, `tests/test_hosting.py:test_admin_schedule_display` |

## Needs work
None.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- Spec: `openspec/specs/site-administration/`
