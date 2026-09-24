# Settings — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| numeric settings | key → (env, default, min, max) | `app/site_settings.py:_NUMBERS` | built |
| form labels | key → text | `app/site_settings.py:LABELS` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `effective` (numbers) | `Key → ℝ` | `app/site_settings.py:_number` | built |
| refresh interval | `() → hours` | `app/site_settings.py:refresh_interval_hours` | built |
| listings per shop | `() → ℕ` | `app/site_settings.py:discover_per_shop` | built |
| price lookups per search | `() → ℕ` | `app/site_settings.py:discover_price_limit` | built |
| set a number | `Key × 𝕊 → ℝ` (validated) | `app/site_settings.py:set_number` | built |
| default currency | `() → Currency?` | `app/site_settings.py:default_currency` | built |
| set default currency | `𝕊 → ()` (validated) | `app/site_settings.py:set_default_currency` | built |
| shops searched | `() → Domain*` | `app/site_settings.py:search_domains` | built |
| set shops searched | `Domain* → ()` (known shops only) | `app/site_settings.py:set_search_domains` | built |
| history pause | `() → 𝔹` | `app/site_settings.py:history_paused` | built |
| reschedule live | `hours → ()` | `app/scheduler.py:set_refresh_interval` | built |
| admin form (all or nothing) | `Form → ()` | `app/admin.py:save_settings` | built |
| maintenance: refresh all | `() → job` | `app/admin.py:refresh_everything_now` | built |
| maintenance: FX | `() → 𝔹` | `app/admin.py:refresh_fx` | built |
| maintenance: pause / resume | `𝔹 → ()` | `app/admin.py:pause_history` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. ranges and known shops | `app/site_settings.py:set_number` | `tests/test_auth.py:test_site_settings` |
| 2. all or nothing | `app/admin.py:save_settings` | `tests/test_auth.py:test_admin_page` |
| 3. applied live | `app/search/providers.py:search_domains` | `tests/test_auth.py:test_settings_apply_without_restart` |
| 4. pause honoured | `app/history.py:schedule_backfill` | `tests/test_auth.py:test_admin_page` |
