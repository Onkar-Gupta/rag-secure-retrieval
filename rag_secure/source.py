"""Find a cited chunk inside its page, so the page can show exactly where an answer came from."""


def context(conn, chunk_id, size, overlap):
    """{doc_id, page, before, highlight, after} for one chunk, or None if the chunk is unknown.

    Chunks of one page start `size - overlap` characters apart, so the page text is the first chunk
    followed by each later chunk minus its first `overlap` characters. The cited chunk is the highlight.
    Whether the caller may read the document is checked by the caller, not here."""
    row = conn.execute("SELECT doc_id, page FROM chunks WHERE chunk_id=?", (chunk_id,)).fetchone()
    if row is None:
        return None
    doc_id, page = row
    rows = conn.execute("SELECT chunk_id, text FROM chunks WHERE doc_id=? AND page IS ? ORDER BY chunk_id",
                        (doc_id, page)).fetchall()
    step = size - overlap
    text, start, end = "", 0, 0
    for i, (cid, piece) in enumerate(rows):
        text += piece if i == 0 else piece[overlap:]
        if cid == chunk_id:
            start, end = i * step, i * step + len(piece)
    return {"doc_id": doc_id, "page": page, "before": text[:start], "highlight": text[start:end], "after": text[end:]}
