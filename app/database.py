"""Tiny database layer. No ORM on purpose -- easy to read, easy to vibe-code on top of.

Shape: a product (the thing you want to buy) has many sources (the same thing
listed on Amazon, Lazada, Shopee, ...), and each source accumulates price
snapshots over time.

One port, two adapters. `get_connection()` is the only way in, and it picks the
engine: the local SQLite file (the default, at DB_PATH) or Postgres when
DATABASE_URL is set (the hosted site, on Neon). Both hand back a connection with
the same small surface -- execute / executemany / executescript / commit /
rollback / close / `with conn:` -- and rows readable by name, by index, .keys()
and dict(row). The SQL below is written once for both; the few differences are
the schema tokens in schema() and write_transaction().
"""

import atexit
import logging
import os
import re
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

logger = logging.getLogger("price_tracker.database")

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

# Set -> Postgres (Neon injects it on Vercel). Unset -> the SQLite file above.
# Tests point this at a local Postgres through tests/helpers.py, never at the
# hosted database.
DATABASE_URL: str | None = os.environ.get("DATABASE_URL") or None

# Transaction-scoped advisory lock keys (Postgres). Any two distinct numbers.
# How long a request waits for a pooled Postgres connection before the database
# counts as unavailable (a 503, never an empty page).
POOL_TIMEOUT_S = 10.0

USER_GUARD_LOCK = 7_300_001  # first sign-up and last-admin changes
SCHEMA_LOCK = 7_300_002      # init_db on concurrent cold starts


class DatabaseUnavailable(RuntimeError):
    """The database couldn't be reached. Pages answer 503 instead of rendering as
    if there were no data (invariant 3, extended to the database)."""


class IntegrityError(Exception):
    """A constraint refused a write (unique, foreign key, check), on either engine."""


def backend() -> str:
    return "postgres" if DATABASE_URL else "sqlite"


SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id {pk},
    username {username},
    -- scrypt$n$r$p$salt$hash; never the password itself.
    password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user' CHECK (role IN ('user', 'admin')),
    -- Personal "Show prices in"; NULL = the site default.
    display_currency TEXT,
    disabled_at TEXT,
    created_at TEXT NOT NULL
);

