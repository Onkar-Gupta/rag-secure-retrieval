import hashlib
from pathlib import Path

import chromadb
from pypdf import PdfReader

from rag_secure import db

SUFFIXES = {".md", ".txt", ".pdf"}


def chunk_text(text, size, overlap):
    """Split text into pieces of at most `size` characters, each starting `size - overlap` after the last."""
    if overlap >= size:
        raise ValueError("overlap must be smaller than size")
    step = size - overlap
    return [text[i : i + size] for i in range(0, max(len(text) - overlap, 1), step)]


def read_pages(path):
    """Return [(page_number_or_None, text)]. Markdown and text have no pages."""
    if path.suffix == ".pdf":
        return [(n, p.extract_text() or "") for n, p in enumerate(PdfReader(path).pages, start=1)]
    return [(None, path.read_text(encoding="utf-8"))]


def group_of(path, docs_dir):
    """The group is the first folder under docs_dir. A file directly in docs_dir has none and is rejected."""
    parts = path.relative_to(docs_dir).parts
    if len(parts) < 2:
        raise ValueError(f"{path} is not inside a group folder under {docs_dir}")
    return parts[0]


def open_collection(chroma_dir, embedding_function=None):
    """The one Chroma collection of chunks. Cosine distance. Default embedder unless one is given."""
    kwargs = {"embedding_function": embedding_function} if embedding_function else {}
    return chromadb.PersistentClient(path=str(chroma_dir)).get_or_create_collection(
        "chunks", configuration={"hnsw": {"space": "cosine"}}, **kwargs
    )


def ingest(docs_dir, chroma_dir, db_path, size, overlap, embedding_function=None):
    """Chunk every document, store vectors in Chroma and text in SQLite. Unchanged files are skipped."""
    docs_dir = Path(docs_dir)
    if not docs_dir.is_dir():
        raise FileNotFoundError(f"{docs_dir} is not a folder (refusing to treat every document as deleted)")
    conn = db.connect(db_path)
    col = open_collection(chroma_dir, embedding_function)
    counts = {"added": 0, "skipped": 0, "chunks": 0, "removed": 0}
    on_disk = set()
    for path in sorted(p for p in docs_dir.rglob("*") if p.suffix in SUFFIXES):
        grp = group_of(path, docs_dir)
        on_disk.add(path.relative_to(docs_dir).as_posix())
        doc_id = path.relative_to(docs_dir).as_posix()
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        row = conn.execute("SELECT sha256 FROM documents WHERE doc_id=?", (doc_id,)).fetchone()
        if row and row[0] == sha:
            counts["skipped"] += 1
            continue
        col.delete(where={"doc_id": doc_id})
        conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        ids, texts, metas = [], [], []
        for page, text in read_pages(path):
            for piece in chunk_text(text, size, overlap):
                ids.append(f"{doc_id}#{len(ids):04d}")
                texts.append(piece)
                metas.append({"doc_id": doc_id, "group": grp, "page": page or 0})
        if ids:
            col.add(ids=ids, documents=texts, metadatas=metas)
        # Upsert, not replace: a changed file must keep its quarantine flag.
        conn.execute(
            "INSERT INTO documents (doc_id, grp, sha256) VALUES (?,?,?) "
            "ON CONFLICT(doc_id) DO UPDATE SET grp=excluded.grp, sha256=excluded.sha256",
            (doc_id, grp, sha),
        )
        conn.executemany(
            "INSERT INTO chunks VALUES (?,?,?,?)",
            [(i, doc_id, m["page"] or None, t) for i, t, m in zip(ids, texts, metas)],
        )
        conn.commit()
        counts["added"] += 1
        counts["chunks"] += len(ids)
    # A document whose file is gone (deleted, or moved to another folder) must stop being searchable.
    for (doc_id,) in conn.execute("SELECT doc_id FROM documents").fetchall():
        if doc_id not in on_disk:
            col.delete(where={"doc_id": doc_id})
            conn.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
            conn.execute("DELETE FROM documents WHERE doc_id=?", (doc_id,))
            counts["removed"] += 1
    conn.commit()
    return counts
