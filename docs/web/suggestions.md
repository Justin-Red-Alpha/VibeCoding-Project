# Web — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. None are applied; this is a
> backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | §5 define each boundary once / Law 2 | the `SseEvent` variants (`shop`, `price`, `note`, `error`, `done`) are built as ad-hoc dicts in 6+ places and parsed by hand in `discover.html` | one declaration (TypedDicts or dataclasses) that `_sse` accepts, plus a test that every variant the JS handles is declared | Python and JS can't drift. It turns Law 2 from advisory to PASS |
| 2 | §4.4 ports | `_discovery_summary`, `_candidate_row` and the price-lookup loop in `discover_stream` call `fx.convert` directly, while `_chart_points` and `target_in` take it as a port | pass the converter in the same way | the stream and summary become testable without a database |
| 3 | §4.2 ownership | `_latest_per_source` is a deduced snapshot view that lives here | move it to `analysis` (analysis suggestion #1) | one home for deduced price views |
