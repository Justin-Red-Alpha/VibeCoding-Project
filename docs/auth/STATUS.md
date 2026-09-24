# Auth — status

> Reconciles ARCHITECTURE.md (intent) against IMPLEMENTATION.md (code). Update it
> whenever code changes what is done (§6.5).

## Headline
✅ Built (2026-09-24). The gaps are password change and reset, and the throttle
being held in memory.

## Completeness
| Object / morphism | State | Notes |
| --- | --- | --- |
| register / sign in / sign out, two roles, first = admin | ✅ built | 171 checks in `tests/test_auth.py` |
| throttle and last-admin guard hold under parallel requests | ✅ built | fixed after the 2026-09-24 code review; tested with real threads |
| per-user products, admin sees all by link | ✅ built | 404 for another user's product |
| cross-site POST guard, local-only redirects | ✅ built | fixed the old open redirect in `/settings/currency` |
| admin: promote / demote / disable / delete, last-admin guard | ✅ built | |
| change own password | ⬜ unbuilt | a follow-up |
| password reset by email | ⬜ unbuilt | there's no mail server; an admin deletes and the person re-registers |

## Needs work
1. A "change password" form for signed-in users.
2. Before any exposure beyond localhost: per-form CSRF tokens, HTTPS (the cookie
   becomes `Secure` automatically on https), and a persistent throttle.

## Coherence
No law fails.

## Where to dig
- Model: ARCHITECTURE.md · Code map: IMPLEMENTATION.md
- Specs: `openspec/specs/user-accounts/`, `openspec/specs/access-control/`
