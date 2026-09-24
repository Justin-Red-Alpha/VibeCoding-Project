# Refresh — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| politeness gap | `1.5 s` | `app/refresh.py:DELAY_BETWEEN_REQUESTS` | built |
| batch turn-taking | one process-wide lock | `app/refresh.py:_batch_lock` | built |
| schedule interval | admin setting (1–168 h), else `REFRESH_INTERVAL_HOURS` env, else 6 | `app/site_settings.py:refresh_interval_hours` | built |
| the scheduled job | id `refresh_all_products`, `max_instances=1` | `app/scheduler.py:REFRESH_JOB_ID` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `refresh_source` | `Source → PriceSnapshot` | `app/refresh.py:refresh_source` | built |
| store, tolerating a deleted source | `Source × Snapshot → 𝔹` | `app/refresh.py:_record` | built |
| sequential, gapped, fault-isolated | `Source* → PriceSnapshot*` | `app/refresh.py:_refresh_sources_politely` | built |
| `refresh_product` | `Product → PriceSnapshot*` | `app/refresh.py:refresh_product` | built |
| one user's products (batch) | `ProductId* → PriceSnapshot*` | `app/refresh.py:refresh_products` | built |
| `refresh_all` (batch) | `() → PriceSnapshot*` | `app/refresh.py:refresh_all` | built |
| `pin_currency?` | `PriceSnapshot → Product` | `app/database.py:set_product_currency` | built |
| schedule start | `() → ()` | `app/scheduler.py:start_scheduler` | built |
| schedule stop | `() → ()` | `app/scheduler.py:stop_scheduler` | built |
| apply a new interval live | `hours → ()` | `app/scheduler.py:set_refresh_interval` | built |
| run the scheduled job now | `() → ()` | `app/scheduler.py:refresh_all_now` | built |
| one-off job (history, "refresh my prices") | `id × fn × args → ()` | `app/scheduler.py:run_once` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. every attempt recorded | `app/refresh.py:refresh_source` | none (see note) |
| 2. sequential, 1.5 s apart | `app/refresh.py:_refresh_sources_politely` | none |
| 2. batches take turns | `app/refresh.py:_batch_lock` | `tests/test_auth.py:test_review_refreshes_take_turns` |
| 2. admin refresh reuses the scheduled job | `app/scheduler.py:refresh_all_now` | `tests/test_auth.py:test_review_refreshes_take_turns` |
| 3. quoted currency stored | `app/refresh.py:refresh_source` | none |
| 4. one bad source never aborts | `app/refresh.py:_refresh_sources_politely` | `tests/test_auth.py:test_review_refreshes_take_turns` |
| 4. deleted mid-fetch is skipped | `app/refresh.py:_record` | `tests/test_auth.py:test_review_refreshes_take_turns` |
| 5. web requests never wait on a batch | `app/main.py:refresh_mine` | `tests/test_auth.py:test_products_are_private` |

## Notes / divergences
- Rules 1 and 3 still have no direct offline test. The `test_currency` form tests
  stub `refresh_product` out to avoid real fetches. A test that stubs
  `fetch_price` and checks the stored snapshot's currency and error would be cheap.
