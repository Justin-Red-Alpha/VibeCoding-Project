# Settings — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| numeric settings | key → (env, default, min, max, whole?) | `app/site_settings.py:_NUMBERS` | built |
| form labels | key → text | `app/site_settings.py:LABELS` | built |
| shops switched off | `settings.search_domains_off` (comma list) | `app/site_settings.py:_switched_off` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `effective` (numbers) | `Key → ℝ` | `app/site_settings.py:_number` | built |
| validate a number | `Key × 𝕊 → ℝ?` | `app/site_settings.py:_parse_number` | built |
| `ignored_env` | `() → 𝕊*` | `app/site_settings.py:ignored_env` | built |
| refresh interval | `() → hours` | `app/site_settings.py:refresh_interval_hours` | built |
| listings per shop | `() → ℕ` | `app/site_settings.py:discover_per_shop` | built |
| price lookups per search | `() → ℕ` | `app/site_settings.py:discover_price_limit` | built |
| clean a number | `Key × 𝕊 → ℝ` (raises) | `app/site_settings.py:clean_number` | built |
| show a number exactly | `ℝ → 𝕊` | `app/site_settings.py:format_number` | built |
| store a number if changed | `Key × ℝ → ()` | `app/site_settings.py:save_number` | built |
| default currency | `() → Currency?` | `app/site_settings.py:default_currency` | built |
| clean a currency | `𝕊 → Currency?` (raises) | `app/site_settings.py:clean_currency` | built |
| store default currency if changed | `Currency? → ()` | `app/site_settings.py:save_default_currency` | built |
| shops that could be searched | `() → Domain*` | `app/site_settings.py:available_shops` | built |
| shops searched | `() → Domain*` | `app/site_settings.py:search_domains` | built |
| clean shop choice | `𝕊* → Domain*` (exact, non-empty) | `app/site_settings.py:clean_search_domains` | built |
| store shop choice | `Domain* → ()` (as the off-list) | `app/site_settings.py:save_search_domains` | built |
| history pause | `() → 𝔹` | `app/site_settings.py:history_paused` | built |
| set history pause | `𝔹 → ()` | `app/site_settings.py:set_history_paused` | built |
| reschedule live (if changed) | `hours → ()` | `app/scheduler.py:set_refresh_interval` | built |
| admin form (clean all, then write) | `Form → ()` | `app/admin.py:save_settings` | built |
| maintenance: refresh all | `() → job` | `app/admin.py:refresh_everything_now` | built |
| maintenance: FX | `() → 𝔹` | `app/admin.py:refresh_fx` | built |
| maintenance: pause / resume | `𝔹 → ()` | `app/admin.py:pause_history` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. ranges; exact shop match | `app/site_settings.py:clean_search_domains` | `tests/test_auth.py:test_site_settings` |
| 1. injected domain refused via the form | `app/admin.py:save_settings` | `tests/test_auth.py:test_review_settings_never_freeze_config` |
| 2. clean first; only changes stored | `app/site_settings.py:save_number` | `tests/test_auth.py:test_review_settings_never_freeze_config` |
| 2. numbers shown exactly | `app/site_settings.py:format_number` | `tests/test_auth.py:test_review_admin_numbers_render_exactly` |
| bad env values reported | `app/site_settings.py:ignored_env` | `tests/test_auth.py:test_review_ignored_env_is_reported` |
| 3. applied live; reschedule only on change | `app/scheduler.py:set_refresh_interval` | `tests/test_auth.py:test_settings_apply_without_restart` |
| 4. pause honoured at the source | `app/history.py:schedule_backfill` | `tests/test_auth.py:test_settings_apply_without_restart` |
| 4. pause honoured mid-run | `app/history.py:backfill_product` | `tests/test_history.py:test_admin_pause_stops_running_lookups` |
