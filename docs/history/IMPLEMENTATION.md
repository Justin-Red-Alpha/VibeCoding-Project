# History — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| `Observation` | `{price, currency?, observed_at, strategy, ref}` | `app/history.py:Observation` | built |
| `HistoryResult` | `kind ∈ {found, none, unavailable, unsupported}` + observations + reason | `app/history.py:HistoryResult` | built |
| source registry (port) | `lookup*` | `app/history.py:HISTORY_SOURCES` | built |
| politeness | 4 s gap; 15 / 60 min pauses | `app/history.py:REQUEST_GAP_S` | built |
| pause state | process-wide deadline | `app/history.py:_cooldown_until` | built |
| capture cap | 24 | `app/history.py:MAX_CAPTURES` | built |
| plausibility band | ×3 around the median | `app/history.py:PLAUSIBLE_FACTOR` | built |
| canonical URL rule | per shop | `app/adapters.py:canonical_path` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `archive_urls` | `Url × Adapter → Url*` | `app/history.py:archive_urls` | built |
| `lookup` (Wayback) | `Source × Adapter → HistoryResult` | `app/history.py:wayback_lookup` | built |
| `lookup` (BuyWhere) | `Source × Adapter → HistoryResult` | none yet: its API was unreachable on 2026-09-24 | planned |
| back off | `seconds → HistoryResult(unavailable)` | `app/history.py:_back_off` | built |
| `plausible? · same currency?` | `Observation* → kept, other, implausible` | `app/history.py:filter_observations` | built |
| outcome → note | `… → 𝕊` | `app/history.py:_found_note` | built |
| `backfill_source` | `Source → ()` | `app/history.py:backfill_source` | built |
| `backfill_product` | `Product → ()` | `app/history.py:backfill_product` | built |
| `schedule_backfill` | `Product → ()` | `app/history.py:schedule_backfill` | built |
| `read_capture?` | `Html × Url → PriceResult?` | `app/scraper.py:extract_from_html` | built |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. exact matching, same host | `app/history.py:archive_urls` | `tests/test_history.py:test_archive_urls` |
| 2. never render; JS shops unsupported | `app/history.py:wayback_lookup` | `tests/test_history.py:test_wayback_lookup` |
| 2. never a list price | `app/scraper.py:extract_from_html` | `tests/test_history.py:test_extract_from_html` |
| 3. never convert; foreign dropped | `app/history.py:filter_observations` | `tests/test_history.py:test_backfill_source` |
| 4. current price is live-only | `app/main.py:_latest_per_source` | `tests/test_history.py:test_current_price_is_live_only` |
| 5. idempotent | `app/database.py:get_origin_refs` | `tests/test_history.py:test_backfill_source` |
| 6. polite: gap, cap, stop, pause | `app/history.py:_back_off` | `tests/test_history.py:test_rate_limit_backoff` |
| 6. one job per product | `app/scheduler.py:run_once` | `tests/test_history.py:test_scheduling` |
| archived history drives the verdict | `app/analysis.py:best_price_series` | `tests/test_history.py:test_verdict_uses_archived_history` |

## Notes / divergences
- **Live, 2026-09-24:** the amazon.com WH-1000XM5 gave 9 archived USD prices
  (2025-05 → 2026-09) from 24 copies, in 134 s. One, **USD 88.00 (2025-12)**,
  looks like the wrong element: Amazon's first selector is the generic
  `.a-price .a-offscreen`. It couldn't be inspected because the archive then
  blocked this IP. See suggestions #1.
- The original "1 s apart" rule was wrong and caused that block. The 4 s gap and
  the stop-and-pause rules were added during apply.
