"""Tiny SQLite wrapper. No ORM on purpose -- easy to read, easy to vibe-code on top of.

Shape: a product (the thing you want to buy) has many sources (the same thing
listed on Amazon, Lazada, Shopee, ...), and each source accumulates price
snapshots over time.
"""

import sqlite3
from pathlib import Path
from datetime import datetime, timezone

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "app.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE COLLATE NOCASE,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    target_price REAL,
    -- NULL means "in the product's own currency" (the pre-choice behaviour).
    target_currency TEXT,
    currency TEXT,
    created_at TEXT NOT NULL,
    -- Who tracks it. NULL = from before accounts; the first admin claims those.
    user_id INTEGER REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id INTEGER NOT NULL REFERENCES sources(id) ON DELETE CASCADE,
    price REAL,
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
    rate REAL NOT NULL,
    fetched_at TEXT NOT NULL,
    PRIMARY KEY (base, quote)
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


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
    conn.executescript(SCHEMA)

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
    # Migrate first: the new indexes reference columns a v1 database doesn't
    # have yet, so applying SCHEMA to it would fail.
    _migrate_single_url_schema(conn)
    conn.executescript(SCHEMA)
    _add_missing_columns(conn)
    conn.commit()
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
        "VALUES (?, ?, ?, ?, ?, ?)",
        (name, target_price, target_currency, currency, now_iso(), user_id),
    )
    conn.commit()
    product_id = cur.lastrowid
    conn.close()
    return product_id


def get_products() -> list[sqlite3.Row]:
    """Every product of every user: for the scheduler and admin maintenance only."""
    conn = get_connection()
    rows = conn.execute("SELECT * FROM products ORDER BY created_at DESC").fetchall()
    conn.close()
    return rows


def get_products_for_user(user_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM products WHERE user_id = ? ORDER BY created_at DESC", (user_id,)
    ).fetchall()
    conn.close()
    return rows


def get_product(product_id: int) -> sqlite3.Row | None:
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
        "INSERT INTO sources (product_id, retailer, url, price_selector, created_at) VALUES (?, ?, ?, ?, ?)",
        (product_id, retailer or _retailer_name(url), url, price_selector or None, now_iso()),
    )
    conn.commit()
    source_id = cur.lastrowid
    conn.close()
    return source_id


def get_sources(product_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM sources WHERE product_id = ? ORDER BY created_at ASC", (product_id,)
    ).fetchall()
    conn.close()
    return rows


def get_source(source_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    conn.close()
    return row


def get_all_sources() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute("SELECT * FROM sources").fetchall()
    conn.close()
    return rows


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
    empty; archived ones pass the capture time and where it came from."""
    conn = get_connection()
    conn.execute(
        "INSERT INTO price_snapshots "
        "(source_id, price, currency, strategy, fetched_at, error, origin, origin_ref) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (source_id, price, currency, strategy, fetched_at or now_iso(), error, origin, origin_ref),
    )
    conn.commit()
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


def get_snapshots(source_id: int) -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM price_snapshots WHERE source_id = ? ORDER BY fetched_at ASC", (source_id,)
    ).fetchall()
    conn.close()
    return rows


def get_snapshots_for_product(product_id: int) -> list[sqlite3.Row]:
    """Every snapshot across every source of this product, newest last."""
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT s.*, src.retailer, src.url
        FROM price_snapshots s
        JOIN sources src ON src.id = s.source_id
        WHERE src.product_id = ?
        ORDER BY s.fetched_at ASC
        """,
        (product_id,),
    ).fetchall()
    conn.close()
    return rows


def get_latest_snapshot(source_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute(
        "SELECT * FROM price_snapshots WHERE source_id = ? ORDER BY fetched_at DESC LIMIT 1",
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

    BEGIN IMMEDIATE takes the write lock before counting, so two first sign-ups
    racing each other can't both see zero users and both become admin.
    """
    conn = get_connection()
    conn.isolation_level = None  # we manage the transaction ourselves
    try:
        conn.execute("BEGIN IMMEDIATE")
        existing = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        role = "admin" if existing == 0 else "user"
        try:
            cur = conn.execute(
                "INSERT INTO users (username, password_hash, role, created_at) VALUES (?, ?, ?, ?)",
                (username, password_hash, role, now_iso()),
            )
        except sqlite3.IntegrityError as exc:
            raise UsernameTaken(username) from exc
        user_id = cur.lastrowid
        if role == "admin":
            conn.execute("UPDATE products SET user_id = ? WHERE user_id IS NULL", (user_id,))
        conn.execute("COMMIT")
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()
    return user_id, role


def count_users() -> int:
    conn = get_connection()
    count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    conn.close()
    return count


def get_user(user_id: int) -> sqlite3.Row | None:
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def get_user_by_name(username: str) -> sqlite3.Row | None:
    """Case-insensitive: the column is COLLATE NOCASE."""
    conn = get_connection()
    row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
    conn.close()
    return row


def list_users() -> list[sqlite3.Row]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT u.*, (SELECT COUNT(*) FROM products p WHERE p.user_id = u.id) AS product_count "
        "FROM users u ORDER BY u.created_at ASC"
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


def get_session(token_hash: str) -> sqlite3.Row | None:
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
