"""The admin page: user accounts, site settings, maintenance. Admins only."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER

from . import auth, fx, scheduler, site_settings
from . import database as db
from .refresh import refresh_all
from .templating import templates

router = APIRouter(prefix="/admin")

# Messages are chosen by code, never echoed from the URL, so a crafted link
# can't put arbitrary text on the admin page.
NOTICES = {
    "role": "Role updated.",
    "disabled": "Account disabled and signed out.",
    "enabled": "Account enabled.",
    "deleted": "Account deleted, with its tracked products.",
    "settings": "Settings saved. They apply from the next search or refresh.",
    "refreshing": "Refreshing every tracked price in the background.",
    "fx": "Exchange rates refreshed.",
    "fx_failed": "Couldn't reach the exchange-rate services; the cached rates are kept.",
    "history_paused": "Archive lookups paused. Tracking won't contact the Internet Archive.",
    "history_resumed": "Archive lookups resumed.",
}


def _back(notice: str | None = None, error: str | None = None) -> RedirectResponse:
    # Errors come from AuthError/ValueError messages we wrote ourselves; they're
    # passed through a short-lived cookie, not the URL.
    response = RedirectResponse(url="/admin" + (f"?notice={notice}" if notice else ""),
                                status_code=HTTP_303_SEE_OTHER)
    if error:
        response.set_cookie("admin_error", error, max_age=30, path="/admin",
                            httponly=True, samesite="lax")
    return response


def _shop_choices() -> list[str]:
    from .search.providers import DEFAULT_SEARCH_DOMAINS
    choices = list(DEFAULT_SEARCH_DOMAINS)
    for domain in site_settings.search_domains():
        if domain not in choices:
            choices.append(domain)
    return choices


@router.get("")
def admin_page(request: Request, notice: str = "", admin=Depends(auth.require_admin)):
    response = templates.TemplateResponse("admin.html", {
        "request": request,
        "users": db.list_users(),
        "notice": NOTICES.get(notice),
        "error": request.cookies.get("admin_error"),
        "default_currency": site_settings.default_currency(),
        "search_domains": site_settings.search_domains(),
        "shop_choices": _shop_choices(),
        "numbers": {key: getattr(site_settings, key)() for key in site_settings.LABELS},
        "labels": site_settings.LABELS,
        "history_paused": site_settings.history_paused(),
        "fx_age": fx.rates_age_hours(),
    })
    response.delete_cookie("admin_error", path="/admin")
    return response


# --- users ----------------------------------------------------------------------

@router.post("/users/{user_id}/role")
def set_role(user_id: int, role: str = Form(...), admin=Depends(auth.require_admin)):
    try:
        auth.change_role(user_id, role)
    except auth.AuthError as exc:
        return _back(error=str(exc))
    return _back("role")


@router.post("/users/{user_id}/disable")
def disable(user_id: int, admin=Depends(auth.require_admin)):
    try:
        auth.set_disabled(user_id, True)
    except auth.AuthError as exc:
        return _back(error=str(exc))
    return _back("disabled")


@router.post("/users/{user_id}/enable")
def enable(user_id: int, admin=Depends(auth.require_admin)):
    try:
        auth.set_disabled(user_id, False)
    except auth.AuthError as exc:
        return _back(error=str(exc))
    return _back("enabled")


@router.post("/users/{user_id}/delete")
def delete(user_id: int, admin=Depends(auth.require_admin)):
    try:
        auth.delete_account(user_id)
    except auth.AuthError as exc:
        return _back(error=str(exc))
    return _back("deleted")


# --- site settings ------------------------------------------------------------------

@router.post("/settings")
async def save_settings(request: Request, admin=Depends(auth.require_admin)):
    """All or nothing: every value is validated before any is saved."""
    form = await request.form()
    old = {
        "currency": site_settings.default_currency(),
        "domains": site_settings.search_domains(),
        "numbers": {key: str(getattr(site_settings, key)()) for key in site_settings.LABELS},
    }
    try:
        site_settings.set_default_currency(form.get("default_currency", ""))
        site_settings.set_search_domains(form.getlist("search_domains"))
        for key in site_settings.LABELS:
            site_settings.set_number(key, form.get(key, ""))
    except ValueError as exc:
        # Put back anything saved before the invalid value was reached.
        db.set_setting("display_currency", old["currency"])
        db.set_setting("search_domains", ",".join(old["domains"]))
        for key, value in old["numbers"].items():
            db.set_setting(key, value)
        return _back(error=str(exc))
    scheduler.set_refresh_interval(site_settings.refresh_interval_hours())
    return _back("settings")


# --- maintenance ------------------------------------------------------------------------

@router.post("/maintenance/refresh-all")
def refresh_everything_now(admin=Depends(auth.require_admin)):
    scheduler.run_once("refresh-all-now", refresh_all)
    return _back("refreshing")


@router.post("/maintenance/fx")
def refresh_fx(admin=Depends(auth.require_admin)):
    return _back("fx" if fx.refresh_rates(force=True) else "fx_failed")


@router.post("/maintenance/history")
def pause_history(action: str = Form(...), admin=Depends(auth.require_admin)):
    paused = action == "pause"
    site_settings.set_history_paused(paused)
    return _back("history_paused" if paused else "history_resumed")
