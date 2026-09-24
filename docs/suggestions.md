# Suggestions (roll-up)

> Highest payoff first, one line each, linking to the component detail. Applying
> one is a normal `work` cycle: an OpenSpec change, then build, test and
> reconcile. None are applied yet.

1. **Declare the SSE event types once**, so Law 2 goes from advisory to PASS:
   [web #1](web/suggestions.md)
1a. **Check the suspicious archived USD 88, then order Amazon's `#corePrice…`
   selectors first.** A generic first selector can read a carousel or used-offer
   price into history: [history #1](history/suggestions.md)
2. **Test refresh**, the sole writer of price history, which has no tests:
   [refresh #1](refresh/suggestions.md)
3. **Guard the browser seam** with a test that fails on any
   `playwright.sync_api` import in `app/`, so the `--reload` bug can't come back:
   [browser #1](browser/suggestions.md)
4. **Pass `convert` as a port everywhere in `web`.** The stream and summary
   become DB-free testable: [web #2](web/suggestions.md)
5. **Name `ShopOutcome`.** It's a 4-tuple unpacked positionally:
   [discovery #1](discovery/suggestions.md)
6. **Enforce success ⊕ failure in the schema** with a `CHECK` constraint (a
   rebuild, so invariant 8 applies): [storage #1](storage/suggestions.md)
7. **Move `_latest_per_source` into analysis**, so deduced views have one home:
   [analysis #1](analysis/suggestions.md)
8. **One converter port shape**, `convert` partially applied:
   [analysis #2](analysis/suggestions.md)
9. **Declare the extraction strategy order once:**
   [extraction #1](extraction/suggestions.md)
10. **YAGNI: `available_providers`** has one member. Build a keyed provider or
    remove it: [discovery #2](discovery/suggestions.md)
11. **Name `DISPLAY_CURRENCIES`' dual role** (picker and validation):
    [fx #1](fx/suggestions.md)

## System-wide reductions
- **`Candidate` vs `Source`** was checked with the §3 reduction and **rejected**.
  The functor isn't bijective on objects, and their lifetimes and `Loc`s differ.
  Revisit only if search results are ever persisted.
