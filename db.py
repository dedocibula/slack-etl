import sqlite3
from contextlib import contextmanager
from typing import Iterator, Optional

from models import Channel, File, Message, User

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
        url       TEXT,
        size_bytes INTEGER
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


def upsert_channel(conn: sqlite3.Connection, channel: Channel) -> None:
    """Insert or replace channel."""
    conn.execute(
        "INSERT OR REPLACE INTO channels (id, name, is_private) VALUES (?, ?, ?)",
        (channel.id, channel.name, int(channel.is_private)),
    )


def upsert_user(conn: sqlite3.Connection, user: User) -> None:
    """Insert or replace user."""
    conn.execute(
        "INSERT OR REPLACE INTO users (id, name, real_name) VALUES (?, ?, ?)",
        (user.id, user.name, user.real_name),
    )


def insert_message(
    conn: sqlite3.Connection,
    channel_id: str,
    msg: Message,
) -> None:
    """Insert message. Silently ignores duplicates on (ts, channel_id)."""
    conn.execute(
        "INSERT OR IGNORE INTO messages (ts, channel_id, user_id, text, thread_ts) VALUES (?, ?, ?, ?, ?)",
        (msg.ts, channel_id, msg.user, msg.text, msg.thread_ts),
    )


def insert_file(conn: sqlite3.Connection, f: File) -> None:
    """Insert or replace file record."""
    conn.execute(
        "INSERT OR REPLACE INTO files (id, message_ts, local_path, url, size_bytes) VALUES (?, ?, ?, ?, ?)",
        (f.id, f.message_ts, f.local_path, f.url, f.size_bytes),
    )


def iter_pending_files(conn: sqlite3.Connection) -> Iterator[File]:
    """Yield files that have a URL but have not been downloaded yet."""
    rows = conn.execute(
        "SELECT id, message_ts, url, local_path, size_bytes FROM files WHERE local_path IS NULL AND url IS NOT NULL"
    ).fetchall()
    for row in rows:
        yield File(id=row["id"], message_ts=row["message_ts"], url=row["url"],
                   local_path=row["local_path"], size_bytes=row["size_bytes"])


def iter_downloaded_files(conn: sqlite3.Connection) -> Iterator[File]:
    """Yield files that have been downloaded (local_path and size_bytes set)."""
    rows = conn.execute(
        "SELECT id, message_ts, url, local_path, size_bytes FROM files WHERE local_path IS NOT NULL AND size_bytes IS NOT NULL"
    ).fetchall()
    for row in rows:
        yield File(id=row["id"], message_ts=row["message_ts"], url=row["url"],
                   local_path=row["local_path"], size_bytes=row["size_bytes"])


def clear_file_download(conn: sqlite3.Connection, file_id: str) -> None:
    """Reset local_path and size_bytes to NULL so the file is re-queued for download."""
    conn.execute(
        "UPDATE files SET local_path = NULL, size_bytes = NULL WHERE id = ?",
        (file_id,),
    )


def build_user_map(conn: sqlite3.Connection) -> dict[str, User]:
    """Return {user_id: User} for all users in the DB."""
    rows = conn.execute("SELECT id, name, real_name FROM users").fetchall()
    return {row["id"]: User(id=row["id"], name=row["name"], real_name=row["real_name"]) for row in rows}


def iter_channels_from_db(conn: sqlite3.Connection) -> Iterator[Channel]:
    """Yield all channels stored in the DB."""
    rows = conn.execute("SELECT id, name, is_private FROM channels").fetchall()
    for row in rows:
        yield Channel(id=row["id"], name=row["name"], is_private=bool(row["is_private"]))


def iter_distinct_months(conn: sqlite3.Connection, channel_id: str) -> Iterator[tuple[int, int]]:
    """Yield (year, month) tuples for every calendar month that has messages in a channel, oldest first."""
    rows = conn.execute(
        """SELECT DISTINCT
               CAST(strftime('%Y', datetime(CAST(ts AS REAL), 'unixepoch', 'localtime')) AS INTEGER) AS yr,
               CAST(strftime('%m', datetime(CAST(ts AS REAL), 'unixepoch', 'localtime')) AS INTEGER) AS mo
           FROM messages WHERE channel_id = ? ORDER BY yr, mo""",
        (channel_id,),
    ).fetchall()
    for row in rows:
        yield (row["yr"], row["mo"])


def iter_top_level_messages(
    conn: sqlite3.Connection, channel_id: str, month_start: float, month_end: float
) -> Iterator[Message]:
    """Yield top-level messages (not replies) for a channel within [month_start, month_end)."""
    rows = conn.execute(
        """SELECT ts, user_id, text, thread_ts FROM messages
           WHERE channel_id = ?
             AND CAST(ts AS REAL) >= ? AND CAST(ts AS REAL) < ?
             AND (thread_ts IS NULL OR ts = thread_ts)
           ORDER BY CAST(ts AS REAL)""",
        (channel_id, month_start, month_end),
    ).fetchall()
    for row in rows:
        yield Message(ts=row["ts"], user=row["user_id"], text=row["text"], thread_ts=row["thread_ts"])


def iter_thread_replies(
    conn: sqlite3.Connection, channel_id: str, thread_ts: str
) -> Iterator[Message]:
    """Yield replies for a thread, excluding the parent message, oldest first."""
    rows = conn.execute(
        """SELECT ts, user_id, text FROM messages
           WHERE channel_id = ? AND thread_ts = ? AND ts != thread_ts
           ORDER BY CAST(ts AS REAL)""",
        (channel_id, thread_ts),
    ).fetchall()
    for row in rows:
        yield Message(ts=row["ts"], user=row["user_id"], text=row["text"])


def iter_files_for_message(conn: sqlite3.Connection, message_ts: str) -> Iterator[File]:
    """Yield files attached to a given message timestamp."""
    rows = conn.execute(
        "SELECT id, message_ts, url, local_path, size_bytes FROM files WHERE message_ts = ?",
        (message_ts,),
    ).fetchall()
    for row in rows:
        yield File(id=row["id"], message_ts=row["message_ts"], url=row["url"],
                   local_path=row["local_path"], size_bytes=row["size_bytes"])


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
