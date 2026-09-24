"""Accounts, sessions and who may see what.

Two roles: `user` (the default) and `admin`. The first account ever registered
is the admin and takes ownership of every product that existed before accounts.

Security choices, all standard library:
  * Passwords: salted scrypt, parameters stored with the hash so they can be
    raised later. Verification is constant-time.
  * Sessions: a random token in an HttpOnly, SameSite=Lax cookie. The database
    keeps only its SHA-256, so a copied database can't be used to sign in.
    Logout, disabling and deleting remove the rows.
  * Guessing: 5 failed sign-ins for one username within 15 minutes locks it for
    15 minutes. An unknown username still costs one scrypt, so response time
    doesn't reveal which usernames exist.
  * Ownership: every product and source route goes through product_for /
    source_for. Someone else's product is a 404, exactly like a missing one.
"""

import base64
import hashlib
import hmac
import re
import secrets
import time
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request

from . import database as db

SESSION_COOKIE = "session"
SESSION_DAYS = 14

USERNAME_RE = re.compile(r"^[A-Za-z0-9._-]{3,32}$")
PASSWORD_MIN, PASSWORD_MAX = 8, 256

SCRYPT_N, SCRYPT_R, SCRYPT_P, SCRYPT_DKLEN = 2 ** 14, 8, 1, 64

LOCK_AFTER_FAILURES = 5
LOCK_WINDOW_S = 15 * 60

ROLES = ("user", "admin")


class AuthError(Exception):
    """A refusal with a message that's safe to show the user."""


# --- passwords -------------------------------------------------------------------

