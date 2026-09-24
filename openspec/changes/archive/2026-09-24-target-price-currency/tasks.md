# Tasks

## 1. Pin current behaviour first

- [x] 1.1 Create `tests/test_currency.py` with the `check`/`section` harness and a temp-DB fixture (`database.DB_PATH` → temp file, asserted ≠ `data/app.db`); verify `python -m tests.test_currency` runs and exits 0 with an empty test list
- [x] 1.2 Add `currency-comparison` tests against the current code: unknown currency never ranked (with and without display currency), off-currency excluded as-quoted, no-rate listing never cheapest, inferred single shared currency, mixed currencies with no pin → no cheapest, nothing-converted → `converted` False; best-price series drops unknown/foreign/unconvertible snapshots; verify all pass on unmodified code

## 2. Data

- [x] 2.1 Add `target_currency TEXT` to `SCHEMA` and an idempotent `ADD COLUMN` step in `init_db` after `SCHEMA`; verify with a test that builds a pre-change `products` table with a row, runs `init_db` twice, and finds the column present and the row intact
- [x] 2.2 Add a `target_currency` parameter to `db.add_product`; verify a test round-trips `MYR` and `None`

## 3. Analysis and view

- [x] 3.1 Add `analysis.target_in(amount, currency, into, convert)`; verify tests for same currency (identity), converted, no rate → None, unknown currency → None, no amount → None
- [x] 3.2 Rewire `main._product_view` to use `product["target_currency"] or primary currency` and `target_in(..., history_currency, fx.convert)`; verify view tests: MYR 800 target vs SGD 300 → not BUY_NOW; MYR 1000 → BUY_NOW; legacy NULL target applied in primary currency; no rates + foreign target → `target_not_applied`; verdict label identical across display None / MYR / USD for single-currency listings; stored target unchanged after switching display currency
- [x] 3.3 Extract `main._chart_points(snapshots, display_currency, primary_currency, convert)` from `product_detail`; verify tests: foreign snapshot dropped as-quoted, converted with display currency, unknown/no-rate dropped

## 4. Forms and templates

- [x] 4.1 Add `target_currency` form field to `POST /products` and `POST /discover/track`, validated against `fx.DISPLAY_CURRENCIES` (400 otherwise), stored only when a target amount is given; verify TestClient tests: `XYZ` → 400 and no product created (no network: rejection happens before any fetch)
- [x] 4.2 Add the currency `<select>` beside the target input in `index.html` and `discover.html`, preselecting `current_display_currency()`, and replace the "first listing" hint; verify by rendering both pages with display currency MYR and none and checking the selected option
- [x] 4.3 Update `product.html` so the target shows in its own currency and the "(… for this view)" note keys off `history_currency`; verify the product page renders for an MYR target on an SGD product showing both figures

## 5. Reconcile

- [x] 5.1 Update `CLAUDE.md` invariant 5 and Running section, and `README.md` §5, to describe the target currency; verify by reading them against the specs
- [x] 5.2 Run all three suites (`test_extraction`, `test_search`, `test_currency`) with `PYTHONIOENCODING=utf-8`; verify all pass
- [x] 5.3 Restart the dev server and check the dropdown and a product page in the browser; verify no template errors — done: dropdown checked live at 390px and 1100px on both forms (a phone overflow was found and fixed); product page checked by the rendering test only, since the real DB has no tracked products and adding one would scrape live shops
- [x] 5.4 Run the supercharge drift check; record the result (no `docs/` tree yet — expected "nothing to check") — result: `0 dead / 0 refs` (exit 0)
