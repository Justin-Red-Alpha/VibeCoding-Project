# Proposal

## Why

A target price is typed as a bare number and silently assumed to be in the
product's primary currency (the first shop that returned one). A user viewing
prices in MYR who types "800" meaning ringgit gets it read as SGD 800. That can
produce a false `BUY NOW`, which is the one kind of lie this app exists to avoid.
The currency handling added in commit `9a3fc71` has no tests either. Its rules
decide which listing is shown as the deal, so a regression would pass unnoticed.

## What Changes

- The target price field on both forms (add-by-URL on the dashboard, "Track these"
  on discovery) gets a currency dropdown. It defaults to the current display
  currency, or to "Shop's currency" when prices are shown as quoted.
- The chosen currency is stored with the product next to the target amount. The
  target amount is never rewritten or converted in storage.
- When the verdict is computed, the target is converted into the currency of the
  price history (the display currency if one is selected, otherwise the product's
  primary currency). If no rate exists, the target is shown but not applied, as
  it is today.
- Products tracked before this change have no stored target currency. They keep
  the current meaning: the target is in the product's primary currency.
- An unrecognised currency code submitted with a target is rejected. Nothing is
  tracked.
- New offline test suite `tests/test_currency.py`. It pins the currency rules from
  `9a3fc71` and the new target behaviour: unknown-currency listings are never
  ranked, off-currency listings are excluded, targets convert, and the chart never
  mixes currencies.

## Capabilities

### New Capabilities
- `target-price`: the user's buy-at-or-below target, including its currency and how it feeds the BUY/WAIT verdict.
- `currency-comparison`: which listings are ranked, charted and counted in price history when they are priced in different or unknown currencies.

### Modified Capabilities
- none (no specs exist yet)

## Impact

- **Schema:** adds the nullable column `products.target_currency`. It's an additive
  `ALTER TABLE ... ADD COLUMN`, with no table rebuild and no foreign-key cascade
  risk. Existing rows read as NULL, which keeps the old meaning.
- **Code:** `app/database.py`, `app/analysis.py` (new pure target conversion),
  `app/main.py` (two form handlers, `_product_view`, chart-point extraction),
  `app/templates/index.html`, `app/templates/discover.html`,
  `app/templates/product.html`.
- **Tests:** new `tests/test_currency.py`. It runs offline against a throwaway
  SQLite file and never touches `data/app.db`.
- **Docs:** `CLAUDE.md` invariant 5 and the Running section, and `README.md` §5.
- **No new dependencies. No network access in tests.**
