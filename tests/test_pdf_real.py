"""End to end on a real PDF with the REAL embedding model (downloads about 83 MB on first use)."""

import sqlite3
from pathlib import Path

import chromadb

from rag_secure.ingest import ingest

DOCS = Path(__file__).parent / "fixtures" / "docs"


def test_real_pdf_pages_and_search(tmp_path):
    counts = ingest(DOCS, tmp_path / "chroma", tmp_path / "t.sqlite", 300, 50)
    assert counts["added"] == 1

    conn = sqlite3.connect(tmp_path / "t.sqlite")
    pages = {p for (p,) in conn.execute("SELECT page FROM chunks")}
    assert pages == {1, 2, 3}

    col = chromadb.PersistentClient(path=str(tmp_path / "chroma")).get_collection("chunks")
    ask = {
        "Which tools and programming skills do employers want?": 2,
        "Which kinds of company hire graduate computer vision engineers in the UK?": 1,
        "How can a fresher stand out, and what about visa sponsorship?": 3,
    }
    for question, expected_page in ask.items():
        top = col.query(query_texts=[question], n_results=1)["metadatas"][0][0]
        assert top["page"] == expected_page, question
        assert top["group"] == "public"
