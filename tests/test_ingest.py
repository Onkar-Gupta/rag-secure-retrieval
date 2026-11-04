import sqlite3

import pytest
from chromadb import Documents, EmbeddingFunction, Embeddings

from rag_secure.ingest import chunk_text, group_of, ingest


class FakeEmbedder(EmbeddingFunction):
    """Tiny deterministic embedder so tests never download the real model."""

    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        return [[float(len(t) % 7), float(sum(map(ord, t)) % 11), 1.0] for t in input]

    @staticmethod
    def name():
        return "fake"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return FakeEmbedder()


def make_pdf(pages):
    """Smallest valid PDF with one line of text per page (standard library only)."""
    objs = ["<< /Type /Catalog /Pages 2 0 R >>"]
    kids = " ".join(f"{3 + 2 * i} 0 R" for i in range(len(pages)))
    objs.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>")
    font = 3 + 2 * len(pages)
    for i, text in enumerate(pages):
        content = f"BT /F1 12 Tf 20 100 Td ({text}) Tj ET"
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 200] /Contents {4 + 2 * i} 0 R"
            f" /Resources << /Font << /F1 {font} 0 R >> >> >>"
        )
        objs.append(f"<< /Length {len(content)} >>\nstream\n{content}\nendstream")
    objs.append("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    out, offsets = b"%PDF-1.4\n", []
    for n, body in enumerate(objs, start=1):
        offsets.append(len(out))
        out += f"{n} 0 obj\n{body}\nendobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def run(tmp_path, docs):
    return ingest(docs, tmp_path / "chroma", tmp_path / "t.sqlite", 10, 3, FakeEmbedder())


def test_chunk_boundaries_and_overlap():
    chunks = chunk_text("abcdefghijklmnopqrst", 10, 3)
    assert chunks[0] == "abcdefghij"
    assert chunks[1] == "hijklmnopq"  # starts 7 characters later, so 3 overlap
    with pytest.raises(ValueError):
        chunk_text("abc", 5, 5)


def test_group_from_folder_and_outside_rejected(tmp_path):
    (tmp_path / "finance").mkdir()
    assert group_of(tmp_path / "finance" / "a.md", tmp_path) == "finance"
    with pytest.raises(ValueError):
        group_of(tmp_path / "loose.md", tmp_path)


def test_ingest_stores_group_and_is_idempotent(tmp_path):
    docs = tmp_path / "docs"
    (docs / "finance").mkdir(parents=True)
    (docs / "finance" / "a.md").write_text("x" * 25, encoding="utf-8")
    first = run(tmp_path, docs)
    assert first["added"] == 1 and first["chunks"] == 4  # starts at 0, 7, 14, 21
    assert run(tmp_path, docs) == {"added": 0, "skipped": 1, "chunks": 0}
    (docs / "finance" / "a.md").write_text("y" * 8, encoding="utf-8")
    assert run(tmp_path, docs)["chunks"] == 1  # old chunks replaced, not added to
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    assert conn.execute("SELECT grp FROM documents").fetchall() == [("finance",)]
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone() == (1,)


def test_file_outside_group_folder_is_rejected(tmp_path):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "loose.md").write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        run(tmp_path, docs)


def test_pdf_pages_are_kept(tmp_path):
    docs = tmp_path / "docs"
    (docs / "public").mkdir(parents=True)
    (docs / "public" / "p.pdf").write_bytes(make_pdf(["page one", "page two"]))
    run(tmp_path, docs)
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    rows = conn.execute("SELECT page, text FROM chunks ORDER BY chunk_id").fetchall()
    assert {r[0] for r in rows} == {1, 2}
    assert "page one" in "".join(t for p, t in rows if p == 1)
