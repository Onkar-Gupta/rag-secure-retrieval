import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    grp TEXT NOT NULL,
    sha256 TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    page INTEGER,
    text TEXT NOT NULL
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    return conn
