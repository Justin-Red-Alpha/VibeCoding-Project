"""Glue between the scraper and the database: fetch a fresh price for one
source, one product's sources, or everything, and store each result (success or
failure) as a snapshot."""

import logging
import threading
import time

from . import database as db
from .scraper import fetch_price, ScrapeError

logger = logging.getLogger("price_tracker.refresh")

# Be a polite client: never fire retailer requests back to back.
DELAY_BETWEEN_REQUESTS = 1.5

# Batch refreshes (the schedule, an admin's "refresh everyone", a user's "refresh
# my prices") take turns rather than running side by side: two loops at once
# would hit the same shops twice as fast, breaking the sequential rule above.
_batch_lock = threading.Lock()


def _record(source_id: int, **snapshot) -> bool:
    """Store a snapshot. False if the listing was deleted while we fetched it
    (its row is gone, so the foreign key refuses): that is not an error."""
    try:
        db.add_snapshot(source_id, **snapshot)
        return True
    except db.IntegrityError:
        logger.info("Source %s was deleted during its refresh; result dropped", source_id)
        return False


def refresh_source(source_id: int) -> None:
    source = db.get_source(source_id)
    if source is None:
        return
    try:
        result = fetch_price(source["url"], source["price_selector"])
    except ScrapeError as exc:
        _record(source_id, price=None, error=str(exc))
        logger.warning("Failed to refresh %s (%s): %s", source["retailer"], source_id, exc)
        return
    except Exception as exc:  # never let one bad source abort a batch refresh
        _record(source_id, price=None, error=f"Unexpected error: {exc}")
        logger.exception("Unexpected error refreshing source %s", source_id)
        return

    if _record(source_id, price=result.price, currency=result.currency, strategy=result.strategy):
        if result.currency:
            db.set_product_currency(source["product_id"], result.currency)
        logger.info(
            "Refreshed %s (%s): %s %.2f via %s",
            source["retailer"], source_id, result.currency or "", result.price, result.strategy,
        )


def _refresh_sources_politely(source_ids: list[int], deadline: float | None = None,
                              clock=time.monotonic) -> int:
    """Check each listing in turn. With a deadline, no new check starts once it has
    passed. Returns how many were checked."""
    checked = 0
    for index, source_id in enumerate(source_ids):
        if index:
            time.sleep(DELAY_BETWEEN_REQUESTS)
        if deadline is not None and clock() >= deadline:
            break
        try:
            refresh_source(source_id)
        except Exception:  # belt and braces: one listing must never stop the rest
            logger.exception("Refresh of source %s failed; continuing", source_id)
        checked += 1
    return checked


def stalest_first() -> list[int]:
    """Every listing's id, least recently checked first (db.get_sources_stalest_first)."""
    return [row["id"] for row in db.get_sources_stalest_first()]


def refresh_stalest(deadline: float, clock=time.monotonic) -> dict:
    """The daily run's refresh: stalest listings first, starting no new check after
    `deadline`. Nothing is queued: a listing it didn't reach is simply still the
    stalest, so the next run starts with it."""
    with _batch_lock:
        source_ids = stalest_first()
        checked = _refresh_sources_politely(source_ids, deadline=deadline, clock=clock)
    return {"refreshed": checked, "refresh_left": len(source_ids) - checked}


def refresh_product(product_id: int) -> None:
    """One product, right now (used when it's added or its Refresh button is pressed)."""
    _refresh_sources_politely([s["id"] for s in db.get_sources(product_id)])


def refresh_products(product_ids: list[int]) -> None:
    """Several products (one user's), in turn with any other batch refresh."""
    with _batch_lock:
        source_ids = [s["id"] for pid in product_ids for s in db.get_sources(pid)]
        _refresh_sources_politely(source_ids)


def refresh_all() -> None:
    with _batch_lock:
        _refresh_sources_politely([s["id"] for s in db.get_all_sources()])
