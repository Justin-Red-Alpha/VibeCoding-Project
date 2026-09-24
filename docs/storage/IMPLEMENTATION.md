# Storage — implementation map

> The functor ARCHITECTURE.md → code. Each object and morphism maps to the
> file:symbol that realises it. Keep it in sync **with** the code (§6.3): a new
> morphism gets a row here in the same change that adds its code.

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| `Product` | `products(id, name, target_price, target_currency, currency, created_at)` | `app/database.py:SCHEMA` | built |
| `Source` | `sources(id, product_id, retailer, url, price_selector, created_at)` | `app/database.py:SCHEMA` | built |
| `PriceSnapshot` | `price_snapshots(id, source_id, price, currency, strategy, fetched_at, error)` | `app/database.py:SCHEMA` | built |
| `Setting` | `settings(key, value)` | `app/database.py:SCHEMA` | built |
| `FxRate` | `fx_rates(base, quote, rate, fetched_at)` | `app/database.py:SCHEMA` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `src_product` | `Source → Product` | `app/database.py:get_sources` | built |
| `snap_source` | `PriceSnapshot → Source` | `app/database.py:get_snapshots_for_product` | built |
| `target_currency?` | `Product → Currency` | `app/database.py:target_currency` | built |
| `currency?` (write-once) | `Product → Currency` | `app/database.py:set_product_currency` | built |
| `init_db` | migrate → schema → columns | `app/database.py:init_db` | built |
| v1 → v2 migration functor | `Product(v1) → Product × Source` | `app/database.py:_migrate_single_url_schema` | built |
| additive columns | extend `Product` | `app/database.py:_add_missing_columns` | built |
| `add_product` | `row → id` | `app/database.py:add_product` | built |
| `add_source` | `row → id` | `app/database.py:add_source` | built |
| `add_snapshot` | `row → ()` | `app/database.py:add_snapshot` | built |
| latest snapshot | `Source → PriceSnapshot?` | `app/database.py:get_latest_snapshot` | built |
| `display_currency?` | `Setting → Currency` | `app/database.py:get_setting` | built |
| set setting | `key × value? → ()` | `app/database.py:set_setting` | built |
| `rate` cache write | `FxRate* → ()` | `app/database.py:save_fx_rates` | built |
| `rate` cache read | `base → FxRate*` | `app/database.py:get_fx_rates` | built |
| `fx_fetched_at` | `base → Date?` | `app/database.py:get_fx_fetched_at` | built |
| connection per call | `() → Connection` | `app/database.py:get_connection` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. success ⊕ failure snapshot | `app/refresh.py:refresh_source` | `tests/test_extraction.py:test_comparison` |
| 2. never store a converted price | `app/refresh.py:refresh_source` | `tests/test_extraction.py:test_conversion_comparison` |
| 3. `currency?` write-once | `app/database.py:set_product_currency` | `tests/test_currency.py:test_target_in_view` |
| 4. rebuild with both pragmas | `app/database.py:_migrate_single_url_schema` | `tests/test_currency.py:test_upgrade_adds_target_currency` |
| 5. migrate → schema → columns | `app/database.py:init_db` | `tests/test_currency.py:test_upgrade_adds_target_currency` |
| target currency round-trips | `app/database.py:add_product` | `tests/test_currency.py:test_target_currency_round_trip` |

## Notes / divergences
- Rule 1 is enforced by the only writer, `refresh_source`, not by a table `CHECK`.
  A future second writer must keep it.
- Nothing tests `set_product_currency` directly. Its write-once behaviour is only
  exercised through the view tests.
