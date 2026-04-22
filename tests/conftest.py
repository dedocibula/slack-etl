import sqlite3
import pytest
from db import get_connection, init_schema


@pytest.fixture
def db_conn():
    """Provide an in-memory SQLite database with schema initialized."""
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.isolation_level = None
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")

    # Initialize schema
    init_schema(conn)

    yield conn

    conn.close()
