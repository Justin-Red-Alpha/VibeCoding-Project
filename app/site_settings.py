"""Site-wide settings an admin can change without a restart.

Each value is read when it's used (per search, per refresh), so a change applies
at once. The resolution order is the admin's value in the `settings` table, then
the environment variable, then the built-in default.

Two rules keep the admin page from damaging configuration it didn't touch:
  * Clean first, write after. `clean_*` validates and returns a value without
    saving; the admin form cleans every field before writing any, so an invalid
    field changes nothing at all.
  * Only a changed value is stored. Saving the form with an untouched field
    leaves it unset, so its environment variable and default keep applying.

Shops are stored as the ones switched *off*, not the ones switched on. A shop
added to ADAPTERS later is therefore searched automatically ("adding a shop =
one entry in ADAPTERS" stays true), and an admin can only switch off shops from
the known list, never type in a new site.
"""

import logging
import os

from . import database as db

logger = logging.getLogger("price_tracker.settings")

# key -> (env var, default, min, max, whole number?)
_NUMBERS = {
    "refresh_interval_hours": ("REFRESH_INTERVAL_HOURS", 6, 1, 168, False),
    "discover_per_shop": ("DISCOVER_PER_SHOP", 6, 1, 20, True),
    "discover_price_limit": ("DISCOVER_PRICE_LIMIT", 6, 0, 20, True),
}

LABELS = {
    "refresh_interval_hours": "Refresh interval (hours)",
    "discover_per_shop": "Listings kept per shop",
    "discover_price_limit": "Missing prices looked up per search",
}

_warned: set[str] = set()


def _parse_number(key: str, raw) -> float | None:
    """The value if it's a number in range (whole where required), else None."""
    _env, _default, low, high, whole = _NUMBERS[key]
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if not low <= value <= high or (whole and value != int(value)):
        return None
    return value


def ignored_env() -> list[str]:
    """Environment values that are set but unusable, so they're being ignored.
    Shown on the admin page and logged once, rather than dropped silently."""
    problems = []
    for key, (env, default, low, high, whole) in _NUMBERS.items():
        raw = os.environ.get(env)
        if raw is not None and _parse_number(key, raw) is None:
            kind = "a whole number" if whole else "a number"
            problems.append(f"{env}={raw!r} is ignored: it must be {kind} from {low} to {high}.")
    return problems


def _number(key: str) -> float:
    env, default, *_ = _NUMBERS[key]
    for source, raw in (("setting", db.get_setting(key)), ("env", os.environ.get(env))):
        if raw is None:
            continue
        value = _parse_number(key, raw)
        if value is not None:
            return value
        if source == "env" and env not in _warned:
            _warned.add(env)
            logger.warning("Ignoring %s=%r: out of range or not a number; using %s", env, raw, default)
    return default


def refresh_interval_hours() -> float:
    return _number("refresh_interval_hours")


def discover_per_shop() -> int:
    return int(_number("discover_per_shop"))


def discover_price_limit() -> int:
    return int(_number("discover_price_limit"))


def clean_number(key: str, raw: str) -> float:
    value = _parse_number(key, raw)
    if value is None:
        _env, _default, low, high, whole = _NUMBERS[key]
        kind = "a whole number" if whole else "a number"
        raise ValueError(f"{LABELS[key]} must be {kind} from {low} to {high}.")
    return value


def format_number(value: float) -> str:
    """For the admin form: 6.0 -> "6", 1.05 -> "1.05" (never mangles digits)."""
    return f"{value:g}"


def save_number(key: str, value: float) -> None:
    """Store only a change, so an untouched field keeps following its env/default."""
    if value != _number(key):
        _env, _default, _low, _high, whole = _NUMBERS[key]
        db.set_setting(key, str(int(value)) if whole else f"{value:g}")


# --- default display currency (anonymous visitors and users without a preference) ----

def default_currency() -> str | None:
    return db.get_setting("display_currency") or None


def clean_currency(code: str) -> str | None:
    from .fx import DISPLAY_CURRENCIES
    code = (code or "").strip().upper()
    if code and code not in DISPLAY_CURRENCIES:
        raise ValueError(f"Unsupported currency: {code}.")
    return code or None


def save_default_currency(code: str | None) -> None:
    if code != default_currency():
        db.set_setting("display_currency", code)


# --- shops searched ----------------------------------------------------------------

def available_shops() -> list[str]:
    """Every shop search could cover: SEARCH_DOMAINS if set, else every adapter's
    search domain. The admin chooses among these; it can't add to them."""
    from .search.providers import DEFAULT_SEARCH_DOMAINS
    configured = [d.strip().lower() for d in os.environ.get("SEARCH_DOMAINS", "").split(",")
                  if d.strip()]
    return configured or list(DEFAULT_SEARCH_DOMAINS)


def _switched_off() -> set[str]:
    return {d for d in (db.get_setting("search_domains_off") or "").split(",") if d}


def search_domains() -> list[str]:
    off = _switched_off()
    return [d for d in available_shops() if d not in off]


def clean_search_domains(chosen: list[str]) -> list[str]:
    """Exact matches against the known list only, so nothing new can be injected."""
    available = available_shops()
    picked = [d for d in available if d in {c.strip().lower() for c in chosen}]
    unknown = [c for c in chosen if c.strip().lower() not in available]
    if unknown:
        raise ValueError(f"Not one of the shops this app searches: {', '.join(unknown)}.")
    if not picked:
        raise ValueError("Pick at least one shop to search.")
    return picked


def save_search_domains(picked: list[str]) -> None:
    off = [d for d in available_shops() if d not in picked]
    db.set_setting("search_domains_off", ",".join(off) or None)


# --- archive lookups on hold --------------------------------------------------------

def history_paused() -> bool:
    return db.get_setting("history_paused") == "1"


def set_history_paused(paused: bool) -> None:
    db.set_setting("history_paused", "1" if paused else None)