-- One row per signed-in browser. Only a hash of the cookie's token is stored,
-- so a copy of this file can't be used to sign in.
CREATE TABLE IF NOT EXISTS sessions (
    token_hash TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS products (
    id {pk},
    name TEXT NOT NULL,
    target_price DOUBLE PRECISION,
    -- NULL means "in the product's own currency" (the pre-choice behaviour).
    target_currency TEXT,
    currency TEXT,
    created_at TEXT NOT NULL,
    -- Who tracks it. NULL = from before accounts; the first admin claims those.
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sources (
    id {pk},
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    retailer TEXT NOT NULL,
    url TEXT NOT NULL,
    price_selector TEXT,
    created_at TEXT NOT NULL,
    -- When the price archive was last consulted for this listing, and what it said.
    history_checked_at TEXT,
    history_note TEXT
);

CREATE TABLE IF NOT EXISTS price_snapshots (
    id {pk},
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    price DOUBLE PRECISION,
    currency TEXT,
    strategy TEXT,
    -- When the price was observed: the fetch time, or the capture time for an
    -- archived copy.
    fetched_at TEXT NOT NULL,
    error TEXT,
    -- NULL = a live check. 'wayback' = read from an archived copy of this same
    -- listing, whose URL is origin_ref. Archived rows are history only, never
    -- the current price.
    origin TEXT,
    origin_ref TEXT
);

CREATE INDEX IF NOT EXISTS idx_sources_product ON sources(product_id);
CREATE INDEX IF NOT EXISTS idx_snapshots_source ON price_snapshots(source_id);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

-- Cached FX rates. Prices themselves are never converted on the way in; this is
-- only consulted when comparing or displaying.
CREATE TABLE IF NOT EXISTS fx_rates (
    base TEXT NOT NULL,
    quote TEXT NOT NULL,
    rate DOUBLE PRECISION NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (base, quote)
);
"""

# The two places the engines' DDL differs. Money is DOUBLE PRECISION on both:
# Postgres REAL is 4 bytes (~7 digits) and would round an IDR price such as
# 1,234,567.89; SQLite reads DOUBLE PRECISION as its own 8-byte REAL.
_DIALECT = {
    "sqlite": {
        "{pk}": "INTEGER PRIMARY KEY AUTOINCREMENT",
        "{username}": "TEXT NOT NULL UNIQUE COLLATE NOCASE",
    },
    "postgres": {
        # INTEGER, not BIGINT, so the foreign keys' types match.
        "{pk}": "INTEGER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY",
        # citext keeps `WHERE username = ?` case-insensitive with no query changes.
        "{username}": "CITEXT NOT NULL UNIQUE",
    },
}


def schema(dialect: str) -> str:
    text = SCHEMA
    for token, spelling in _DIALECT[dialect].items():
        text = text.replace(token, spelling)
    return text


# --- the port ------------------------------------------------------------------

class Row:
    """A Postgres row that reads like sqlite3.Row: row["name"], row[0], .keys(),
    dict(row). (SQLite connections hand back sqlite3.Row itself.)"""

    __slots__ = ("_names", "_index", "_values")

    def __init__(self, names, index, values):
        self._names, self._index, self._values = names, index, values

    def __getitem__(self, key):
        if isinstance(key, (int, slice)):
            return self._values[key]
        return self._values[self._index[key]]

    def keys(self) -> list[str]:
        return list(self._names)

    def __iter__(self):
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)

    def __eq__(self, other) -> bool:
        return isinstance(other, Row) and (self._names, self._values) == (other._names, other._values)

    def __hash__(self):
        return hash(self._values)

    def __repr__(self) -> str:
        return f"Row({dict(zip(self._names, self._values))!r})"


def _row_factory(cursor):
    names = [column.name for column in cursor.description or ()]
    index = {name: i for i, name in enumerate(names)}
    return lambda values: Row(names, index, values)


def _redact(message: str) -> str:
    """Driver errors can quote the connection string; logs never get it."""
    message = re.sub(r"\b\w+://\S+", "<url>", message)
    return re.sub(r"(password\s*=\s*)\S+", r"\1***", message, flags=re.IGNORECASE)


class _SqliteConn(sqlite3.Connection):
    """sqlite3's own connection, raising the app's IntegrityError, so no caller
    needs to import sqlite3."""

    def execute(self, sql, parameters=()):
        try:
            return super().execute(sql, parameters)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc

    def executemany(self, sql, seq_of_parameters):
        try:
            return super().executemany(sql, seq_of_parameters)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc

    def executescript(self, script):
        try:
            return super().executescript(script)
        except sqlite3.IntegrityError as exc:
            raise IntegrityError(str(exc)) from exc


@lru_cache(maxsize=256)
def _pg_sql(sql: str) -> str:
    """`?` placeholders to psycopg's `%s`. A literal % must be doubled once
    parameters are passed. (No SQL here has a ? or % inside a string literal.)"""
    return sql.replace("%", "%%").replace("?", "%s")


def _translate(exc):
    import psycopg
    if isinstance(exc, psycopg.IntegrityError):
        return IntegrityError(str(exc))
    if isinstance(exc, psycopg.OperationalError):  # includes the pool's PoolTimeout
        logger.error("Database unreachable: %s: %s", type(exc).__name__, _redact(str(exc)))
        return DatabaseUnavailable("The database could not be reached.")
    return exc


class _PgConn:
    """The surface of sqlite3.Connection the app uses, over a pooled psycopg
    connection. close() hands it back to the pool."""

    def __init__(self, pool):
        import psycopg
        self._psycopg = psycopg
        try:
            self._conn = pool.getconn()
        except psycopg.Error as exc:
            raise _translate(exc) from exc
        self._pool = pool

    def _run(self, fn, *args):
        try:
            return fn(*args)
        except self._psycopg.Error as exc:
            translated = _translate(exc)
            if translated is exc:
                raise
            raise translated from exc

    def execute(self, sql, parameters=()):
        return self._run(self._conn.execute, _pg_sql(sql), tuple(parameters))

    def executemany(self, sql, seq_of_parameters):
        cursor = self._conn.cursor()
        self._run(cursor.executemany, _pg_sql(sql), list(seq_of_parameters))
        return cursor

    def executescript(self, script):
        # No parameters: sent as one simple query, so several statements are fine.
        # It runs inside the current transaction (SQLite's commits first).
        return self._run(self._conn.execute, script)

    def commit(self):
        self._run(self._conn.commit)

    def rollback(self):
        self._run(self._conn.rollback)

    @property
    def in_transaction(self) -> bool:
        return self._conn.info.transaction_status != self._psycopg.pq.TransactionStatus.IDLE

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        # Same as sqlite3's `with conn:`: commit, or roll back on error. Doesn't close.
        if exc_type is None:
            self.commit()
        else:
            self._conn.rollback()
        return False

    def close(self):
        conn, self._conn = getattr(self, "_conn", None), None
        if conn is None:
            return
        try:
            if not conn.closed and conn.info.transaction_status != self._psycopg.pq.TransactionStatus.IDLE:
                conn.rollback()
        except self._psycopg.Error:
            pass  # a broken connection: the pool discards it
        self._pool.putconn(conn)

    def __del__(self):
        # Safety net: a function that raised before its close() would otherwise
        # keep the connection forever, and four of those would starve the pool.
        try:
            self.close()
        except Exception:
            pass


_pool_lock = threading.Lock()
_pool = None
_pool_url: str | None = None


def _configure_pg(conn) -> None:
    import psycopg
    # READ COMMITTED, pinned rather than left to the server default: the race
    # guards in write_transaction depend on it (see there).
    conn.isolation_level = psycopg.IsolationLevel.READ_COMMITTED


def _pg_pool():
    """One small pool per process, opened on first use. Checked on checkout, so a
    connection Neon dropped while its compute slept is replaced, not handed out."""
    global _pool, _pool_url
    with _pool_lock:
        if _pool is None or _pool_url != DATABASE_URL:
            from psycopg_pool import ConnectionPool
            if _pool is not None:
                _pool.close()
            _pool = ConnectionPool(
                DATABASE_URL, min_size=0, max_size=4, timeout=POOL_TIMEOUT_S, open=False,
                check=ConnectionPool.check_connection, configure=_configure_pg,
                kwargs={"row_factory": _row_factory},
            )
            _pool.open(wait=False)
            if _pool_url is None:
                atexit.register(close_pool)  # its worker threads can't be joined later
            _pool_url = DATABASE_URL
        return _pool


def close_pool() -> None:
    global _pool, _pool_url
    with _pool_lock:
        if _pool is not None:
            _pool.close()
        _pool, _pool_url = None, None


def get_connection():
    """The port. A Postgres connection when DATABASE_URL is set, else the SQLite
    file. Raises DatabaseUnavailable if the database can't be reached."""
    if DATABASE_URL:
        return _PgConn(_pg_pool())
    try:
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(DB_PATH, factory=_SqliteConn)
    except (OSError, sqlite3.OperationalError) as exc:
        logger.error("Database unreachable: %s: %s", type(exc).__name__, exc)
        raise DatabaseUnavailable("The database could not be opened.") from exc
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def write_transaction(conn):
    """The one exclusive-write primitive, for "check, then write" rules that must
    stay atomic under concurrency (first sign-up, last admin).

    SQLite: BEGIN IMMEDIATE takes the database write lock before the check.

    Postgres: the transaction's FIRST statement takes a transaction-scoped
    advisory lock, so a second caller waits there until the first commits. The
    order matters with the isolation level: under READ COMMITTED (pinned in
    _configure_pg) each later statement sees rows committed before it began, so
    the check after the wait sees the other caller's write. Under REPEATABLE READ
    the snapshot would be taken by the lock statement itself, before the wait,
    and the check would miss that write: the race would reopen. Transaction-
    scoped locks also work through Neon's transaction-mode pooler, and are
    released by COMMIT or ROLLBACK.
    """
    if isinstance(conn, _PgConn):
        if conn.in_transaction:
            raise RuntimeError("write_transaction must start the transaction")
        try:
            conn.execute("SELECT pg_advisory_xact_lock(?)", (USER_GUARD_LOCK,))
            yield conn
            conn.commit()
        except BaseException:
            try:
                conn._conn.rollback()
            except Exception:
                pass  # a broken connection: close() hands it to the pool to discard
            raise
        return
    previous = conn.isolation_level
    conn.isolation_level = None  # we manage the transaction ourselves
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield conn
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.isolation_level = previous


def ping() -> None:
    """`SELECT 1` through the port. Raises DatabaseUnavailable if it doesn't answer."""
    conn = get_connection()
    try:
        conn.execute("SELECT 1").fetchone()
    except sqlite3.Error as exc:
        raise DatabaseUnavailable("The database did not answer.") from exc
    finally:
        conn.close()


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    try:
        return {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    except sqlite3.Error:
        return set()


def _migrate_single_url_schema(conn: sqlite3.Connection) -> None:
    """v1 stored the url + selector on the product itself. Move each of those
    into a source row so old databases keep their history."""
    if "url" not in _columns(conn, "products"):
        return

    # Foreign keys must be OFF for a table rebuild. Renaming a parent table
    # rewrites its children's references to follow it, so with enforcement on,
    # the final DROP of the old table would cascade into the rows we just
    # migrated and delete them.
    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    # Without this, renaming a table rewrites every other table's references to
    # follow it -- so a leftover child would end up pointing at `products_v1`
    # and break for good once we drop it.
    conn.execute("PRAGMA legacy_alter_table = ON")

    conn.executescript(
        """
        ALTER TABLE products RENAME TO products_v1;
        ALTER TABLE price_snapshots RENAME TO price_snapshots_v1;
        -- Any `sources` here is an empty leftover from an interrupted upgrade;
        -- drop it so SCHEMA recreates it pointing at the new `products`.
        DROP TABLE IF EXISTS sources;
        """
    )
    conn.executescript(schema("sqlite"))

    for row in conn.execute("SELECT * FROM products_v1"):
        conn.execute(
            "INSERT INTO products (id, name, target_price, currency, created_at) VALUES (?, ?, ?, ?, ?)",
            (row["id"], row["name"], row["target_price"], None, row["created_at"]),
        )
        cur = conn.execute(
            "INSERT INTO sources (product_id, retailer, url, price_selector, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (row["id"], _retailer_name(row["url"]), row["url"], row["price_selector"], row["created_at"]),
        )
        conn.execute(
            "INSERT INTO price_snapshots (source_id, price, currency, strategy, fetched_at, error) "
            "SELECT ?, price, NULL, NULL, fetched_at, error FROM price_snapshots_v1 WHERE product_id = ?",
            (cur.lastrowid, row["id"]),
        )

    conn.executescript("DROP TABLE price_snapshots_v1; DROP TABLE products_v1;")
    conn.commit()
    conn.execute("PRAGMA legacy_alter_table = OFF")
    conn.execute("PRAGMA foreign_keys = ON")


def _retailer_name(url: str) -> str:
    from .adapters import retailer_label
    return retailer_label(url)


def _add_missing_columns(conn: sqlite3.Connection) -> None:
    """Columns added after a table already existed. CREATE TABLE IF NOT EXISTS
    won't add them to an old database. ADD COLUMN doesn't rebuild the table, so
    the foreign-key cascade trap above doesn't apply here."""
    additions = {
        "products": {
            "target_currency": "TEXT",
            # ADD COLUMN may carry a REFERENCES clause as long as it defaults to NULL.
            "user_id": "INTEGER REFERENCES users(id) ON DELETE CASCADE",
        },
        "sources": {"history_checked_at": "TEXT", "history_note": "TEXT"},
        "price_snapshots": {"origin": "TEXT", "origin_ref": "TEXT"},
    }
    for table, columns in additions.items():
        existing = _columns(conn, table)
        for column, definition in columns.items():
            if column not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def init_db() -> None:
    conn = get_connection()
    try:
        if backend() == "postgres":
            # Two instances cold-starting together would both run CREATE TABLE
            # IF NOT EXISTS, and Postgres can reject the second with a duplicate
            # error. The lock, as the transaction's first statement, makes them
            # take turns. A Postgres database always starts from this schema, so
            # the SQLite upgrade steps below don't apply.
            conn.execute("SELECT pg_advisory_xact_lock(?)", (SCHEMA_LOCK,))
            conn.execute("CREATE EXTENSION IF NOT EXISTS citext")
            conn.executescript(schema("postgres"))
            conn.commit()
            return
        # Migrate first: the new indexes reference columns a v1 database doesn't
        # have yet, so applying SCHEMA to it would fail.
        _migrate_single_url_schema(conn)
        conn.executescript(schema("sqlite"))
        _add_missing_columns(conn)
        conn.commit()
    finally:
        conn.close()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- products ---------------------------------------------------------

def add_product(
    name: str,
    target_price: float | None,
    currency: str | None = None,
    target_currency: str | None = None,
    user_id: int | None = None,
) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO products (name, target_price, target_currency, currency, created_at, user_id) "
        "VALUES (?, ?, ?, ?, ?, ?) RETURNING id",
        (name, target_price, target_currency, currency, now_iso(), user_id),
    )
    product_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return product_id


def get_products() -> list[Row]:
    """Every product of every user: for the scheduler and admin maintenance only."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM products ORDER BY created_at DESC, id DESC").fetchall()
    conn.close()
    return rows


def get_products_for_user(user_id: int) -> list[Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM products WHERE user_id = ? ORDER BY created_at DESC, id DESC", (user_id,)
    ).fetchall()
    conn.close()
    return rows


def get_product(product_id: int) -> Row | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    conn.close()
    return row


def delete_product(product_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM products WHERE id = ?", (product_id,))
    conn.commit()
    conn.close()


def set_product_currency(product_id: int, currency: str) -> None:
    """Pin the product's currency the first time a source reports one."""
    conn = get_connection()
    conn.execute(
        "UPDATE products SET currency = ? WHERE id = ? AND (currency IS NULL OR currency = '')",
        (currency, product_id),
    )
    conn.commit()
    conn.close()


# --- sources ----------------------------------------------------------

def add_source(product_id: int, url: str, price_selector: str | None, retailer: str | None = None) -> int:
    conn = get_connection()
    cur = conn.execute(
        "INSERT INTO sources (product_id, retailer, url, price_selector, created_at) "
        "VALUES (?, ?, ?, ?, ?) RETURNING id",
        (product_id, retailer or _retailer_name(url), url, price_selector or None, now_iso()),
    )
    source_id = cur.fetchone()[0]
    conn.commit()
    conn.close()
    return source_id


def get_sources(product_id: int) -> list[Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM sources WHERE product_id = ? ORDER BY created_at ASC, id ASC", (product_id,)
    ).fetchall()
    conn.close()
    return rows


def get_source(source_id: int) -> Row | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    conn.close()
    return row


def get_all_sources() -> list[Row]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM sources ORDER BY id").fetchall()
    conn.close()
    return rows


def get_sources_stalest_first() -> list[Row]:
    """Every listing, least recently checked first: never-checked ones, then by
    their latest *live* check (a failed check counts; an archived row doesn't),
    ties by id. NULLS FIRST is spelled out because the engines disagree: SQLite
    puts NULLs first when ascending, Postgres last."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT src.* FROM sources src
        LEFT JOIN (
            SELECT source_id, MAX(fetched_at) AS last_checked FROM price_snapshots
            WHERE origin IS NULL GROUP BY source_id
        ) live ON live.source_id = src.id
        ORDER BY live.last_checked ASC NULLS FIRST, src.id ASC
        """
    ).fetchall()
    conn.close()
    return rows


def get_products_with_unchecked_sources() -> list[int]:
    """Products with a listing the archive was never asked about (or whose lookup
    was cut off before it finished): what the daily run's history sweep resumes."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT DISTINCT product_id FROM sources WHERE history_checked_at IS NULL ORDER BY product_id"
    ).fetchall()
    conn.close()
    return [row[0] for row in rows]


def delete_source(source_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
    conn.commit()
    conn.close()


# --- price snapshots ----------------------------------------------------

def add_snapshot(
    source_id: int,
    price: float | None,
    currency: str | None = None,
    strategy: str | None = None,
    error: str | None = None,
    fetched_at: str | None = None,
    origin: str | None = None,
    origin_ref: str | None = None,
) -> None:
    """Record one observation. Live checks leave `fetched_at` to now and `origin`
    empty; archived ones pass the capture time and where it came from.

    Raises IntegrityError if the source was deleted meanwhile. The failed
    insert is rolled back and the connection closed before it propagates: left
    open, its transaction would keep the write lock and every later write would
    fail with "database is locked".
    """
    conn = get_connection()
    try:
        with conn:  # commits, or rolls back on error
            conn.execute(
                "INSERT INTO price_snapshots "
                "(source_id, price, currency, strategy, fetched_at, error, origin, origin_ref) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (source_id, price, currency, strategy, fetched_at or now_iso(), error, origin, origin_ref),
            )
    finally:
        conn.close()


def get_origin_refs(source_id: int) -> set[str]:
    """Archived copies already recorded for this listing, so a re-run adds none twice."""
    conn = get_connection()
    rows = conn.execute(
        "SELECT origin_ref FROM price_snapshots WHERE source_id = ? AND origin_ref IS NOT NULL",
        (source_id,),
    ).fetchall()
    conn.close()
    return {row["origin_ref"] for row in rows}


def set_history_note(source_id: int, note: str) -> None:
    conn = get_connection()
    conn.execute(
        "UPDATE sources SET history_checked_at = ?, history_note = ? WHERE id = ?",
        (now_iso(), note, source_id),
    )
    conn.commit()
    conn.close()


def get_snapshots(source_id: int) -> list[Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM price_snapshots WHERE source_id = ? ORDER BY fetched_at ASC, id ASC",
        (source_id,)
    ).fetchall()
    conn.close()
    return rows


def get_snapshots_for_product(product_id: int) -> list[Row]:
    """Every snapshot across every source of this product, newest last."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT s.*, src.retailer, src.url
        FROM price_snapshots s
        JOIN sources src ON src.id = s.source_id
        WHERE src.product_id = ?
        ORDER BY s.fetched_at ASC, s.id ASC
        """,
        (product_id,),
    ).fetchall()
    conn.close()
    return rows


def get_latest_snapshot(source_id: int) -> Row | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM price_snapshots WHERE source_id = ? ORDER BY fetched_at DESC, id DESC LIMIT 1",
        (source_id,),
    ).fetchone()
    conn.close()
    return row


# --- users and sessions --------------------------------------------------

class UsernameTaken(Exception):
    pass


def create_user(username: str, password_hash: str) -> tuple[int, str]:
    """Insert a user and return (id, role). The very first user is the admin and
    takes ownership of every product created before accounts existed.

    write_transaction takes the write lock before counting, so two first sign-ups
    racing each other can't both see zero users and both become admin.
    """
    conn = get_connection()
    try:
        with write_transaction(conn):
            existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            role = "admin" if existing == 0 else "user"
            try:
                user_id = conn.execute(
                    "INSERT INTO users (username, password_hash, role, created_at) "
                    "VALUES (?, ?, ?, ?) RETURNING id",
                    (username, password_hash, role, now_iso()),
                ).fetchone()[0]
            except IntegrityError as exc:
                raise UsernameTaken(username) from exc
            if role == "admin":
                conn.execute("UPDATE products SET user_id = ? WHERE user_id IS NULL", (user_id,))
    finally:
        conn.close()
    return user_id, role


def count_users() -> int:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return count


def get_user(user_id: int) -> Row | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def get_user_by_name(username: str) -> Row | None:
    """Case-insensitive: the column is COLLATE NOCASE (SQLite) or CITEXT (Postgres)."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row


def list_users() -> list[Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT u.*, (SELECT COUNT(*) FROM products p WHERE p.user_id = u.id) AS product_count "
        "FROM users u ORDER BY u.created_at ASC, u.id ASC"
    ).fetchall()
    conn.close()
    return rows


def count_enabled_admins() -> int:
    conn = get_connection()
    count = conn.execute(
        "SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled_at IS NULL"
    ).fetchone()[0]
    conn.close()
    return count


class LastAdmin(Exception):
    """The change would leave the site without an enabled admin."""


class NoSuchUser(Exception):
    pass


def guarded_user_change(user_id: int, *, role: str | None = None,
                        disabled: bool | None = None, delete: bool = False) -> None:
    """Change a user's role, disable/enable them, or delete them, refusing any change
    that would leave no enabled admin.

    The check and the write happen in ONE write_transaction (the write lock), so
    two admins demoting each other at the same moment can't both see "2 admins"
    and both succeed.
    """
    conn = get_connection()
    try:
        with write_transaction(conn):
            target = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
            if target is None:
                raise NoSuchUser(user_id)
            removes_admin = (
                target["role"] == "admin" and target["disabled_at"] is None
                and (delete or role == "user" or disabled is True)
            )
            if removes_admin:
                admins = conn.execute(
                    "SELECT COUNT(*) FROM users WHERE role = 'admin' AND disabled_at IS NULL"
                ).fetchone()[0]
                if admins <= 1:
                    raise LastAdmin(user_id)
            if delete:
                conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
            else:
                if role is not None:
                    conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
                if disabled is not None:
                    conn.execute("UPDATE users SET disabled_at = ? WHERE id = ?",
                                 (now_iso() if disabled else None, user_id))
                    if disabled:
                        conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    finally:
        conn.close()


def set_user_role(user_id: int, role: str) -> None:
    conn = get_connection()
    conn.execute("UPDATE users SET role = ? WHERE id = ?", (role, user_id))
    conn.commit()
    conn.close()


def set_user_disabled(user_id: int, disabled: bool) -> None:
    conn = get_connection()
    conn.execute("UPDATE users SET disabled_at = ? WHERE id = ?",
                 (now_iso() if disabled else None, user_id))
    conn.commit()
    conn.close()


def delete_user(user_id: int) -> None:
    """Cascades to the user's products (and their sources and snapshots) and sessions."""
    conn = get_connection()
    conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()
    conn.close()


def set_user_currency(user_id: int, currency: str | None) -> None:
    conn = get_connection()
    conn.execute("UPDATE users SET display_currency = ? WHERE id = ?", (currency, user_id))
    conn.commit()
    conn.close()


def add_session(token_hash: str, user_id: int, expires_at: str) -> None:
    conn = get_connection()
    conn.execute(
        "INSERT INTO sessions (token_hash, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token_hash, user_id, now_iso(), expires_at),
    )
    conn.commit()
    conn.close()


def get_session(token_hash: str) -> Row | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM sessions WHERE token_hash = ?", (token_hash,)).fetchone()
    conn.close()
    return row


def delete_session(token_hash: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
    conn.commit()
    conn.close()


def delete_user_sessions(user_id: int) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()


def delete_expired_sessions(now: str) -> None:
    conn = get_connection()
    conn.execute("DELETE FROM sessions WHERE expires_at <= ?", (now,))
    conn.commit()
    conn.close()


# --- settings ----------------------------------------------------------

def get_setting(key: str, default: str | None = None) -> str | None:
    conn = get_connection()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row and row["value"] is not None else default


def set_setting(key: str, value: str | None) -> None:
    conn = get_connection()
    if value is None or value == "":
        conn.execute("DELETE FROM settings WHERE key = ?", (key,))
    else:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
    conn.commit()
    conn.close()


# --- fx rates ----------------------------------------------------------

def save_fx_rates(base: str, rates: dict[str, float]) -> None:
    stamp = now_iso()
    conn = get_connection()
    conn.executemany(
        "INSERT INTO fx_rates (base, quote, rate, fetched_at) VALUES (?, ?, ?, ?) "
        "ON CONFLICT(base, quote) DO UPDATE SET rate = excluded.rate, fetched_at = excluded.fetched_at",
        [(base, quote, float(rate), stamp) for quote, rate in rates.items()],
    )
    conn.commit()
    conn.close()


def get_fx_rates(base: str) -> dict[str, float]:
    conn = get_connection()
    rows = conn.execute("SELECT quote, rate FROM fx_rates WHERE base = ?", (base,)).fetchall()
    conn.close()
    return {row["quote"]: row["rate"] for row in rows}


def get_fx_fetched_at(base: str) -> str | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT fetched_at FROM fx_rates WHERE base = ? ORDER BY fetched_at DESC LIMIT 1", (base,)
    ).fetchone()
    conn.close()
    return row["fetched_at"] if row else None
