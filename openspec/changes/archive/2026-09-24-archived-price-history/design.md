# Design

## Context

See `proposal.md` for the motivation. Here is what was measured, and what the
code does today.

- **Wayback CDX** (`https://web.archive.org/cdx/search/cdx`) lists captures of a
  URL. `collapse=timestamp:6` gives one per month. With
  `filter=statuscode:200&output=json&fl=timestamp,original` it returns a header
  row plus `[timestamp, original]` rows. For the WH-1000XM5, the amazon.com slug
  URL had 53 monthly captures (2022-05 → 2026-09), the `/dp/ASIN` form had 37,
  and amazon.sg had 1.
- **Raw capture:** `https://web.archive.org/web/<ts>id_/<original>`. The `id_`
  flag returns the archived bytes without the Wayback toolbar or rewriting.
  `scraper._extract` on those bytes gave `USD 196.23` (2024-07) and `USD 149.95`
  (2026-09) via `amazon-css`. The 2022 capture had no readable price. Each fetch
  took about 2.5 s.
- **Snapshots:** today every row in `price_snapshots` is a live fetch.
  `main._latest_per_source` takes each source's newest successful row as its
  current price. `best_price_series` buckets all rows hourly.
- **Scheduler:** an APScheduler `BackgroundScheduler` (`scheduler._scheduler`)
  runs `refresh_all` every 6 h. It isn't started in tests, because tests never
  run `lifespan`.
- **BuyWhere** (the planned second source) was unreachable on 2026-09-24: search
  returned `degraded`, and key registration timed out at both 30 s and 90 s.

### Model delta (FRAMEWORK terms)

**§3 consolidation check: is an archived price a new object?** Write out
`ArchivedPrice`'s morphisms: `source → Source`, `price → ℝ`,
`currency → Currency`, `observed_at → Date`. Those are exactly
`PriceSnapshot`'s, and every square commutes. The one morphism with no partner is
provenance (*where* it was observed). So an archived price is a `PriceSnapshot`
with a partial `origin?`. Don't create a `history_points` table. Extend the
existing object.

| Kind | Item | Signature | Partiality | Semantics |
| --- | --- | --- | --- | --- |
| `Dat` | `origin?` | `PriceSnapshot → {wayback}` | Partial | NULL = live check. The discriminator of §3 |
| `Dat` | `origin_ref?` | `PriceSnapshot → Url` | Partial | the capture URL. Provenance and dedup key |
| `Dat` | `fetched_at` (reread) | `PriceSnapshot → Date` | Total | now "observed at": the capture time for archived rows. Same column, no rename |
| `Dat` | `history_checked_at?` | `Source → Date` | Partial | when the archive was last consulted |
| `Dat` | `history_note?` | `Source → 𝕊` | Partial | the outcome shown to the user (found N · none · unreachable · shop unsupported · excluded counts) |
| `Dat` | `HistoryResult` | `found(Observation*) ⊕ none(𝕊) ⊕ unavailable(𝕊) ⊕ unsupported(𝕊)` | sum | a sum, so "unreachable" can never look like "no history" (invariant 3) |
| `Trn` | `lookup` (the port) | `Source × Adapter → HistoryResult` ⊸ | Total | a history-source contract. Wayback is one realisation; BuyWhere is planned |
| `Trn` | `archive_urls` | `Url × Adapter → Url*` | Total | the URL without its query, plus the canonical form (Amazon `https://www.<host>/dp/<ASIN>`), same host only |
| `Trn` | `list_captures` | `Url* → Capture*` ⊸ | Partial | CDX, one per month (newest capture in each month), newest 24 months |
| `Trn` | `read_capture` | `Capture → PriceResult?` ⊸ | Partial | raw `id_` bytes → `scraper.extract_from_html` (never renders) |
| `Trn` | `plausible` | `ℝ* → ℝ*` | Total | drop values under median/3 or over median×3 (only when ≥ 3 values) |
| `Trn` | `backfill_source` | `Source → ()` ⊸ | Total | lookup → filter → dedup → store → write the note |
| `Trn` | `live_latest_per_source` | `PriceSnapshot* → Latest` | Deduced | as today, but **only rows with `origin? = ∅`** |

## Goals / Non-Goals

**Goals:**
- Give a new listing history on day one, where an archive has it, without
  weakening any invariant.
- Make the port small enough that BuyWhere is one new function plus a registry
  entry.

**Non-Goals:**
- **Cross-listing or cross-market history,** such as amazon.com prices for an
  amazon.sg listing. That's a different listing, possibly a different market and
  currency. If ever wanted, it should be a user-confirmed `Source` of its own
  (invariant 6).
- **Rendering archived pages.** It's unsafe, since replayed JS reaches live
  hosts, and for Lazada it's pointless.
- **Styling archived points differently on the chart.** Provenance is shown in
  the snapshot table and the per-listing note. A chart marker is a follow-up.
- **BuyWhere itself.** It stays planned until its API answers.

## Decisions

1. **Extend `PriceSnapshot` rather than adding a history table** (the §3 check
   above). Everything that reads history (`best_price_series`, the chart, the
   verdict) then picks up archived rows with no new code path.
   *Discarded:* a `history_points` table. It's a parallel object with identical
   morphisms, and every reader would have to union two stores.
2. **The current price stays live-only.** `_latest_per_source` filters out
   `origin IS NOT NULL`. Without this, a capture newer than the last live check
   would become "cheapest right now", an archived price presented as current.
