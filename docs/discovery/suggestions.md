# Discovery — suggestions (category-theory derived)

> Deduced from ARCHITECTURE.md by FRAMEWORK rules. None are applied; this is a
> backlog.

| # | Rule (§) | Smell found | Proposed change | Payoff |
| --- | --- | --- | --- | --- |
| 1 | §2 name every object | `ShopOutcome` is an anonymous 4-tuple unpacked positionally in `web` | a small `NamedTuple ShopOutcome(domain, retailer, candidates, error)` | the boundary type is named once and can't be mis-ordered |
| 2 | §5 YAGNI | `available_providers` suggests a provider registry with one member | remove it until a second provider exists, or build the keyed provider | no abstraction pretending to be scaffolding |
| 3 | §3 consolidation (considered) | `Candidate` and `storage.Source` share `url` and `retailer` | **Rejected for now.** They have different lifetimes and `Loc`s (transient RAM vs durable row), and only `url` crosses on confirm. Revisit if candidates are ever persisted | — |

## Detail
### 3. Candidate vs Source (§3 reduction, abbreviated)
Step 1: `Candidate` has title, url, retailer, provider, price?, score and flags;
`Source` has url, retailer, price_selector? and product. Step 2/3: the squares for
`url` and `retailer` commute. Step 5: title, score, flags and provider have no
partner, and product has no partner either. A functor would need to be bijective
on objects, and it isn't: a `Candidate` exists for every search hit, a `Source`
only for confirmed ones. That makes them different objects joined by a partial
`confirm` morphism, not twins.