def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R,
                            p=SCRYPT_P, dklen=SCRYPT_DKLEN)
    b64 = lambda raw: base64.b64encode(raw).decode()
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${b64(salt)}${b64(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, n, r, p, salt, expected = encoded.split("$")
        if scheme != "scrypt":
            return False
        expected_raw = base64.b64decode(expected)
        digest = hashlib.scrypt(password.encode(), salt=base64.b64decode(salt), n=int(n),
                                r=int(r), p=int(p), dklen=len(expected_raw))
    except (ValueError, TypeError):
        return False  # a malformed or tampered hash never matches
    return hmac.compare_digest(digest, expected_raw)


# Checked against when the username doesn't exist, so an unknown user takes as
# long to refuse as a wrong password.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def username_problem(username: str) -> str | None:
    if not USERNAME_RE.match(username or ""):
        return "Usernames are 3–32 characters: letters, digits, dot, underscore or hyphen."
    return None


def password_problem(password: str) -> str | None:
    if not PASSWORD_MIN <= len(password or "") <= PASSWORD_MAX:
        return f"Passwords must be {PASSWORD_MIN}–{PASSWORD_MAX} characters long."
    return None


# --- registering and signing in -------------------------------------------------------

def register(username: str, password: str):
    """Create an account and return its row. The first account is the admin."""
    username = (username or "").strip()
    problem = username_problem(username) or password_problem(password)
    if problem:
        raise AuthError(problem)
    try:
        user_id, _role = db.create_user(username, hash_password(password))
    except db.UsernameTaken:
        raise AuthError("That username is taken.") from None
    return db.get_user(user_id)


_failures: dict[str, list[float]] = {}
_clock = time.monotonic  # tests replace this


def _recent_failures(key: str) -> list[float]:
    now = _clock()
    kept = [t for t in _failures.get(key, []) if now - t < LOCK_WINDOW_S]
    _failures[key] = kept
    return kept


def authenticate(username: str, password: str):
    """Return the user row, or raise AuthError with a message safe to display."""
    key = (username or "").strip().lower()
    if len(_recent_failures(key)) >= LOCK_AFTER_FAILURES:
        raise AuthError("Too many failed attempts for this username. Try again in 15 minutes.")

    user = db.get_user_by_name(key) if key else None
    ok = verify_password(password or "", user["password_hash"] if user else _DUMMY_HASH)
    if not (user and ok):
        _failures.setdefault(key, []).append(_clock())
        raise AuthError("Wrong username or password.")
    if user["disabled_at"]:
        raise AuthError("This account has been disabled by an admin.")
    _failures.pop(key, None)
    return user


# --- sessions --------------------------------------------------------------------------

def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def start_session(user_id: int) -> str:
    """Return the raw token for the cookie. Only its hash is stored."""
    token = secrets.token_urlsafe(32)
    expires = (_now() + timedelta(days=SESSION_DAYS)).isoformat()
    db.delete_expired_sessions(_now().isoformat())
    db.add_session(_hash_token(token), user_id, expires)
    return token


def user_for_token(token: str | None):
    """The signed-in user for this cookie, or None if it's unknown, expired or disabled."""
    if not token:
        return None
    session = db.get_session(_hash_token(token))
    if session is None or session["expires_at"] <= _now().isoformat():
        return None
    user = db.get_user(session["user_id"])
    if user is None or user["disabled_at"]:
        return None
    return user


def end_session(token: str | None) -> None:
    if token:
        db.delete_session(_hash_token(token))


def set_session_cookie(response, token: str, request: Request) -> None:
    response.set_cookie(
        SESSION_COOKIE, token, max_age=SESSION_DAYS * 24 * 3600, path="/",
        httponly=True, samesite="lax", secure=request.url.scheme == "https",
    )


def clear_session_cookie(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")


# --- who is asking, and may they ---------------------------------------------------

class LoginRequired(Exception):
    def __init__(self, next_path: str):
        self.next_path = next_path


def current_user(request: Request):
    """The signed-in user, or None. Looked up once per request."""
    if not hasattr(request.state, "user"):
        request.state.user = user_for_token(request.cookies.get(SESSION_COOKIE))
    return request.state.user


def require_user(request: Request):
    user = current_user(request)
    if user is None:
        target = request.url.path + (f"?{request.url.query}" if request.url.query else "")
        raise LoginRequired(target if request.method == "GET" else "/")
    return user


def require_admin(request: Request):
    user = require_user(request)
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Admins only.")
    return user


def is_admin(user) -> bool:
    return user is not None and user["role"] == "admin"


def product_for(user, product_id: int):
    """The product, if this user may see it (their own, or any for an admin).
    Anything else is a 404, identical to a product that doesn't exist."""
    product = db.get_product(product_id)
    if product is None or not (is_admin(user) or product["user_id"] == user["id"]):
        raise HTTPException(status_code=404, detail="Product not found")
    return product


def source_for(user, source_id: int):
    source = db.get_source(source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    product_for(user, source["product_id"])  # 404s the same way
    return source


def local_path(target: str | None, default: str = "/") -> str:
    """Only a path on this site: `/x?y` yes; `https://…`, `//host`, `/\\host` no.
    Used for every redirect that takes a destination from the request."""
    if not target or not target.startswith("/") or target.startswith(("//", "/\\")):
        return default
    if any(ch in target for ch in "\r\n"):
        return default
    return target


# --- admin actions (the last-admin guard lives here, so every path enforces it) -------

def _would_remove_last_admin(target) -> bool:
    return (target["role"] == "admin" and not target["disabled_at"]
            and db.count_enabled_admins() <= 1)


def _target(user_id: int):
    target = db.get_user(user_id)
    if target is None:
        raise AuthError("No such user.")
    return target


def change_role(user_id: int, role: str) -> None:
    if role not in ROLES:
        raise AuthError("Unknown role.")
    target = _target(user_id)
    if role == "user" and _would_remove_last_admin(target):
        raise AuthError("The site needs at least one admin.")
    db.set_user_role(user_id, role)


def set_disabled(user_id: int, disabled: bool) -> None:
    target = _target(user_id)
    if disabled and _would_remove_last_admin(target):
        raise AuthError("The site needs at least one admin.")
    db.set_user_disabled(user_id, disabled)
    if disabled:
        db.delete_user_sessions(user_id)


def delete_account(user_id: int) -> None:
    target = _target(user_id)
    if _would_remove_last_admin(target):
        raise AuthError("The site needs at least one admin.")
    db.delete_user(user_id)
