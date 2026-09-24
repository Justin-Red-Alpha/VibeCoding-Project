"""Past prices for a tracked listing, from a public archive of its own page.

A new product has no history, so the BUY/WAIT verdict says "not enough data" for
days. Many product pages have been archived for years, though. This finds
archived copies of the listing's OWN page, reads each one's price with the normal
extractor, and stores the results as that listing's past observations. They're
ordinary price snapshots marked `origin='wayback'`, dated when each copy was
archived.

What keeps it honest:
  * Exact matching only: the listing's URL, and the shop's canonical form of it,
    on the same host. Never another listing, shop or country domain.
  * Archived pages are never rendered, and JS-priced shops (Lazada, Shopee) are
    skipped, because the only number in their raw HTML is the list price.
  * Prices are never converted. One in a different currency from the listing is
    dropped, and so is one far from the listing's median (an accessory, a used
    offer). The note says how many.
  * An unreachable archive is reported as unreachable, never as "no history".
  * The current price stays live-only; that rule lives in main._latest_per_source.

History sources sit behind one small port (`HISTORY_SOURCES`). The Internet
Archive is the only one today. BuyWhere is the intended next one; its API was
unreachable on 2026-09-24.
"""

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from statistics import median
from urllib.parse import urlparse, urlunparse

import requests

from . import database as db
from .adapters import adapter_for
from .scraper import BROWSER_HEADERS, extract_from_html

logger = logging.getLogger("price_tracker.history")

CDX_URL = "https://web.archive.org/cdx/search/cdx"
# `id_` asks for the archived bytes as captured: no toolbar, no URL rewriting.
CAPTURE_URL = "https://web.archive.org/web/{timestamp}id_/{original}"
MAX_CAPTURES = 24          # newest months only
# The archive answers bursts with HTTP 429. A client that keeps going for more
# than a minute after that gets its IP blocked at the firewall for an hour, and
# the block doubles on repeat (learned the hard way on 2026-09-24). So: at most
# 15 requests a minute, stop at the FIRST sign of limiting, and pause every
# lookup in this process for a while afterwards.
REQUEST_GAP_S = 4.0
COOLDOWN_AFTER_429_S = 15 * 60
COOLDOWN_AFTER_BLOCK_S = 60 * 60  # connection refused = the firewall block itself
# The capture index is slow: 9 s to 50 s per query, measured 2026-09-24. The lookup
# runs in the background, so waiting costs nothing, and giving up too early would
# report a slow archive as unreachable.
CDX_TIMEOUT_S = 60
CAPTURE_TIMEOUT_S = 30
PLAUSIBLE_FACTOR = 3.0     # keep prices within [median / 3, median * 3]
MIN_VALUES_FOR_PLAUSIBILITY = 3


@dataclass
class Observation:
    price: float
    currency: str | None
    observed_at: str       # ISO 8601, UTC
    strategy: str
    ref: str               # the archived copy it was read from


@dataclass
class HistoryResult:
    """found ⊕ none ⊕ unavailable ⊕ unsupported. It's a sum, so "the archive was
    down" can never be shown as "this listing has no history"."""
    kind: str
    observations: list[Observation] = field(default_factory=list)
    reason: str = ""


# --- matching -----------------------------------------------------------------------

def archive_urls(url: str, adapter) -> list[str]:
    """The listing's own URL without tracking parameters, plus the shop's canonical
    URL for the same item on the same host. Nothing else."""
    parts = urlparse(url)
    scheme = parts.scheme or "https"
    stripped = urlunparse((scheme, parts.netloc, parts.path, "", "", ""))
    urls = [stripped]
    if adapter.item_id_re and adapter.canonical_path:
        match = re.search(adapter.item_id_re, parts.path)
        if match:
            canonical = f"{scheme}://{parts.netloc}{adapter.canonical_path.format(id=match.group(1))}"
            if canonical != stripped:
                urls.append(canonical)
    return urls


# --- the Internet Archive -----------------------------------------------------------

