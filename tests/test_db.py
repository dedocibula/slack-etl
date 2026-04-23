import pytest
import sqlite3
from db import (
    get_connection,
    init_schema,
    transaction,
    upsert_channel,
    upsert_user,
    insert_message,
    insert_file,
    iter_pending_files,
    iter_downloaded_files,
    clear_file_download,
    get_last_fetched_ts,
    update_sync_state,
)
from models import Channel, File, Message, User


class TestSchemaInitialization:
    """Test schema creation and idempotency."""

    def test_init_schema_creates_tables(self, db_conn):
        """init_schema creates all required tables."""
        cursor = db_conn.cursor()
        tables = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {row[0] for row in tables}

        assert "channels" in table_names
        assert "users" in table_names
        assert "messages" in table_names
        assert "files" in table_names
        assert "sync_state" in table_names

    def test_init_schema_creates_indexes(self, db_conn):
        """init_schema creates required indexes."""
        cursor = db_conn.cursor()
        indexes = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        ).fetchall()
        index_names = {row[0] for row in indexes}

        assert "idx_messages_channel_ts" in index_names
        assert "idx_messages_thread" in index_names

    def test_init_schema_is_idempotent(self, db_conn):
        """init_schema can be called multiple times safely."""
        init_schema(db_conn)

        cursor = db_conn.cursor()
        tables = cursor.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        assert len(tables) >= 5


class TestUpsertChannel:
    """Test channel upsert operations."""

    def test_upsert_channel_inserts_new(self, db_conn):
        """upsert_channel inserts new channel."""
        upsert_channel(db_conn, Channel(id="C123", name="general", is_private=False))

        row = db_conn.execute(
            "SELECT id, name, is_private FROM channels WHERE id = ?",
            ("C123",)
        ).fetchone()

        assert row["id"] == "C123"
        assert row["name"] == "general"
        assert row["is_private"] == 0

    def test_upsert_channel_replaces_existing(self, db_conn):
        """upsert_channel replaces existing channel."""
        upsert_channel(db_conn, Channel(id="C123", name="general", is_private=False))
        upsert_channel(db_conn, Channel(id="C123", name="updated-name", is_private=True))

        row = db_conn.execute(
            "SELECT name, is_private FROM channels WHERE id = ?",
            ("C123",)
        ).fetchone()

        assert row["name"] == "updated-name"
        assert row["is_private"] == 1

    def test_upsert_channel_private_flag(self, db_conn):
        """upsert_channel correctly stores is_private flag."""
        upsert_channel(db_conn, Channel(id="C456", name="secret", is_private=True))

        row = db_conn.execute(
            "SELECT is_private FROM channels WHERE id = ?",
            ("C456",)
        ).fetchone()

        assert row["is_private"] == 1


class TestUpsertUser:
    """Test user upsert operations."""

    def test_upsert_user_with_real_name(self, db_conn):
        """upsert_user inserts user with real_name."""
        upsert_user(db_conn, User(id="U123", name="john", real_name="John Doe"))

        row = db_conn.execute(
            "SELECT id, name, real_name FROM users WHERE id = ?",
            ("U123",)
        ).fetchone()

        assert row["id"] == "U123"
        assert row["name"] == "john"
        assert row["real_name"] == "John Doe"

    def test_upsert_user_nullable_real_name(self, db_conn):
        """upsert_user handles nullable real_name."""
        upsert_user(db_conn, User(id="U456", name="bot-user"))

        row = db_conn.execute(
            "SELECT real_name FROM users WHERE id = ?",
            ("U456",)
        ).fetchone()

        assert row["real_name"] is None

    def test_upsert_user_replaces_existing(self, db_conn):
        """upsert_user replaces existing user."""
        upsert_user(db_conn, User(id="U123", name="oldname", real_name="Old Name"))
        upsert_user(db_conn, User(id="U123", name="newname", real_name="New Name"))

        row = db_conn.execute(
            "SELECT name, real_name FROM users WHERE id = ?",
            ("U123",)
        ).fetchone()

        assert row["name"] == "newname"
        assert row["real_name"] == "New Name"


