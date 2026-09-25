"""Shared test helpers: a throwaway database, and signing a TestClient in.

Every suite that touches the database goes through use_temp_db() and reset_db().
With no TEST_DATABASE_URL they use a temp SQLite file. With TEST_DATABASE_URL set
(CI's Postgres job, or `docker run ... postgres:17` locally) they use that
Postgres, and reset it by dropping the whole schema -- so it must be a local
throwaway: anything else is refused before a single statement runs.
"""

import os
import tempfile
from pathlib import Path
from urllib.parse import urlsplit

from app import database as db

TEST_PASSWORD = "correct-horse-battery"

LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1"})


class UnsafeTestDatabase(RuntimeError):
    """TEST_DATABASE_URL points somewhere the tests must never erase."""


def check_test_database_url(url: str, production_url: str | None = None) -> None:
    """Refuse any database but a local throwaway. The reset erases everything."""
    if production_url is None:
        production_url = os.environ.get("DATABASE_URL")
    host = urlsplit(url).hostname
    if host not in LOCAL_HOSTS:
        raise UnsafeTestDatabase(
            f"TEST_DATABASE_URL must point at localhost or 127.0.0.1, not {host!r}: "
            "the tests drop every table in it.")
    if production_url and url == production_url:
        raise UnsafeTestDatabase("TEST_DATABASE_URL is the same as DATABASE_URL.")


def on_postgres() -> bool:
    return db.backend() == "postgres"


def use_temp_db() -> Path:
    """Point the app at a throwaway database, empty. Never data/app.db, and never
    a DATABASE_URL exported in this shell."""
    real = db.DB_PATH
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    db.DB_PATH = tmp
    assert db.DB_PATH != real, "tests must never touch data/app.db"
    url = os.environ.get("TEST_DATABASE_URL") or None
    if url:
        check_test_database_url(url)
    db.DATABASE_URL = url
    empty_db()
    return tmp


def empty_db() -> None:
    """No tables at all (the SQLite upgrade tests build an old schema by hand)."""
    if on_postgres():
        check_test_database_url(db.DATABASE_URL)  # again, right before erasing
        conn = db.get_connection()
        try:
            conn.executescript("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
            conn.commit()
        finally:
            conn.close()
        # Pooled connections keep server-side prepared statements that name the
        # dropped tables' types (citext): "cache lookup failed for type". Start over.
        db.close_pool()
    elif db.DB_PATH.exists():
        db.DB_PATH.unlink()


def reset_db() -> None:
    """An empty database with the current schema."""
    empty_db()
    db.init_db()


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
