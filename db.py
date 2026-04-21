import sqlite3
from contextlib import contextmanager
from typing import Optional

# ============================================================================
# SQL Schema Statements
# ============================================================================

CREATE_CHANNELS = """
    CREATE TABLE IF NOT EXISTS channels (
        id        TEXT PRIMARY KEY,
        name      TEXT NOT NULL,
        is_private INTEGER NOT NULL DEFAULT 0
    )
"""

CREATE_USERS = """
    CREATE TABLE IF NOT EXISTS users (
        id        TEXT PRIMARY KEY,
        name      TEXT NOT NULL,
        real_name TEXT
    )
"""

CREATE_MESSAGES = """
    CREATE TABLE IF NOT EXISTS messages (
        ts        TEXT NOT NULL,
        channel_id TEXT NOT NULL REFERENCES channels(id),
        user_id   TEXT REFERENCES users(id),
        text      TEXT,
        thread_ts TEXT,
        PRIMARY KEY (ts, channel_id)
    )
"""

CREATE_MESSAGES_IDX_CHANNEL_TS = """
    CREATE INDEX IF NOT EXISTS idx_messages_channel_ts
    ON messages(channel_id, ts)
"""

CREATE_MESSAGES_IDX_THREAD = """
    CREATE INDEX IF NOT EXISTS idx_messages_thread
    ON messages(channel_id, thread_ts)
    WHERE thread_ts IS NOT NULL
"""

CREATE_FILES = """
    CREATE TABLE IF NOT EXISTS files (
        id        TEXT PRIMARY KEY,
        message_ts TEXT NOT NULL,
        local_path TEXT,
        url       TEXT
    )
"""

CREATE_SYNC_STATE = """
    CREATE TABLE IF NOT EXISTS sync_state (
        channel_id       TEXT PRIMARY KEY REFERENCES channels(id),
        last_fetched_ts  TEXT
    )
"""

# ============================================================================
# Connection & Schema
# ============================================================================


def get_connection(db_path: str = "database.sqlite") -> sqlite3.Connection:
    """Open connection with WAL mode, row factory, and explicit transaction control."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None  # explicit transaction control
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_schema(conn: sqlite3.Connection) -> None:
    """Initialize all tables and indexes. Safe to call on every startup."""
    conn.execute(CREATE_CHANNELS)
    conn.execute(CREATE_USERS)
    conn.execute(CREATE_MESSAGES)
    conn.execute(CREATE_MESSAGES_IDX_CHANNEL_TS)
    conn.execute(CREATE_MESSAGES_IDX_THREAD)
    conn.execute(CREATE_FILES)
    conn.execute(CREATE_SYNC_STATE)
    conn.commit()


# ============================================================================
# Transaction Context Manager
# ============================================================================


@contextmanager
def transaction(conn: sqlite3.Connection):
    """Context manager for explicit transaction with rollback on exception."""
    try:
        conn.execute("BEGIN IMMEDIATE")
        yield
        conn.commit()
    except Exception:
        conn.rollback()
        raise


# ============================================================================
# Upsert & Insert Helpers
# ============================================================================


def upsert_channel(conn: sqlite3.Connection, id: str, name: str, is_private: int) -> None:
    """Insert or replace channel."""
    conn.execute(
        "INSERT OR REPLACE INTO channels (id, name, is_private) VALUES (?, ?, ?)",
        (id, name, is_private),
    )


def upsert_user(conn: sqlite3.Connection, id: str, name: str, real_name: Optional[str]) -> None:
    """Insert or replace user."""
    conn.execute(
        "INSERT OR REPLACE INTO users (id, name, real_name) VALUES (?, ?, ?)",
        (id, name, real_name),
    )


def insert_message(
    conn: sqlite3.Connection,
    ts: str,
    channel_id: str,
    user_id: Optional[str],
    text: Optional[str],
    thread_ts: Optional[str],
) -> None:
    """Insert message. Silently ignores duplicates on (ts, channel_id)."""
    conn.execute(
        "INSERT OR IGNORE INTO messages (ts, channel_id, user_id, text, thread_ts) VALUES (?, ?, ?, ?, ?)",
        (ts, channel_id, user_id, text, thread_ts),
    )


def insert_file(
    conn: sqlite3.Connection,
    id: str,
    message_ts: str,
    local_path: Optional[str],
    url: Optional[str],
) -> None:
    """Insert file record."""
    conn.execute(
        "INSERT OR REPLACE INTO files (id, message_ts, local_path, url) VALUES (?, ?, ?, ?)",
        (id, message_ts, local_path, url),
    )


def get_last_fetched_ts(conn: sqlite3.Connection, channel_id: str) -> Optional[str]:
    """Get the last successfully fetched timestamp for a channel."""
    row = conn.execute(
        "SELECT last_fetched_ts FROM sync_state WHERE channel_id = ?",
        (channel_id,),
    ).fetchone()
    return row["last_fetched_ts"] if row else None


def update_sync_state(conn: sqlite3.Connection, channel_id: str, last_ts: str) -> None:
    """Update the last fetched timestamp for a channel. Creates row if absent."""
    conn.execute(
        "INSERT OR REPLACE INTO sync_state (channel_id, last_fetched_ts) VALUES (?, ?)",
        (channel_id, last_ts),
    )
