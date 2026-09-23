"""Currency conversion, so listings in different countries can be compared.

Two rules this module exists to enforce:

  * Snapshots are **always stored in the currency the shop quoted**. Converting at
    write time would bake today's rate into permanent history, and a later rate
    change would silently rewrite what past prices "were".
  * Conversion happens at display/compare time only, and the original price is
    always shown alongside, because the original is what you'd actually be charged.

Rates are cached in SQLite, so the app keeps working offline and can tell you how
old its numbers are.
"""

import logging
from datetime import datetime, timezone

import requests

from . import database as db

logger = logging.getLogger("price_tracker.fx")

# One fetch keyed on USD gives every cross rate: A->B is usd_to_b / usd_to_a.
BASE = "USD"
RATE_SOURCES = [
    ("open.er-api", "https://open.er-api.com/v6/latest/USD", "rates"),
    ("frankfurter", "https://api.frankfurter.app/latest?base=USD", "rates"),
]
MAX_AGE_HOURS = 12

# Offered in the picker. Everything the adapters can quote, plus common majors.
DISPLAY_CURRENCIES = [
    "SGD", "MYR", "PHP", "IDR", "THB", "VND", "TWD",
    "USD", "EUR", "GBP", "JPY", "INR", "AUD", "HKD", "CAD",
]


def _fetch_rates() -> dict[str, float] | None:
    for name, url, key in RATE_SOURCES:
        try:
            resp = requests.get(url, timeout=20)
            resp.raise_for_status()
            rates = resp.json().get(key) or {}
            if rates:
                logger.info("Fetched %d FX rates from %s", len(rates), name)
                return {code: float(rate) for code, rate in rates.items()
                        if isinstance(rate, (int, float))}
        except (requests.RequestException, ValueError, TypeError) as exc:
            logger.warning("FX source %s failed: %s", name, exc)
    return None


def refresh_rates(force: bool = False) -> bool:
    """Update cached rates if they're stale. Returns True if we now have rates."""
    if not force:
        age = rates_age_hours()
        if age is not None and age < MAX_AGE_HOURS:
            return True

    rates = _fetch_rates()
    if not rates:
        # Keep serving whatever we already had rather than losing conversion.
        return db.get_fx_rates(BASE) != {}
    db.save_fx_rates(BASE, rates)
    return True


def rates_age_hours() -> float | None:
    fetched_at = db.get_fx_fetched_at(BASE)
    if not fetched_at:
        return None
    try:
        stamp = datetime.fromisoformat(fetched_at)
    except (ValueError, TypeError):
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - stamp).total_seconds() / 3600


def convert(amount: float | None, from_currency: str | None, to_currency: str | None) -> float | None:
    """Convert between currencies using cached rates. None when we can't."""
    if amount is None or not from_currency or not to_currency:
        return None
    if from_currency == to_currency:
        return round(amount, 2)

    rates = db.get_fx_rates(BASE)
    if not rates:
        return None

    from_rate = rates.get(from_currency) if from_currency != BASE else 1.0
    to_rate = rates.get(to_currency) if to_currency != BASE else 1.0
    if not from_rate or not to_rate:
        return None

    return round(amount * (to_rate / from_rate), 2)


def make_converter(display_currency: str | None):
    """Build `to_display(amount, from_currency)` for the analysis layer.

    Returns None when conversion is off, which keeps the no-conversion behaviour
    (compare only within one currency) exactly as it was.
    """
    if not display_currency:
        return None

    def to_display(amount: float | None, from_currency: str | None) -> float | None:
        return convert(amount, from_currency, display_currency)

    return to_display


def available() -> bool:
    return bool(db.get_fx_rates(BASE))
