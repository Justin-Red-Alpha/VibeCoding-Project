# Auth — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| `User` | `users(id, username NOCASE UNIQUE, password_hash, role, display_currency, disabled_at, created_at)` | `app/database.py:create_user` | built |
| `Session` | `sessions(token_hash, user_id, created_at, expires_at)` | `app/database.py:add_session` | built |
| `owner?` | `products.user_id` | `app/database.py:get_products_for_user` | built |
| cookie | `session`, 14 days, HttpOnly, SameSite=Lax | `app/auth.py:set_session_cookie` | built |
| throttle state | username → failure times | `app/auth.py:_failures` | built |
| guesses in flight | username → count, under `_throttle_lock` | `app/auth.py:_in_flight` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| hash | `𝕊 → Hash` | `app/auth.py:hash_password` | built |
| verify | `𝕊 × Hash → 𝔹` | `app/auth.py:verify_password` | built |
| `register` | `Username × Password → User` | `app/auth.py:register` | built |
| `login?` | `Username × Password → User` | `app/auth.py:authenticate` | built |
| start session | `User → Token` | `app/auth.py:start_session` | built |
| `current_user?` | `Cookie → User` | `app/auth.py:current_user` | built |
| token → user | `Token → User?` | `app/auth.py:user_for_token` | built |
| sign out | `Token → ()` | `app/auth.py:end_session` | built |
| require sign-in | `Request → User` (else 303 to login) | `app/auth.py:require_user` | built |
| require admin | `Request → User` (else 403) | `app/auth.py:require_admin` | built |
| `authorize_product?` | `User × ProductId → Product` | `app/auth.py:product_for` | built |
| source ownership | `User × SourceId → Source` | `app/auth.py:source_for` | built |
| safe redirect | `𝕊 → Path` | `app/auth.py:local_path` | built |
| promote / demote | `UserId × Role → ()` | `app/auth.py:change_role` | built |
| disable / enable | `UserId × 𝔹 → ()` | `app/auth.py:set_disabled` | built |
| delete | `UserId → ()` (cascades) | `app/auth.py:delete_account` | built |
| guarded change (atomic) | `UserId × change → ()` | `app/database.py:guarded_user_change` | built |
| guard errors → message | `LastAdmin ∨ NoSuchUser → AuthError` | `app/auth.py:_guarded` | built |
| routes: register / login / logout | HTTP | `app/account.py:register` | built |
| route: personal currency | `POST /settings/currency` | `app/account.py:set_display_currency` | built |
| routes: admin users | `POST /admin/users/{id}/…` | `app/admin.py:set_role` | built |
| cross-site POST guard | `Request → 403?` | `app/main.py:SameSitePostGuard` | built |
| login redirect | `LoginRequired → 303` | `app/main.py:_to_login` | built |
| change own password | `User × Password → ()` | none | planned |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. first account is admin, claims unowned | `app/database.py:create_user` | `tests/test_auth.py:test_storage` |
| 2. at least one enabled admin | `app/database.py:guarded_user_change` | `tests/test_auth.py:test_last_admin_guard` |
| 2. …even when two admins race | `app/database.py:guarded_user_change` | `tests/test_auth.py:test_review_admins_cannot_both_demote` |
| 1. …even when first sign-ups race (both engines) | `app/database.py:write_transaction` | `tests/test_hosting.py:test_first_sign_up_race` |
| 3. salted scrypt only | `app/auth.py:hash_password` | `tests/test_auth.py:test_passwords` |
| 4. sessions hashed at rest; end on disable | `app/auth.py:start_session` | `tests/test_auth.py:test_sessions` |
| 5. one failure message; dummy hash | `app/auth.py:authenticate` | `tests/test_auth.py:test_sign_in_and_throttle` |
| 6. throttle | `app/auth.py:_recent_failures` | `tests/test_auth.py:test_sign_in_and_throttle` |
| 6. …parallel guesses counted | `app/auth.py:authenticate` | `tests/test_auth.py:test_review_parallel_guessing_is_capped` |
| 7. ownership on every product route | `app/auth.py:product_for` | `tests/test_auth.py:test_products_are_private` |
| 8. local redirects only | `app/auth.py:local_path` | `tests/test_auth.py:test_account_routes` |
| cross-site POST refused | `app/main.py:SameSitePostGuard` | `tests/test_auth.py:test_same_site_guard` |
| …compared with the forwarded host behind the proxy | `app/main.py:SameSitePostGuard` | `tests/test_hosting.py:test_forwarded_host` |
| cookie `Secure` over https | `app/auth.py:set_session_cookie` | `tests/test_hosting.py:test_secure_cookie_over_https` |
| admin page admins only | `app/auth.py:require_admin` | `tests/test_auth.py:test_admin_page` |

## Notes / divergences
- The throttle is **in memory**. It resets on restart, and per-worker if several
  workers ever run.
- No email means no password reset. An admin can delete an account so the person
  can re-register.
