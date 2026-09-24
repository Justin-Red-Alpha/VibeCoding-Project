# Analysis — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. None are applied; this is a
> backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | §4.2 ownership of deduced views | `_latest_per_source` (latest snapshot per source) is a deduced view of snapshots, but it lives in `web` | move it next to `compare_sources` | every deduced price view has one home, and it can be tested without routes |
| 2 | §5 one source of truth | two converter shapes: `to_display(amount, from)` and `convert(amount, from, to)` | define `to_display` as `convert` partially applied at the call site, and accept one port type | one port contract instead of two |

Swept and clean:
- **§5 deduce-don't-store:** nothing is stored.
- **§3:** `SourcePrice` is a view (Source × latest snapshot + deduced fields), not
  a parallel entity.
