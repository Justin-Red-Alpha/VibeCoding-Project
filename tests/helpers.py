"""Shared test helpers: a throwaway database, and signing a TestClient in."""

import tempfile
from pathlib import Path

from app import database as db

TEST_PASSWORD = "correct-horse-battery"


def use_temp_db() -> Path:
    """Point the app at a throwaway SQLite file. Never data/app.db."""
    real = db.DB_PATH
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    db.DB_PATH = tmp
    assert db.DB_PATH != real, "tests must never touch data/app.db"
    return tmp


def client(signed_in_as: str | None = "owner", password: str = TEST_PASSWORD):
    """A TestClient (startup never runs: no FX download, no scheduler). By default
    it registers, or signs in, `owner`. The first account on a fresh DB is the admin."""
    import logging
    from fastapi.testclient import TestClient
    from app import main
    logging.getLogger("httpx").setLevel(logging.WARNING)
    c = TestClient(main.app, follow_redirects=False)
    if signed_in_as:
        sign_in(c, signed_in_as, password)
    return c


def sign_in(c, username: str, password: str = TEST_PASSWORD) -> None:
    if db.get_user_by_name(username) is None:
        r = c.post("/register", data={"username": username, "password": password,
                                      "confirm": password})
    else:
        r = c.post("/login", data={"username": username, "password": password})
    assert r.status_code == 303, f"sign-in as {username} failed: {r.status_code} {r.text[:200]}"
