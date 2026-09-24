"""One Jinja environment for every router, with the signed-in user on every page."""

from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from . import auth, fx, site_settings
from .adapters import ADAPTERS


def display_currency_for(user) -> str | None:
    """The currency this visitor sees prices in: their own choice, else the site
    default. None means "as quoted"."""
    if user is not None and user["display_currency"]:
        return user["display_currency"]
    return site_settings.default_currency()


def _page_context(request: Request) -> dict:
    user = auth.current_user(request)
    return {
        "user": user,
        "is_admin": auth.is_admin(user),
        # What the currency pickers preselect (the target picker defaults to it too).
        "display_pref": display_currency_for(user),
    }


templates = Jinja2Templates(
    directory=str(Path(__file__).resolve().parent / "templates"),
    context_processors=[_page_context],
)
templates.env.globals["known_retailers"] = [a.name for a in ADAPTERS]
templates.env.globals["fx_currencies"] = fx.DISPLAY_CURRENCIES
templates.env.globals["fx_rates_age_hours"] = fx.rates_age_hours