def _observed_at(timestamp: str) -> str:
    return datetime.strptime(timestamp[:14], "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).isoformat()


def _unavailable(detail: str) -> HistoryResult:
    return HistoryResult("unavailable", reason=(
        f"The Internet Archive couldn't be reached ({detail}), so no history was "
        "added. Try again later."))


# Process-wide: once the archive says "slow down", nobody asks again until this time.
_cooldown_until = 0.0


def _back_off(seconds: float, detail: str, clock) -> HistoryResult:
    global _cooldown_until
    _cooldown_until = max(_cooldown_until, clock() + seconds)
    logger.warning("Internet Archive %s; pausing lookups for %d min", detail, seconds // 60)
    return _unavailable(f"{detail}; pausing lookups for {int(seconds // 60)} minutes")


PAUSED_REASON = "Archive lookups were paused by an admin, so this lookup stopped early."


def _paused() -> bool:
    from . import site_settings  # site_settings imports nothing from here; lazy anyway
    return site_settings.history_paused()


def wayback_lookup(source, adapter, get=requests.get, sleep=time.sleep,
                   clock=time.monotonic, paused=None) -> HistoryResult:
    """Find this listing's archived copies and read a price from each.
    `paused` (default: the admin's switch) is re-checked before every capture."""
    paused = paused or _paused
    if adapter.needs_js:
        return HistoryResult("unsupported", reason=(
            f"Archived copies of {adapter.name} pages don't include the selling price "
            "(the shop draws it with scripts), so no history was added."))
    if clock() < _cooldown_until:
        return _unavailable("recently asked to slow down; not asking again yet")

    urls = archive_urls(source["url"], adapter)
    by_month: dict[str, tuple[str, str]] = {}
    for index, url in enumerate(urls):
        if index:
            sleep(REQUEST_GAP_S)
        try:
            resp = get(CDX_URL, params={
                "url": url, "output": "json", "fl": "timestamp,original",
                "filter": "statuscode:200", "collapse": "timestamp:6",
            }, timeout=CDX_TIMEOUT_S)
        except requests.ConnectionError:
            return _back_off(COOLDOWN_AFTER_BLOCK_S, "refused the connection", clock)
        except requests.RequestException as exc:
            return _unavailable(type(exc).__name__)
        if resp.status_code == 429:
            return _back_off(COOLDOWN_AFTER_429_S, "is rate-limiting (HTTP 429)", clock)
        if resp.status_code >= 500:
            return _unavailable(f"HTTP {resp.status_code}")
        try:
            rows = resp.json() if resp.text.strip() else []
        except ValueError:
            return _unavailable("unreadable index response")
        for timestamp, original in rows[1:]:  # the first row is the header
            month = timestamp[:6]
            if month not in by_month or timestamp > by_month[month][0]:
                by_month[month] = (timestamp, original)

    if not by_month:
        return HistoryResult("none", reason="The Internet Archive has no copies of this listing.")

    picks = [by_month[m] for m in sorted(by_month, reverse=True)[:MAX_CAPTURES]]
    observations: list[Observation] = []
    failed = 0
    for timestamp, original in picks:
        sleep(REQUEST_GAP_S)
        if paused():
            # An admin paused lookups mid-run (often *because* the archive is
            # rate-limiting us): stop now rather than finish 24 requests.
            return HistoryResult("unavailable", reason=PAUSED_REASON)
        ref = CAPTURE_URL.format(timestamp=timestamp, original=original)
        try:
            resp = get(ref, headers=BROWSER_HEADERS, timeout=CAPTURE_TIMEOUT_S)
        except requests.ConnectionError:
            # Refused mid-run: that's the firewall block. Stop, don't try the rest.
            return _back_off(COOLDOWN_AFTER_BLOCK_S, "refused the connection", clock)
        except requests.RequestException:
            failed += 1  # a slow copy; the next one may be fine
            continue
        if resp.status_code == 429:
            return _back_off(COOLDOWN_AFTER_429_S, "is rate-limiting (HTTP 429)", clock)
        if resp.status_code != 200:
            failed += 1
            continue
        result = extract_from_html(resp.text, original)
        if result is None:
            continue
        observations.append(Observation(
            price=result.price, currency=result.currency,
            observed_at=_observed_at(timestamp),
            strategy=f"wayback:{result.strategy}", ref=ref,
        ))

    if failed == len(picks):
        return _unavailable(f"all {failed} archived copies failed to load")
    if not observations:
        return HistoryResult("none", reason=(
            f"The Internet Archive has {len(picks)} copies of this listing, but none "
            "shows a readable price."))
    observations.sort(key=lambda o: o.observed_at)
    return HistoryResult("found", observations=observations)


# Tried in order; the first `found` wins. BuyWhere is planned (see module docstring).
HISTORY_SOURCES = [wayback_lookup]


# --- filtering and storing ------------------------------------------------------------

def filter_observations(observations, currency, live_prices):
    """Split archived prices into (kept, other_currency, implausible).

    Nothing is converted: a price in another currency can't be compared with this
    listing's, so it's dropped. With at least 3 prices to judge by (archived + live),
    anything under a third or over three times the median is dropped too. It's
    probably a different offer (an accessory, a used unit), and keeping it would
    skew the verdict's percentiles for good.
    """
    same = [o for o in observations if o.currency == currency]
    other_currency = len(observations) - len(same)
    values = [o.price for o in same] + list(live_prices)
    if len(values) < MIN_VALUES_FOR_PLAUSIBILITY:
        return same, other_currency, 0
    mid = median(values)
    low, high = mid / PLAUSIBLE_FACTOR, mid * PLAUSIBLE_FACTOR
    kept = [o for o in same if low <= o.price <= high]
    return kept, other_currency, len(same) - len(kept)


def _found_note(kept, added, other_currency, implausible) -> str:
    if kept:
        first, last = kept[0].observed_at[:7], kept[-1].observed_at[:7]
        note = (f"Internet Archive: {len(kept)} archived price{'s' if len(kept) != 1 else ''}, "
                f"{first} to {last} ({added} new).")
    else:
        note = "Internet Archive: archived prices were found, but none could be used."
    excluded = []
    if implausible:
        excluded.append(f"{implausible} implausible")
    if other_currency:
        excluded.append(f"{other_currency} in another currency")
    if excluded:
        note += " Excluded: " + ", ".join(excluded) + "."
    return note


def backfill_source(source_id: int, lookups=None) -> HistoryResult | None:
    """Look up one listing's archived prices and store the usable, new ones."""
    source = db.get_source(source_id)
    if source is None:
        return None
    adapter = adapter_for(source["url"])

    result = None
    for lookup in lookups or HISTORY_SOURCES:
        attempt = lookup(source, adapter)
        result = result or attempt
        if attempt.kind == "found":
            result = attempt
            break

    if result.kind != "found":
        db.set_history_note(source_id, result.reason)
        logger.info("History for source %s: %s", source_id, result.kind)
        return result

    live = [s for s in db.get_snapshots(source_id)
            if s["origin"] is None and s["price"] is not None]
    currency = (live[-1]["currency"] if live and live[-1]["currency"]
                else adapter.currency_for(urlparse(source["url"]).hostname or ""))
    kept, other_currency, implausible = filter_observations(
        result.observations, currency, [s["price"] for s in live])

    known = db.get_origin_refs(source_id)
    new = [o for o in kept if o.ref not in known]
    for o in new:
        db.add_snapshot(source_id, o.price, o.currency, o.strategy,
                        fetched_at=o.observed_at, origin="wayback", origin_ref=o.ref)

    db.set_history_note(source_id, _found_note(kept, len(new), other_currency, implausible))
    logger.info("History for source %s: %d kept, %d new, %d other currency, %d implausible",
                source_id, len(kept), len(new), other_currency, implausible)
    return result


def backfill_product(product_id: int, only_unchecked: bool = False) -> None:
    """The product's listings, one after another (never in parallel).

    `only_unchecked` skips listings the archive was already asked about, so adding
    a second shop doesn't re-fetch the first one's 24 copies. The user's "Look for
    archived prices" button passes False and re-checks everything.
    """
    for source in db.get_sources(product_id):
        if _paused():
            return  # paused while this job was queued or running: stop here
        if only_unchecked and source["history_checked_at"]:
            continue
        try:
            backfill_source(source["id"])
        except Exception:  # one listing must never stop the others
            logger.exception("History lookup failed for source %s", source["id"])


def schedule_backfill(product_id: int, only_unchecked: bool = True) -> None:
    """Run the lookup in the background: at most one per product at a time.
    Does nothing while an admin has archive lookups paused (and a job already
    queued or running re-checks the pause as it goes)."""
    if _paused():
        return
    from .scheduler import run_once
    run_once(f"history-{product_id}", backfill_product, product_id, only_unchecked)