class TestInsertMessage:
    """Test message insertion with deduplication."""

    def test_insert_message_basic(self, db_conn):
        """insert_message stores message."""
        upsert_channel(db_conn, Channel(id="C123", name="general"))
        upsert_user(db_conn, User(id="U123", name="john", real_name="John"))

        insert_message(db_conn, "C123", Message(ts="1234567890.000100", user="U123", text="Hello"))

        row = db_conn.execute(
            "SELECT ts, channel_id, user_id, text FROM messages WHERE ts = ?",
            ("1234567890.000100",)
        ).fetchone()

        assert row["ts"] == "1234567890.000100"
        assert row["channel_id"] == "C123"
        assert row["user_id"] == "U123"
        assert row["text"] == "Hello"

    def test_insert_message_without_user(self, db_conn):
        """insert_message handles app messages without user."""
        upsert_channel(db_conn, Channel(id="C123", name="general"))

        insert_message(db_conn, "C123", Message(ts="1234567890.000100", text="App message"))

        row = db_conn.execute(
            "SELECT user_id FROM messages WHERE ts = ?",
            ("1234567890.000100",)
        ).fetchone()

        assert row["user_id"] is None

    def test_insert_message_deduplicates(self, db_conn):
        """insert_message silently ignores duplicates."""
        upsert_channel(db_conn, Channel(id="C123", name="general"))
        upsert_user(db_conn, User(id="U123", name="john"))

        insert_message(db_conn, "C123", Message(ts="1234567890.000100", user="U123", text="Hello"))
        insert_message(db_conn, "C123", Message(ts="1234567890.000100", user=None, text="Different"))

        row = db_conn.execute(
            "SELECT user_id, text FROM messages WHERE ts = ?",
            ("1234567890.000100",)
        ).fetchone()

        # First insert wins
        assert row["user_id"] == "U123"
        assert row["text"] == "Hello"

    def test_insert_message_with_thread_ts(self, db_conn):
        """insert_message stores thread_ts for replies."""
        upsert_channel(db_conn, Channel(id="C123", name="general"))
        upsert_user(db_conn, User(id="U123", name="john"))

        insert_message(db_conn, "C123", Message(ts="1234567890.000200", user="U123", text="Reply", thread_ts="1234567890.000100"))

        row = db_conn.execute(
            "SELECT thread_ts FROM messages WHERE ts = ?",
            ("1234567890.000200",)
        ).fetchone()

        assert row["thread_ts"] == "1234567890.000100"

    def test_insert_message_composite_key(self, db_conn):
        """insert_message composite key allows same ts in different channels."""
        upsert_channel(db_conn, Channel(id="C123", name="general"))
        upsert_channel(db_conn, Channel(id="C456", name="random"))
        upsert_user(db_conn, User(id="U123", name="john"))

        insert_message(db_conn, "C123", Message(ts="1234567890.000100", user="U123", text="Msg in C123"))
        insert_message(db_conn, "C456", Message(ts="1234567890.000100", user="U123", text="Msg in C456"))

        rows = db_conn.execute(
            "SELECT channel_id FROM messages WHERE ts = ? ORDER BY channel_id",
            ("1234567890.000100",)
        ).fetchall()

        assert len(rows) == 2
        assert rows[0]["channel_id"] == "C123"
        assert rows[1]["channel_id"] == "C456"


class TestInsertFile:
    """Test file insertion."""

    def test_insert_file_basic(self, db_conn):
        """insert_file stores file record."""
        insert_file(db_conn, File(id="F123", message_ts="1234567890.000100", url="https://files.slack.com/..."))

        row = db_conn.execute(
            "SELECT id, message_ts, local_path, url, size_bytes FROM files WHERE id = ?",
            ("F123",)
        ).fetchone()

        assert row["id"] == "F123"
        assert row["message_ts"] == "1234567890.000100"
        assert row["local_path"] is None
        assert row["url"] == "https://files.slack.com/..."
        assert row["size_bytes"] is None

    def test_insert_file_with_local_path_and_size(self, db_conn):
        """insert_file stores local_path and size_bytes after download."""
        insert_file(db_conn, File(id="F123", message_ts="1234567890.000100", url="https://...", local_path="/tmp/file.txt", size_bytes=1024))

        row = db_conn.execute(
            "SELECT local_path, size_bytes FROM files WHERE id = ?",
            ("F123",)
        ).fetchone()

        assert row["local_path"] == "/tmp/file.txt"
        assert row["size_bytes"] == 1024

    def test_insert_file_replaces_existing(self, db_conn):
        """insert_file replaces existing file (idempotent)."""
        insert_file(db_conn, File(id="F123", message_ts="1234567890.000100", url="https://old.url"))
        insert_file(db_conn, File(id="F123", message_ts="1234567890.000100", url="https://new.url", local_path="/tmp/file.txt", size_bytes=2048))

        row = db_conn.execute(
            "SELECT local_path, url, size_bytes FROM files WHERE id = ?",
            ("F123",)
        ).fetchone()

        assert row["local_path"] == "/tmp/file.txt"
        assert row["url"] == "https://new.url"
        assert row["size_bytes"] == 2048


