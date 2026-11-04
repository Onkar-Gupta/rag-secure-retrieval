import datetime
import hashlib
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    grp TEXT NOT NULL,
    sha256 TEXT NOT NULL,
    quarantined INTEGER NOT NULL DEFAULT 0,
    uploader TEXT,
    ingested_at TEXT
);
CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    page INTEGER,
    text TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS query_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    user TEXT NOT NULL,
    question_hash TEXT NOT NULL,
    question_text TEXT,
    chunk_ids TEXT NOT NULL,
    found INTEGER NOT NULL,
    latency_ms INTEGER NOT NULL
);
"""


def connect(path):
    conn = sqlite3.connect(path)
    conn.executescript(SCHEMA)
    # Databases made before a column existed get it added.
    have = {r[1] for r in conn.execute("PRAGMA table_info(documents)")}
    for column, ddl in (("quarantined", "INTEGER NOT NULL DEFAULT 0"), ("uploader", "TEXT"), ("ingested_at", "TEXT")):
        if column not in have:
            conn.execute(f"ALTER TABLE documents ADD COLUMN {column} {ddl}")
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


def log_query(conn, user, question, chunk_ids, found, latency_ms, keep_text=False):
    """Record one question. By default only a hash of the question is kept, not the text."""
    digest = hashlib.sha256(question.encode()).hexdigest()[:16]
    conn.execute(
        "INSERT INTO query_log (ts, user, question_hash, question_text, chunk_ids, found, latency_ms) "
        "VALUES (?,?,?,?,?,?,?)",
        (datetime.datetime.now().astimezone().isoformat(timespec="seconds"), user, digest,
         question if keep_text else None, ",".join(chunk_ids), int(found), int(latency_ms)),
    )
    conn.commit()


def provenance(conn, chunk_ids):
    """Where each chunk came from: its document, group, who uploaded it and on what date."""
    out = []
    for cid in chunk_ids:
        row = conn.execute(
            "SELECT d.doc_id, d.grp, d.uploader, d.ingested_at FROM chunks c JOIN documents d USING (doc_id) "
            "WHERE c.chunk_id=?", (cid,)).fetchone()
        if row:
            out.append({"chunk_id": cid, "doc_id": row[0], "group": row[1], "uploader": row[2],
                        "ingested_at": row[3]})
    return out
