# History — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. None are applied; this is a
> backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | Invariant 7 spirit (§6.6 the doc is the spec) | archived Amazon pages are read with the generic `.a-price .a-offscreen` first, and a likely wrong USD 88.00 survived the ⅓-median band | once verified, order Amazon's selectors `#corePrice…` first (this benefits live checks too), and consider a tighter band for archived-only points | history can't be skewed by a carousel or used-offer price |
| 2 | §5 deduce | `history_note` is a stored summary of rows that can be recounted | acceptable: it also records outcomes with **no** rows (none, unavailable, unsupported), which can't be deduced. Keep it | — |
| 3 | UI provenance | archived points look the same as live ones on the chart | a hollow point style for `origin?` rows (needs `origin` in `_chart_points`) | provenance visible where people read the trend |
