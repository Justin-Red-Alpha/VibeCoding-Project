"""Registering, signing in and out, and personal preferences."""

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from starlette.status import HTTP_303_SEE_OTHER

from . import auth
from . import database as db
from .fx import DISPLAY_CURRENCIES
from .templating import templates

router = APIRouter()


def _signed_in_redirect(request: Request, user, next_path: str) -> RedirectResponse:
    token = auth.start_session(user["id"])
    response = RedirectResponse(url=auth.local_path(next_path), status_code=HTTP_303_SEE_OTHER)
    auth.set_session_cookie(response, token, request)
    return response


def _form_page(request: Request, page: str, next_path: str, error: str | None = None,
               username: str = "", status: int = 200):
    return templates.TemplateResponse(
        page,
        {"request": request, "next": auth.local_path(next_path), "error": error,
         "username": username, "first_account": db.count_users() == 0,
         "signed_out": request.query_params.get("signed_out") == "1"},
        status_code=status,
    )


@router.get("/login")
def login_page(request: Request, next: str = "/"):
    if auth.current_user(request):
        return RedirectResponse(url=auth.local_path(next), status_code=HTTP_303_SEE_OTHER)
    return _form_page(request, "login.html", next)


@router.post("/login")
def login(request: Request, username: str = Form(""), password: str = Form(""),
          next: str = Form("/")):
    try:
        user = auth.authenticate(username, password)
    except auth.AuthError as exc:
        return _form_page(request, "login.html", next, str(exc), username, status=400)
    return _signed_in_redirect(request, user, next)


@router.get("/register")
def register_page(request: Request, next: str = "/"):
    if auth.current_user(request):
        return RedirectResponse(url=auth.local_path(next), status_code=HTTP_303_SEE_OTHER)
    return _form_page(request, "register.html", next)


@router.post("/register")
def register(request: Request, username: str = Form(""), password: str = Form(""),
             confirm: str = Form(""), next: str = Form("/")):
    if password != confirm:
        return _form_page(request, "register.html", next, "The passwords don't match.",
                          username, status=400)
    try:
        user = auth.register(username, password)
    except auth.AuthError as exc:
        return _form_page(request, "register.html", next, str(exc), username, status=400)
    return _signed_in_redirect(request, user, next)


@router.post("/logout")
def logout(request: Request):
    auth.end_session(request.cookies.get(auth.SESSION_COOKIE))
    response = RedirectResponse(url="/login?signed_out=1", status_code=HTTP_303_SEE_OTHER)
    auth.clear_session_cookie(response)
    return response


@router.post("/settings/currency")
def set_display_currency(currency: str = Form(""), next_url: str = Form("/"),
                         user=Depends(auth.require_user)):
    """The signed-in user's own "Show prices in". It never affects anyone else."""
    choice = currency.strip().upper()
    if choice and choice not in DISPLAY_CURRENCIES:
        choice = ""
    db.set_user_currency(user["id"], choice or None)
    if choice:
        from . import fx
        fx.refresh_rates()
    return RedirectResponse(url=auth.local_path(next_url), status_code=HTTP_303_SEE_OTHER)