class TestFileQueries:
    """Test file query helpers for download tracking."""

    def test_iter_pending_files_yields_undownloaded(self, db_conn):
        """iter_pending_files yields files with url but no local_path."""
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://a.com/f1"))
        insert_file(db_conn, File(id="F2", message_ts="100", url="https://a.com/f2", local_path="/tmp/f2", size_bytes=512))

        pending = list(iter_pending_files(db_conn))

        assert len(pending) == 1
        assert pending[0].id == "F1"

    def test_iter_pending_files_excludes_no_url(self, db_conn):
        """iter_pending_files skips files with no url."""
        insert_file(db_conn, File(id="F1", message_ts="100", url=None))

        pending = list(iter_pending_files(db_conn))

        assert len(pending) == 0

    def test_iter_pending_files_returns_file_dataclass(self, db_conn):
        """iter_pending_files yields File dataclass instances."""
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://a.com/f1"))

        pending = list(iter_pending_files(db_conn))

        assert isinstance(pending[0], File)
        assert pending[0].url == "https://a.com/f1"
        assert pending[0].local_path is None

    def test_iter_downloaded_files_yields_completed(self, db_conn):
        """iter_downloaded_files yields files with local_path and size_bytes."""
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://a.com/f1"))
        insert_file(db_conn, File(id="F2", message_ts="100", url="https://a.com/f2", local_path="/tmp/f2", size_bytes=512))

        downloaded = list(iter_downloaded_files(db_conn))

        assert len(downloaded) == 1
        assert downloaded[0].id == "F2"
        assert downloaded[0].local_path == "/tmp/f2"
        assert downloaded[0].size_bytes == 512

    def test_iter_downloaded_files_excludes_no_size(self, db_conn):
        """iter_downloaded_files skips files with local_path but no size_bytes (incomplete)."""
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://a.com/f1", local_path="/tmp/f1"))

        downloaded = list(iter_downloaded_files(db_conn))

        assert len(downloaded) == 0

    def test_clear_file_download_resets_to_pending(self, db_conn):
        """clear_file_download resets local_path and size_bytes to NULL."""
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://a.com/f1", local_path="/tmp/f1", size_bytes=1024))

        clear_file_download(db_conn, "F1")

        row = db_conn.execute(
            "SELECT local_path, size_bytes FROM files WHERE id = ?", ("F1",)
        ).fetchone()
        assert row["local_path"] is None
        assert row["size_bytes"] is None

    def test_clear_file_download_makes_file_pending_again(self, db_conn):
        """After clear_file_download, file appears in iter_pending_files."""
        insert_file(db_conn, File(id="F1", message_ts="100", url="https://a.com/f1", local_path="/tmp/f1", size_bytes=1024))

        clear_file_download(db_conn, "F1")

        pending = list(iter_pending_files(db_conn))
        assert len(pending) == 1
        assert pending[0].id == "F1"


class TestSyncState:
    """Test sync state for crash recovery."""

    def test_get_last_fetched_ts_not_found(self, db_conn):
        """get_last_fetched_ts returns None for missing channel."""
        result = get_last_fetched_ts(db_conn, "C123")
        assert result is None

    def test_update_sync_state_new_channel(self, db_conn):
        """update_sync_state creates new sync_state record."""
        upsert_channel(db_conn, Channel(id="C123", name="general"))
        update_sync_state(db_conn, "C123", "1234567890.000100")

        result = get_last_fetched_ts(db_conn, "C123")
        assert result == "1234567890.000100"

    def test_update_sync_state_replaces_existing(self, db_conn):
        """update_sync_state updates existing sync_state."""
        upsert_channel(db_conn, Channel(id="C123", name="general"))
        update_sync_state(db_conn, "C123", "1234567890.000100")
        update_sync_state(db_conn, "C123", "1234567890.000200")

        result = get_last_fetched_ts(db_conn, "C123")
        assert result == "1234567890.000200"


