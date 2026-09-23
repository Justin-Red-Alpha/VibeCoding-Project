"""Glue between the scraper and the database: fetch a fresh price for one
source, one product's sources, or everything, and store each result (success or
failure) as a snapshot."""

import logging
import time

from . import database as db
from .scraper import fetch_price, ScrapeError

logger = logging.getLogger("price_tracker.refresh")

# Be a polite client: never fire retailer requests back to back.
DELAY_BETWEEN_REQUESTS = 1.5


def refresh_source(source_id: int) -> None:
    source = db.get_source(source_id)
    if source is None:
        return
    try:
        result = fetch_price(source["url"], source["price_selector"])
        db.add_snapshot(
            source_id,
            price=result.price,
            currency=result.currency,
            strategy=result.strategy,
        )
        if result.currency:
            db.set_product_currency(source["product_id"], result.currency)
        logger.info(
            "Refreshed %s (%s): %s %.2f via %s",
            source["retailer"], source_id, result.currency or "", result.price, result.strategy,
        )
    except ScrapeError as exc:
        db.add_snapshot(source_id, price=None, error=str(exc))
        logger.warning("Failed to refresh %s (%s): %s", source["retailer"], source_id, exc)
    except Exception as exc:  # never let one bad source abort a batch refresh
        db.add_snapshot(source_id, price=None, error=f"Unexpected error: {exc}")
        logger.exception("Unexpected error refreshing source %s", source_id)


def refresh_product(product_id: int) -> None:
    sources = db.get_sources(product_id)
    for index, source in enumerate(sources):
        if index:
            time.sleep(DELAY_BETWEEN_REQUESTS)
        refresh_source(source["id"])


def refresh_all() -> None:
    sources = db.get_all_sources()
    for index, source in enumerate(sources):
        if index:
            time.sleep(DELAY_BETWEEN_REQUESTS)
        refresh_source(source["id"])
