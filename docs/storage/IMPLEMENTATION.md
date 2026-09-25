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
| `User` | `users(...)` (see auth) | `app/database.py:get_user_by_name` | built |
| `Session` | `sessions(token_hash, user_id, expires_at)` | `app/database.py:get_session` | built |
| `owner?` | `products.user_id → users.id` (ON DELETE CASCADE) | `app/database.py:delete_user` | built |
| `Backend` | `DATABASE_URL` set → postgres, else sqlite at `DB_PATH` | `app/database.py:backend` | built |
| `DATABASE_URL` | env, read at import (tests reassign it) | `app/database.py:DATABASE_URL` | built |
| `Row` (Postgres) | name, index, `keys()`, `dict(row)` | `app/database.py:Row` | built |
| dialect tokens | `{pk}`, `{username}` per engine | `app/database.py:_DIALECT` | built |
| advisory lock keys | user guard, schema | `app/database.py:USER_GUARD_LOCK`, `app/database.py:SCHEMA_LOCK` | built |
| pool wait before "unavailable" | 10 s | `app/database.py:POOL_TIMEOUT_S` | built |
| error types | `IntegrityError`, `DatabaseUnavailable` | `app/database.py:IntegrityError`, `app/database.py:DatabaseUnavailable` | built |

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
| `add_snapshot` | `row → ()` (rolls back and closes on a refused insert) | `app/database.py:add_snapshot` | built |
| latest snapshot | `Source → PriceSnapshot?` | `app/database.py:get_latest_snapshot` | built |
| `origin?`, `origin_ref?` | `PriceSnapshot → {wayback}`, `→ Url` | `app/database.py:origin_ref` | built |
| archived refs per listing | `Source → Url*` | `app/database.py:get_origin_refs` | built |
| `history_checked_at?`, `history_note?` | `Source → Date / 𝕊` | `app/database.py:set_history_note` | built |
| `display_currency?` | `Setting → Currency` | `app/database.py:get_setting` | built |
| set setting | `key × value? → ()` | `app/database.py:set_setting` | built |
| `rate` cache write | `FxRate* → ()` | `app/database.py:save_fx_rates` | built |
| `rate` cache read | `base → FxRate*` | `app/database.py:get_fx_rates` | built |
| `fx_fetched_at` | `base → Date?` | `app/database.py:get_fx_fetched_at` | built |
| `connect` (the port) | `Backend → Conn` | `app/database.py:get_connection` | built |
| SQLite adapter (raises `db.IntegrityError`) | `Conn` | `app/database.py:_SqliteConn` | built |
| Postgres adapter (pooled; `?` → `%s`) | `Conn` | `app/database.py:_PgConn` | built |
| placeholder rewrite | `SQL → SQL` | `app/database.py:_pg_sql` | built |
| Postgres pool (lazy, ≤ 4, checked on checkout, READ COMMITTED) | `() → Pool` | `app/database.py:_pg_pool` | built |
| pin READ COMMITTED | `Connection → ()` | `app/database.py:_configure_pg` | built |
| close the pool (shutdown, exit, tests) | `() → ()` | `app/database.py:close_pool` | built |
| `schema` | `Dialect → SQL` | `app/database.py:schema` | built |
| `write_transaction` | `Conn → ctx` | `app/database.py:write_transaction` | built |
| `translate` | `DriverError → IntegrityError ⊕ DatabaseUnavailable` | `app/database.py:_translate` | built |
| never log the URL | `𝕊 → 𝕊` | `app/database.py:_redact` | built |
| `ping` | `() → ()` | `app/database.py:ping` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. success ⊕ failure snapshot | `app/refresh.py:refresh_source` | `tests/test_extraction.py:test_comparison` |
| 2. never store a converted price | `app/refresh.py:refresh_source` | `tests/test_extraction.py:test_conversion_comparison` |
| 3. `currency?` write-once | `app/database.py:set_product_currency` | `tests/test_currency.py:test_target_in_view` |
| 4. rebuild with both pragmas | `app/database.py:_migrate_single_url_schema` | `tests/test_currency.py:test_upgrade_adds_target_currency` |
| 5. migrate → schema → columns | `app/database.py:init_db` | `tests/test_currency.py:test_upgrade_adds_target_currency` |
| target currency round-trips | `app/database.py:add_product` | `tests/test_currency.py:test_target_currency_round_trip` |
| 6. archived rows: history, never current | `app/main.py:_latest_per_source` | `tests/test_history.py:test_current_price_is_live_only` |
| provenance columns added to old DBs | `app/database.py:_add_missing_columns` | `tests/test_history.py:test_storage` |
| 7. one port: rows read the same | `app/database.py:get_connection` | `tests/test_hosting.py:test_rows_read_like_sqlite` |
| 8. money keeps every digit | `app/database.py:SCHEMA` | `tests/test_hosting.py:test_money_keeps_every_digit` |
| 8. `RETURNING` ids; id tie-breakers | `app/database.py:add_product` | `tests/test_hosting.py:test_ids_and_ties` |
| 8. usernames ignore case (NOCASE / CITEXT) | `app/database.py:_DIALECT` | `tests/test_hosting.py:test_usernames_ignore_case` |
| 9. lock-first write transaction | `app/database.py:write_transaction` | `tests/test_hosting.py:test_first_sign_up_race` |
| 10. driver errors translated; nothing left locked | `app/database.py:_translate` | `tests/test_hosting.py:test_driver_errors_are_translated` |
| 11. outage → 503, never empty | `app/main.py:_database_unavailable` | `tests/test_hosting.py:test_outage_is_not_empty_data` |
| 12. concurrent cold starts | `app/database.py:init_db` | `tests/test_hosting.py:test_init_db_on_concurrent_cold_starts` |
| an existing SQLite file opens unchanged | `app/database.py:init_db` | `tests/test_hosting.py:test_existing_sqlite_database_unchanged` |
| tests never erase a non-local database | `tests/helpers.py:check_test_database_url` | `tests/test_hosting.py:test_test_database_guard` |

## Notes / divergences
- Rule 1 is enforced by the writers, not by a table `CHECK`. Since 2026-09-24
  there are two: `refresh_source` (live) and `history.backfill_source` (archived,
  success rows only). Storage suggestions #1 (a `CHECK` constraint) is now more
  relevant.
- Nothing tests `set_product_currency` directly. Its write-once behaviour is only
  exercised through the view tests.
- Every suite runs on both engines: SQLite by default, Postgres with
  `TEST_DATABASE_URL` (the CI `postgres` job). The SQLite upgrade tests print
  "skipped" on Postgres, which always starts from the current schema.
- Timestamps stay ISO-8601 text on both engines (a design non-goal). Byte order
  and Postgres's collation agree for this format, and the suites pass under the
  `postgres:17` image's `en_US.utf8`.
