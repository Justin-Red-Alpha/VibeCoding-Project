"""Glue between the scraper and the database: fetch a fresh price for one
source, one product's sources, or everything, and store each result (success or
failure) as a snapshot."""

import logging
import sqlite3
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
    except sqlite3.IntegrityError:
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


def _refresh_sources_politely(source_ids: list[int]) -> None:
    for index, source_id in enumerate(source_ids):
        if index:
            time.sleep(DELAY_BETWEEN_REQUESTS)
        try:
            refresh_source(source_id)
        except Exception:  # belt and braces: one listing must never stop the rest
            logger.exception("Refresh of source %s failed; continuing", source_id)


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
