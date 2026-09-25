# Web — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| `ProductView` | dict built per request | `app/main.py:_product_view` | built |
| `SseEvent` | `data: {json}` frames | `app/main.py:_sse` | built |
| `CandidateRow` | dict per listing | `app/main.py:_candidate_row` | built |
| target field | amount + currency `<select>` | `app/templates/_target_price_field.html:target_currency` | built |
| headline threshold | `0.45` | `app/main.py:MIN_HEADLINE_SCORE` | built |
| lookup concurrency | `3` | `app/main.py:PRICE_LOOKUP_CONCURRENCY` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `product_view` | `Product → ProductView` | `app/main.py:_product_view` | built |
| latest per source | `PriceSnapshot* → Latest` | `app/main.py:_latest_per_source` | built |
| `chart_points` | `… → ChartPoint*` | `app/main.py:_chart_points` | built |
| `discover_stream` | `Query → SseEvent*` | `app/main.py:discover_stream` | built |
| `last = done` | `Candidate* → Summary` | `app/main.py:_discovery_summary` | built |
| `target_currency?` | `Form → Currency` | `app/main.py:_target_currency` | built |
| display currency | `() → Currency?` | `app/main.py:display_currency` | built |
| a user's choice (NULL = site default, '' = as quoted) | `User? → Currency?` | `app/templating.py:display_currency_for` | built |
| route: dashboard | `GET /` | `app/main.py:dashboard` | built |
| route: product page | `GET /product/{id}` | `app/main.py:product_detail` | built |
| route: discover page | `GET /discover` | `app/main.py:discover_page` | built |
| route: track | `POST /discover/track` | `app/main.py:track_from_discovery` | built |
| route: add product | `POST /products` | `app/main.py:create_product` | built |
| route: add source | `POST /products/{id}/sources` | `app/main.py:create_source` | built |
| route: set display currency | `POST /settings/currency` | `app/account.py:set_display_currency` | built |
| route: refresh one | `POST /products/{id}/refresh` | `app/main.py:refresh_one` | built |
| route: look for archived prices | `POST /products/{id}/history` | `app/main.py:lookup_history` | built |
| history note per listing | `Source → 𝕊` | `app/templates/product.html:history_by_source` | built |
| archived row marker + link | `PriceSnapshot → HTML` | `app/templates/product.html:origin_ref` | built |
| route: refresh my prices | `POST /refresh` (own products; queued in the background, one job per user) | `app/main.py:refresh_mine` | built |
| "refreshing" notice | `?refreshing=1 → HTML` | `app/main.py:dashboard` | built |
| startup | FX + scheduler (shutdown also closes the Postgres pool) | `app/main.py:lifespan` | built |
| outage → 503 page | `DatabaseUnavailable → Response` | `app/main.py:_database_unavailable` | built |
| outage page (no user lookup) | standalone template | `app/main.py:_bare_templates` | built |
| route: health check | `GET /healthz` | `app/main.py:healthz` | built |
| route: the host's daily run | `GET /cron/daily` | `app/main.py:cron_daily` | built |
| public host behind the proxy | `Request → Host` | `app/main.py:SameSitePostGuard` | built |
| JS: render a row | `row → <tr>` | `app/templates/discover.html:makeRow` | built |
| JS: paint a price | `row → cell` | `app/templates/discover.html:paintPrice` | built |
| JS: terminal states | `sections → terminal` | `app/templates/discover.html:stopPending` | built |
| target shown both ways | `ProductView → HTML` | `app/templates/product.html:target_display_price` | built |
| edit target after creation | `Product → Product` | none | planned |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. headline only from plausible listings | `app/main.py:_discovery_summary` | `tests/test_search.py:test_headline_price_ignores_poor_matches` |
| 1. suspect price never headlines | `app/main.py:_discovery_summary` | `tests/test_search.py:test_headline_ignores_suspect_price_despite_good_title` |
| 3. no stuck spinner | `app/templates/discover.html:stopPending` | `tests/test_shop_search.py:test_page_never_leaves_shops_spinning` |
| 4. one currency per chart line | `app/main.py:_chart_points` | `tests/test_currency.py:test_chart_points` |
| 5. ≤3 concurrent lookups, streamed | `app/main.py:discover_stream` | `tests/test_shop_search.py:test_price_lookups_run_concurrently` |
| browser failure becomes an error event | `app/main.py:discover_stream` | `tests/test_shop_search.py:test_browser_failure_becomes_error_event` |
| 6. target currency validated | `app/main.py:_target_currency` | `tests/test_currency.py:test_forms_store_target_currency` |
| 6. picker defaults to display currency | `app/templates/_target_price_field.html:display_pref` | `tests/test_currency.py:test_forms_default_to_display_currency` |
| target shown as entered and as compared | `app/templates/product.html:target_display_price` | `tests/test_currency.py:test_product_page_shows_both_figures` |
| 8. current price is live-only | `app/main.py:_latest_per_source` | `tests/test_history.py:test_current_price_is_live_only` |
| tracking schedules an archive lookup | `app/main.py:lookup_history` | `tests/test_history.py:test_routes_schedule_lookups` |
| provenance shown on the page | `app/templates/product.html:history_by_source` | `tests/test_history.py:test_product_page_shows_provenance` |
| "As quoted" overrides the site default | `app/templating.py:display_currency_for` | `tests/test_auth.py:test_review_as_quoted_beats_site_default` |
| 9. outage is a 503, never empty | `app/main.py:_database_unavailable` | `tests/test_hosting.py:test_outage_is_not_empty_data` |
| 10. health check reveals nothing | `app/main.py:healthz` | `tests/test_hosting.py:test_healthz` |
| 11. cron: secret or nothing | `app/main.py:cron_daily` | `tests/test_hosting.py:test_cron_endpoint` |
| guard uses the forwarded host | `app/main.py:SameSitePostGuard` | `tests/test_hosting.py:test_forwarded_host` |

## Notes / divergences
- Rule 2 (the JS is a dumb renderer) is a convention with no automated check.
- Rule 7 (chart colours) is enforced in `product_detail`'s `color_index` and is
  untested.
- `SseEvent` has no single declaration. See ARCHITECTURE §9 and the suggestions.
