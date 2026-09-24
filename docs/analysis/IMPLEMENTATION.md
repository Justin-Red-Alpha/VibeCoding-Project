# Analysis — implementation map

> The functor ARCHITECTURE.md → code. Keep it in sync **with** the code (§6.3).

## Objects (Dat) → code
| Object | Form / shape | Realised at | State |
| --- | --- | --- | --- |
| `SourcePrice` | dataclass (deduced view) | `app/analysis.py:SourcePrice` | built |
| `Comparison` | dataclass (deduced view) | `app/analysis.py:Comparison` | built |
| `Verdict` | `{label, reason, stats}` | `app/analysis.py:Verdict` | built |

## Morphisms (Trn / relations) → code
| Morphism | Signature | Realising code | State |
| --- | --- | --- | --- |
| `compare_sources` | `… → Comparison` | `app/analysis.py:compare_sources` | built |
| `comparable_price?` | `SourcePrice → ℝ` | `app/analysis.py:SourcePrice::comparable_price` | built |
| `ranking_eligible` | `SourcePrice → 𝔹` | `app/analysis.py:ranking_eligible` | built |
| `currency_unknown` | `SourcePrice → 𝔹` | `app/analysis.py:currency_unknown` | built |
| `off_currency` | `SourcePrice → 𝔹` | `app/analysis.py:off_currency` | built |
| `savings?` | `Comparison → ℝ` | `app/analysis.py:Comparison::savings` | built |
| `savings_pct?` | `Comparison → ℝ` | `app/analysis.py:Comparison::savings_pct` | built |
| comparison currency | `Comparison → Currency?` | `app/analysis.py:Comparison::comparison_currency` | built |
| converted? | `Comparison → 𝔹` | `app/analysis.py:Comparison::converted` | built |
| `best_price_series` | `… → ℝ*` | `app/analysis.py:best_price_series` | built |
| `analyze` | `ℝ* × ℝ? → Verdict` | `app/analysis.py:analyze` | built |
| percentile | `ℝ × ℝ* → ℝ` | `app/analysis.py:_percentile_rank` | built |
| `target_in?` | `… → ℝ?` | `app/analysis.py:target_in` | built |
| `dominant_currency?` | `PriceSnapshot* → Currency` | `app/analysis.py:dominant_currency` | built |
| per-snapshot historical rate | `PriceSnapshot → Rate` | none | planned |

## Composition rules → where enforced
| Rule (ARCHITECTURE §6) | Enforced at | Tested at |
| --- | --- | --- |
| 1. never rank across currencies | `app/analysis.py:compare_sources` | `tests/test_currency.py:test_as_quoted_ranks_only_primary_currency` |
| 1. unknown currency never ranked | `app/analysis.py:compare_sources` | `tests/test_currency.py:test_unknown_currency_never_ranked` |
| 1. no rate ⇒ never cheapest | `app/analysis.py:compare_sources` | `tests/test_extraction.py:test_conversion_without_rates` |
| 1. mixed and unpinned ⇒ no cheapest | `app/analysis.py:compare_sources` | `tests/test_currency.py:test_inferred_comparison_currency` |
| 1. series drops uncomparable prices | `app/analysis.py:best_price_series` | `tests/test_currency.py:test_series_excludes_uncomparable` |
| 2. target in the history's currency | `app/analysis.py:target_in` | `tests/test_currency.py:test_target_in` |
| 2. display currency never moves the verdict | `app/main.py:_product_view` | `tests/test_currency.py:test_display_currency_does_not_move_verdict` |
| verdict precedence | `app/analysis.py:analyze` | `tests/test_extraction.py:test_verdicts` |
| 4. conversion as a port | `app/analysis.py:compare_sources` | `tests/test_extraction.py:test_conversion_comparison` |

## Notes / divergences
- Rule 5 (today's rate for old snapshots) is a documented limit, not a bug. The
  historical-rate row stays `planned`.
