# FX — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| base currency | `"USD"` | `app/fx.py:BASE` | built |
| rate sources | ordered `(name, url, key)*` | `app/fx.py:RATE_SOURCES` | built |
| offered currencies | `Currency*` (also validates targets) | `app/fx.py:DISPLAY_CURRENCIES` | built |
| staleness bound | `12 h` | `app/fx.py:MAX_AGE_HOURS` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `convert?` | `ℝ? × Currency? × Currency? → ℝ` | `app/fx.py:convert` | built |
| `make_converter?` | `Currency? → ToDisplay` | `app/fx.py:make_converter` | built |
| `refresh_rates?` | `() → 𝔹` | `app/fx.py:refresh_rates` | built |
| force a fetch (admin) | `() → 𝔹` (true only if new rates saved) | `app/fx.py:fetch_fresh_rates` | built |
| fetch (sources in order) | `() → Rates?` | `app/fx.py:_fetch_rates` | built |
| `rates_age_hours?` | `() → ℝ` | `app/fx.py:rates_age_hours` | built |
| `available` | `() → 𝔹` | `app/fx.py:available` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. never on write | `app/refresh.py:refresh_source` | `tests/test_extraction.py:test_conversion_comparison` |
| 2. same currency needs no rates | `app/fx.py:convert` | `tests/test_currency.py:test_target_in_view` |
| 3. sources in order | `app/fx.py:_fetch_rates` | none (network) |
| admin FX button reports failure honestly | `app/admin.py:refresh_fx` | `tests/test_auth.py:test_admin_page` |

## Notes / divergences
- `_fetch_rates` has no offline test, because it only does network I/O. The tests
  seed `fx_rates` directly, or replace `_fetch_rates` with a stub. `test_auth`
  also blocks `requests` outright, so a test that forgets to stub fails loudly
  rather than quietly reaching the network.
- The admin button used to say "rates refreshed" whenever *any* rates existed,
  even when the fetch had just failed. Now it reports "failed, still using the
  cached rates from N h ago", or "failed, no rates at all".
