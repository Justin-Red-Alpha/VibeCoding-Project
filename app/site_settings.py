"""Site-wide settings an admin can change without a restart.

Each value is read when it's used (per search, per refresh), so a change applies
at once. The resolution order is the admin's value in the `settings` table, then
the old environment variable, then the built-in default. Setters validate and
raise ValueError with a message safe to show; an invalid value never replaces
the current one.
"""

import os

from . import database as db
from .adapters import GENERIC, adapter_for

# key -> (env var, default, min, max)
_NUMBERS = {
    "refresh_interval_hours": ("REFRESH_INTERVAL_HOURS", 6, 1, 168),
    "discover_per_shop": ("DISCOVER_PER_SHOP", 6, 1, 20),
    "discover_price_limit": ("DISCOVER_PRICE_LIMIT", 6, 0, 20),
}

LABELS = {
    "refresh_interval_hours": "Refresh interval (hours)",
    "discover_per_shop": "Listings kept per shop",
    "discover_price_limit": "Missing prices looked up per search",
}


def _number(key: str) -> float:
    env, default, low, high = _NUMBERS[key]
    for raw in (db.get_setting(key), os.environ.get(env)):
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        if low <= value <= high:
            return value
    return default


def refresh_interval_hours() -> float:
    return _number("refresh_interval_hours")


def discover_per_shop() -> int:
    return int(_number("discover_per_shop"))


def discover_price_limit() -> int:
    return int(_number("discover_price_limit"))


def set_number(key: str, raw: str) -> float:
    env, default, low, high = _NUMBERS[key]
    try:
        value = float(raw)
    except (TypeError, ValueError):
        raise ValueError(f"{LABELS[key]} must be a number.") from None
    if not low <= value <= high or (key != "refresh_interval_hours" and value != int(value)):
        kind = "a number" if key == "refresh_interval_hours" else "a whole number"
        raise ValueError(f"{LABELS[key]} must be {kind} from {low} to {high}.")
    db.set_setting(key, str(value if key == "refresh_interval_hours" else int(value)))
    return value


# --- default display currency (anonymous visitors and users without a preference) ----

def default_currency() -> str | None:
    return db.get_setting("display_currency") or None


def set_default_currency(code: str) -> None:
    from .fx import DISPLAY_CURRENCIES
    code = (code or "").strip().upper()
    if code and code not in DISPLAY_CURRENCIES:
        raise ValueError(f"Unsupported currency: {code}.")
    db.set_setting("display_currency", code or None)


# --- shops searched ----------------------------------------------------------------

def known_shop(domain: str) -> bool:
    """Only shops the app has an adapter for: never an arbitrary site."""
    return adapter_for(f"https://www.{domain}/") is not GENERIC


def search_domains() -> list[str]:
    from .search.providers import DEFAULT_SEARCH_DOMAINS
    for raw in (db.get_setting("search_domains"), os.environ.get("SEARCH_DOMAINS", "")):
        domains = [d.strip().lower() for d in (raw or "").split(",") if d.strip()]
        if domains:
            return domains
    return list(DEFAULT_SEARCH_DOMAINS)


def set_search_domains(domains: list[str]) -> None:
    cleaned = []
    for domain in domains:
        domain = domain.strip().lower()
        if domain and domain not in cleaned:
            cleaned.append(domain)
    if not cleaned:
        raise ValueError("Pick at least one shop to search.")
    unknown = [d for d in cleaned if not known_shop(d)]
    if unknown:
        raise ValueError(f"Not a shop this app knows: {', '.join(unknown)}.")
    db.set_setting("search_domains", ",".join(cleaned))


# --- archive lookups on hold --------------------------------------------------------

def history_paused() -> bool:
    return db.get_setting("history_paused") == "1"


def set_history_paused(paused: bool) -> None:
    db.set_setting("history_paused", "1" if paused else None)
