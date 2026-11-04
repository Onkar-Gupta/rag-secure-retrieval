import sqlite3

import pytest
from chromadb import Documents, EmbeddingFunction, Embeddings
from pdfmaker import make_pdf

from rag_secure import db
from rag_secure.ingest import chunk_text, group_of, ingest, open_collection, read_pages


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
    assert run(tmp_path, docs) == {"added": 0, "skipped": 1, "chunks": 0, "removed": 0, "pages_without_text": []}
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


def test_deleted_file_is_removed_from_both_stores(tmp_path):
    docs = tmp_path / "docs"
    (docs / "finance").mkdir(parents=True)
    (docs / "finance" / "secret.md").write_text("x" * 25, encoding="utf-8")
    (docs / "finance" / "keep.md").write_text("y" * 25, encoding="utf-8")
    run(tmp_path, docs)
    (docs / "finance" / "secret.md").unlink()
    assert run(tmp_path, docs)["removed"] == 1
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    assert conn.execute("SELECT doc_id FROM documents").fetchall() == [("finance/keep.md",)]
    assert {d for (d,) in conn.execute("SELECT doc_id FROM chunks")} == {"finance/keep.md"}
    meta = open_collection(tmp_path / "chroma", FakeEmbedder()).get(include=["metadatas"])["metadatas"]
    assert {m["doc_id"] for m in meta} == {"finance/keep.md"}


def test_moved_file_is_searchable_only_under_its_new_group(tmp_path):
    docs = tmp_path / "docs"
    (docs / "public").mkdir(parents=True)
    (docs / "finance").mkdir()
    (docs / "public" / "plan.md").write_text("z" * 25, encoding="utf-8")
    run(tmp_path, docs)
    (docs / "public" / "plan.md").rename(docs / "finance" / "plan.md")
    run(tmp_path, docs)
    meta = open_collection(tmp_path / "chroma", FakeEmbedder()).get(include=["metadatas"])["metadatas"]
    assert {(m["doc_id"], m["group"]) for m in meta} == {("finance/plan.md", "finance")}


def test_missing_docs_folder_does_not_wipe_the_index(tmp_path):
    docs = tmp_path / "docs"
    (docs / "public").mkdir(parents=True)
    (docs / "public" / "a.md").write_text("x" * 25, encoding="utf-8")
    run(tmp_path, docs)
    with pytest.raises(FileNotFoundError):
        run(tmp_path, tmp_path / "typo")
    assert sqlite3.connect(tmp_path / "t.sqlite").execute("SELECT COUNT(*) FROM chunks").fetchone()[0] > 0


def test_changing_chunk_settings_rebuilds_the_index(tmp_path):
    docs = tmp_path / "docs"
    (docs / "public").mkdir(parents=True)
    (docs / "public" / "a.md").write_text("x" * 40, encoding="utf-8")
    assert ingest(docs, tmp_path / "chroma", tmp_path / "t.sqlite", 10, 3, FakeEmbedder())["chunks"] == 6
    again = ingest(docs, tmp_path / "chroma", tmp_path / "t.sqlite", 20, 5, FakeEmbedder())
    assert again["added"] == 1 and again["chunks"] == 3  # starts at 0, 15, 30
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    assert conn.execute("SELECT COUNT(*) FROM chunks").fetchone() == (3,)


def test_a_pdf_page_with_no_text_is_reported_and_makes_no_empty_chunk(tmp_path):
    docs = tmp_path / "docs"
    (docs / "public").mkdir(parents=True)
    scan = make_pdf([["A real page with plenty of readable text on it."], [], ["Another readable page of text here."]])
    (docs / "public" / "scan.pdf").write_bytes(scan)
    counts = run(tmp_path, docs)
    assert counts["pages_without_text"] == ["public/scan.pdf page 2"]
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    assert {p for (p,) in conn.execute("SELECT page FROM chunks")} == {1, 3}  # no chunk for the blank page
    assert conn.execute("SELECT COUNT(*) FROM chunks WHERE trim(text) = ''").fetchone() == (0,)


def test_markdown_and_text_never_report_missing_pages(tmp_path):
    docs = tmp_path / "docs"
    (docs / "public").mkdir(parents=True)
    (docs / "public" / "short.md").write_text("hi", encoding="utf-8")
    assert run(tmp_path, docs)["pages_without_text"] == []


def test_wrapped_pdf_lines_are_joined_into_one_sentence_and_the_page_number_is_kept(tmp_path):
    lines = ["Visitors must sign in at the front desk and", "wear a badge at all times while", "they are inside the building."]
    pdf = tmp_path / "rules.pdf"
    pdf.write_bytes(make_pdf([["Page one text, long enough to count."], lines]))
    pages = read_pages(pdf)
    assert [n for n, _ in pages] == [1, 2]
    assert pages[1][1] == "Visitors must sign in at the front desk and wear a badge at all times while they are inside the building."
    docs = tmp_path / "docs"
    (docs / "public").mkdir(parents=True)
    (docs / "public" / "rules.pdf").write_bytes(pdf.read_bytes())
    run(tmp_path, docs)
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    assert all(chr(10) not in text for (text,) in conn.execute("SELECT text FROM chunks"))
    page2 = conn.execute("SELECT chunk_id FROM chunks WHERE page=2 ORDER BY chunk_id").fetchone()[0]
    assert db.provenance(conn, [page2])[0]["page"] == 2


def test_markdown_text_is_returned_exactly_as_written(tmp_path):
    md = tmp_path / "a.md"
    text = chr(10).join(["line one", "line two", "", "new paragraph"])
    md.write_text(text, encoding="utf-8")
    assert read_pages(md) == [(None, text)]


def test_a_changed_min_page_chars_changes_what_counts_as_empty(tmp_path):
    docs = tmp_path / "docs"
    (docs / "public").mkdir(parents=True)
    (docs / "public" / "short.pdf").write_bytes(make_pdf([["Tiny page."]]))
    assert ingest(docs, tmp_path / "c", tmp_path / "t.sqlite", 10, 3, FakeEmbedder(), min_page_chars=5)[
        "pages_without_text"] == []
    (docs / "public" / "short.pdf").write_bytes(make_pdf([["Tiny page!"]]))  # a changed file is read again
    assert ingest(docs, tmp_path / "c", tmp_path / "t.sqlite", 10, 3, FakeEmbedder(), min_page_chars=50)[
        "pages_without_text"] == ["public/short.pdf page 1"]
