import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    grp TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    quarantined INTEGER NOT NULL DEFAULT 0
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
    # Databases made before the quarantine flag existed get the column added.
    if "quarantined" not in {r[1] for r in conn.execute("PRAGMA table_info(documents)")}:
        conn.execute("ALTER TABLE documents ADD COLUMN quarantined INTEGER NOT NULL DEFAULT 0")
        conn.commit()
    return conn


def set_quarantine(conn, doc_id, on=True):
    """Hide a document from every search (or show it again). Unknown documents are an error."""
    cur = conn.execute("UPDATE documents SET quarantined=? WHERE doc_id=?", (int(on), doc_id))
    if cur.rowcount == 0:
        raise KeyError(f"unknown document: {doc_id}")
    conn.commit()


def quarantined_docs(conn):
    return [d for (d,) in conn.execute("SELECT doc_id FROM documents WHERE quarantined=1")]
