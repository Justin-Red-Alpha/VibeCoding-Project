# Refresh — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| politeness gap | `1.5 s` | `app/refresh.py:DELAY_BETWEEN_REQUESTS` | built |
| schedule interval | `REFRESH_INTERVAL_HOURS` env var, default 6 | `app/scheduler.py:REFRESH_INTERVAL_HOURS` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `refresh_source` | `Source → PriceSnapshot` | `app/refresh.py:refresh_source` | built |
| `refresh_product` | `Product → PriceSnapshot*` | `app/refresh.py:refresh_product` | built |
| `refresh_all` | `() → PriceSnapshot*` | `app/refresh.py:refresh_all` | built |
| `pin_currency?` | `PriceSnapshot → Product` | `app/database.py:set_product_currency` | built |
| schedule start | `() → ()` | `app/scheduler.py:start_scheduler` | built |
| schedule stop | `() → ()` | `app/scheduler.py:stop_scheduler` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. every attempt recorded | `app/refresh.py:refresh_source` | none (see note) |
| 2. sequential, 1.5 s apart | `app/refresh.py:refresh_product` | none |
| 3. quoted currency stored | `app/refresh.py:refresh_source` | none |
| 4. one bad source never aborts | `app/refresh.py:refresh_all` | none |

## Notes / divergences
- **No offline tests cover this component.** The `test_currency` form tests stub
  `refresh_product` out to avoid real fetches. Adding a test that stubs
  `fetch_price` and checks rules 1, 3 and 4 against a temp DB would be cheap.
