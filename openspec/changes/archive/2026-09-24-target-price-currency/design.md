# Design

## Context

See `proposal.md` for the motivation. Current state:

- `products.currency` is the product's **primary currency**. `refresh.py` sets it
  via `db.set_product_currency` from the first successful fetch that reports a
  currency. `compare_sources` and `best_price_series` use it to decide what gets
  ranked.
- `products.target_price` is a bare `REAL`. `main._product_view` assumes it is in
  the primary currency and converts it with `fx.convert` only when a display
  currency is selected. That logic is inline and untested.
- The per-source chart filtering is inline in `main.product_detail`, also untested.
- Convention (`CLAUDE.md`): analysis takes conversion as a **callable**, never an
  `fx` import, so its tests stay offline and deterministic.

Model delta, in FRAMEWORK terms:

| Kind | Item | Signature / meaning | Partiality |
| --- | --- | --- | --- |
| `Dat` | `products.target_currency` | ISO code or NULL. NULL means "the product's primary currency" | — |
| `Trn` | `analysis.target_in` | `(amount, currency, into, convert) → amount \| None` | None when any input is missing or no rate exists |
| `Trn` | `main._chart_points` | `(snapshots, display_currency, primary_currency, convert) → [(stamp, price)]` | drops points it cannot express in the chart's one currency |
| `Trn` | form handlers | accept `target_currency` from the form. `''` becomes NULL; a code in `fx.DISPLAY_CURRENCIES` is stored; anything else returns 400 | rejects unknown codes |

There are no new objects beyond one column, and no new `Loc` or `Trm`.

## Goals / Non-Goals

**Goals:**
- The target is always compared in the same currency as the history it is compared
  against (invariant 5), whatever currency it was entered in.
- The currency rules from `9a3fc71` are pinned by offline tests.

**Non-Goals:**
- Editing the target after the product is created. There is no edit form today, and
  adding one is a separate change.
- Historical FX rates. Conversion still uses today's rate, as documented.
- Changing how listings are ranked. The tests pin current behaviour; they don't
  alter it.

## Decisions

1. **Add a new `products.target_currency` column; don't reuse `products.currency`.**
   `currency` is the ranking pin written by refresh. If the target's currency were
   stored there, choosing "MYR" for a target would re-pin an SGD product to MYR and
   drop every SGD listing from as-quoted ranking. The two mean different things.
   *Discarded:* reusing `currency`.

2. **NULL means the legacy meaning, with no backfill.** Existing rows need no data
   migration, and a NULL is read exactly as the code reads targets today.
   *Discarded:* backfilling from `products.currency`. The primary currency is still
   NULL until a product's first fetch succeeds, so a backfill would miss those rows
   and add a second path to test.

3. **Use an additive migration, run after `SCHEMA`.** `init_db` does v1→v2 migration,
   then `SCHEMA`, then `ALTER TABLE products ADD COLUMN target_currency TEXT` if
   `PRAGMA table_info` doesn't list it. The ALTER must come after `SCHEMA`: on a v1
   database the rebuild creates `products` from `SCHEMA`, which now includes the
   column. `ADD COLUMN` does not rebuild the table, so the foreign-key cascade trap
   (invariant 8) cannot fire.

4. **Put the conversion in a pure `analysis.target_in(amount, currency, into, convert)`
   with an injected converter.** `main` passes `fx.convert`. `fx.convert` returns the
   amount unchanged for same-currency input without reading rates, so the as-quoted
   path still works offline exactly as before. Tests pass a fake.
   *Discarded:* keeping it inline in `_product_view`. It can't be tested without the
   database and it hides the partiality.

5. **The history currency is `display_currency or primary_currency`.** This is
   already `history_currency` in the view. The target is converted into it. The
   "(… for this view)" note on the product page is keyed off `history_currency`
   instead of `display_currency`, so an MYR target on an as-quoted SGD product
   shows its SGD equivalent.

6. **The dropdown lists "Shop's currency" (value `''`) plus `fx.DISPLAY_CURRENCIES`,
   and preselects `current_display_currency()`.** The user types the number in the
   currency they are looking at. The server checks the value against the same
   list; anything else returns 400 rather than being silently stored or dropped.
   The currency is stored only when a target amount is given.

7. **Extract the chart points into `main._chart_points(...)`.** This is the smallest
   change that makes the "chart never mixes currencies" rule testable. The
   rendered output is unchanged.

8. **Put the tests in a new suite, `tests/test_currency.py`.** It sits beside the two
   existing suites and uses the same `check`/`section` harness. It points
   `database.DB_PATH` at a temporary file, seeds `fx_rates` directly and never
   calls the network. A separate file keeps the database-touching tests out of the
   pure extraction suite.
   *Discarded:* appending to `test_extraction.py`. It would mix pure tests with
   tests that need a database fixture.

## Risks / Trade-offs

- **Risk:** someone points a test at the real `data/app.db`.
  **Mitigation:** the suite sets `DB_PATH` before any `init_db` call and asserts
  that the path is not the real one.
- **Risk:** conversion rounding flips a boundary verdict.
  **Mitigation:** both sides go through the same `round(…, 2)`, and a test pins the
  equal-price case across display currencies.
- **Trade-off:** a target in a foreign currency can only be applied once rates are
  cached. When they aren't, it is shown but not applied, with the existing warning.
  This is deliberate: guessing is worse.

## Migration Plan

On startup, `init_db` adds the column to existing databases, and it is safe to run
repeatedly. To roll back, revert the code. SQLite ignores the extra nullable
column, so no down-migration is needed.
