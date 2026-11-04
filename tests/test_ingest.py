import sqlite3

import pytest
from chromadb import Documents, EmbeddingFunction, Embeddings
from pdfmaker import make_pdf

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
