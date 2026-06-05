"""SQLite connection + schema bootstrap.

Stores the RAG knowledge base (documents + embedded chunks) and the
admin-trained behavior guidelines. Embeddings are kept as raw float32
BLOBs; retrieval is done in NumPy (see rag.py) — no vector extension.
"""
import sqlite3
import threading
from pathlib import Path

from config import DB_PATH

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    filename     TEXT NOT NULL,
    content_type TEXT,
    size_bytes   INTEGER,
    num_chunks   INTEGER DEFAULT 0,
    uploaded_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS chunks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    document_id INTEGER NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,
    text        TEXT NOT NULL,
    embedding   BLOB NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);

CREATE TABLE IF NOT EXISTS guidelines (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    text       TEXT NOT NULL,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL
);
"""


def get_conn() -> sqlite3.Connection:
    """Return a process-wide SQLite connection (created on first use)."""
    global _conn
    with _lock:
        if _conn is None:
            Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
            _conn = sqlite3.connect(DB_PATH, check_same_thread=False)
            _conn.row_factory = sqlite3.Row
            _conn.execute("PRAGMA foreign_keys = ON")
            _conn.execute("PRAGMA journal_mode = WAL")
            _conn.executescript(_SCHEMA)
            _conn.commit()
        return _conn


# A single shared write lock — SQLite allows one writer at a time, and the
# connection is shared across threads (check_same_thread=False).
write_lock = threading.Lock()