class TestTransaction:
    """Test transaction context manager."""

    def test_transaction_commits_on_success(self, db_conn):
        """transaction context manager commits on success."""
        with transaction(db_conn):
            upsert_channel(db_conn, Channel(id="C123", name="general"))

        row = db_conn.execute(
            "SELECT name FROM channels WHERE id = ?",
            ("C123",)
        ).fetchone()

        assert row["name"] == "general"

    def test_transaction_rolls_back_on_exception(self, db_conn):
        """transaction context manager rolls back on exception."""
        with pytest.raises(ValueError):
            with transaction(db_conn):
                upsert_channel(db_conn, Channel(id="C123", name="general"))
                raise ValueError("Test error")

        row = db_conn.execute(
            "SELECT COUNT(*) as count FROM channels WHERE id = ?",
            ("C123",)
        ).fetchone()

        assert row["count"] == 0

    def test_transaction_isolation_with_rollback(self, db_conn):
        """transaction isolation prevents partial writes."""
        upsert_channel(db_conn, Channel(id="C123", name="general"))
        upsert_user(db_conn, User(id="U123", name="john"))

        with pytest.raises(Exception):
            with transaction(db_conn):
                insert_message(db_conn, "C123", Message(ts="1234567890.000100", user="U123", text="Msg"))
                # Force foreign key violation
                db_conn.execute(
                    "INSERT INTO messages (ts, channel_id, user_id) VALUES (?, ?, ?)",
                    ("1234567890.000200", "C999", "U123")
                )

        row = db_conn.execute(
            "SELECT COUNT(*) as count FROM messages WHERE ts = ?",
            ("1234567890.000100",)
        ).fetchone()

        assert row["count"] == 0


class TestForeignKeyConstraints:
    """Test foreign key relationships."""

    def test_message_requires_valid_channel(self, db_conn):
        """insert_message fails without valid channel."""
        with pytest.raises(sqlite3.IntegrityError):
            insert_message(db_conn, "C999", Message(ts="1234567890.000100", text="Test"))

    def test_message_allows_null_user(self, db_conn):
        """insert_message allows null user_id (app messages)."""
        upsert_channel(db_conn, Channel(id="C123", name="general"))
        insert_message(db_conn, "C123", Message(ts="1234567890.000100", text="App msg"))

        row = db_conn.execute(
            "SELECT user_id FROM messages WHERE ts = ?",
            ("1234567890.000100",)
        ).fetchone()

        assert row["user_id"] is None

    def test_sync_state_requires_valid_channel(self, db_conn):
        """update_sync_state fails without valid channel FK."""
        with pytest.raises(sqlite3.IntegrityError):
            update_sync_state(db_conn, "C999", "1234567890.000100")


class TestConnectionInitialization:
    """Test get_connection setup."""

    def test_get_connection_enables_wal(self, tmp_path):
        """get_connection enables WAL mode on file-based databases."""
        db_file = str(tmp_path / "test.db")
        conn = get_connection(db_file)

        result = conn.execute("PRAGMA journal_mode").fetchone()
        assert result[0].lower() == "wal"

        conn.close()

    def test_get_connection_enables_foreign_keys(self):
        """get_connection enables foreign key constraints."""
        conn = get_connection(":memory:")

        result = conn.execute("PRAGMA foreign_keys").fetchone()
        assert result[0] == 1

        conn.close()

    def test_get_connection_sets_row_factory(self):
        """get_connection sets row_factory to sqlite3.Row."""
        conn = get_connection(":memory:")

        assert conn.row_factory == sqlite3.Row

        conn.close()

    def test_get_connection_explicit_transactions(self):
        """get_connection disables implicit transactions."""
        conn = get_connection(":memory:")

        assert conn.isolation_level is None

        conn.close()