3. **Matching is exact, on the same host.** `archive_urls` returns only the
   listing's own URL, stripped of its query string, and the adapter's canonical
   form. The Amazon ASIN is taken from `product_url_re`.
   *Discarded:* searching the archive by product name, or pulling amazon.com for
   an amazon.sg listing. Either would put a different listing's past into this
   listing's history.
4. **Never render.** Archived HTML goes through a new public
   `scraper.extract_from_html(html, url)`, which runs the non-browser strategies
   only. Adapters with `needs_js = True` (Lazada, Shopee) are skipped up front
   with an `unsupported` result. For Lazada, the only number in the archived HTML
   is `pdt_price`, the list price. Invariant 2 must hold even in history.
5. **Filters happen before storing.** (a) Currency: keep only captures whose
   extracted currency equals the listing's currency. That's the latest live
   snapshot's currency, else the adapter's currency for the host. Nothing is
   converted (invariants 1 and 4). (b) Plausibility: with at least 3 values
   (archived plus the listing's live prices), drop anything outside
   `[median/3, median×3]`. The excluded counts go into `history_note`.
   *Discarded:* storing everything and filtering at read time. That would put an
   accessory price or a used offer permanently into the listing's history, where
   it would skew the percentile verdict.
6. **Dedup on `origin_ref`.** Before storing, skip any capture URL the listing
   already has. Re-running is idempotent.
7. **Scheduling is a one-off APScheduler job per product,** with job id
   `history-<product_id>`, `replace_existing=True` and `max_instances=1`. The job
   loops over the product's sources in order and sleeps `REQUEST_GAP_S` (4 s)
   between archive requests (see "Load on the archive" below for why it isn't
   1 s). This reuses an existing `Loc` (the scheduler's thread pool) rather
   than adding a thread. `main` calls `history.schedule_backfill(product_id)`
   after `track_from_discovery`, `create_product` and `create_source`, and from
   the new `POST /products/{id}/history` route. Tests stub `schedule_backfill`.
   *Discarded:* running inline in the request. That's 24 × ~2.5 s per listing.
8. **The port is a module-level registry,** `HISTORY_SOURCES = [wayback_lookup]`.
   Each entry is `(source_row, adapter) → HistoryResult`. Backfill asks the
   sources in order and uses the first `found`. With one realisation today, that's
   the minimum structure that makes BuyWhere a one-line addition. The user chose
   this explicitly, so it isn't speculative abstraction (§5).
9. **Everything that touches the network is injected.** `wayback_lookup` takes
   `get` (an HTTP GET) and `sleep` callables, defaulting to `requests.get` and
   `time.sleep`. Tests pass fakes that serve fixture CDX JSON and fixture archived
   HTML. The existing Amazon fixture in `tests/test_extraction.py` has the right
   shape.

**Coherence laws to keep:**
- **Law 1.** `read_capture` runs where its HTML is delivered: in a scheduler
  thread, over `t_archive`.
- **Law 2.** `t_archive : Archive → ServerProc` carries `Capture*` (the CDX list)
  or `Html`, and crosses a real boundary.
- **Law 4.** The web request never waits on the archive. The only link is the
  scheduled job and the rows it writes (`t_sql`).
- **Law 6.** `extract_from_html` now has two placements, live and archived.
  Neither renders, so neither depends on a browser loop.

## Risks / Trade-offs

- **The archive is slow or down.** It can take minutes for a listing.
  → Background job, with timeouts of 60 s per index query and 30 s per capture (set after the index took up to 50 s live), result `unavailable`, and the page
  offers a retry.
- **An archived page shows a different offer** (used, a marketplace seller, or a
  carousel item). → The plausibility filter. **Correction during apply:** the
  extractor does *not* prefer Amazon's core price block. Its first Amazon
  selector is the generic `.a-price .a-offscreen`, which matches the first price
  anywhere on the page. The live run kept a suspicious USD 88.00 (Dec 2025),
  inside the ⅓-median band, among USD 149–278 prices. It couldn't be inspected
  because the archive then blocked this IP. The follow-up is to check that
  capture and, if confirmed, try the `#corePrice…` selectors first.
- **The archive crawler sees a US-localised price on a non-US domain.**
  → The currency filter drops it (it's excluded, never converted).
- **History mixes monthly archived points with hourly live points.** That's fine
  for percentiles, and each point is a real observation. The verdict reason
  already counts observations, and the note says how many are archived.
- **Load on the archive: corrected during apply.** The original "1 s apart" was
  wrong. The Internet Archive answers bursts with HTTP 429, and a client that
  continues for over a minute is firewall-blocked for an hour, with the block
  doubling on repeat. This IP was blocked on 2026-09-24 after the research probes
  plus one live lookup, and the first version also carried on past a 429 on a
  capture. The rules are now:
  - a 4 s gap (at most 15 requests a minute);
  - stop at the first 429 or refused connection;
  - pause all lookups in the process: 15 min after a 429, 60 min after a refusal.

  That makes up to 26 requests per listing and about 3 minutes, in the background.

## Migration Plan

Additive `ALTER TABLE … ADD COLUMN` for four nullable columns in
`_add_missing_columns`, with no rebuild. Existing rows read as live
(`origin = NULL`). To roll back, revert the code; the extra columns are ignored.
