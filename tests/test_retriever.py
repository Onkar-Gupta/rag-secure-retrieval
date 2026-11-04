"""Filtered retrieval. The key regression test: a forbidden chunk never comes back, even when it
is the closest match. Uses real Chroma with a tiny keyword embedder so we control the distances."""

import pytest
from chromadb import Documents, EmbeddingFunction, Embeddings

from rag_secure import db
from rag_secure.ingest import ingest, open_collection
from rag_secure.retriever import retrieve

WORDS = ["budget", "deploy", "holiday"]


class KeywordEmbedder(EmbeddingFunction):
    """One dimension per keyword, so a text is closest to a question that shares its keyword."""

    def __init__(self):
        pass

    def __call__(self, input: Documents) -> Embeddings:
        return [[float(w in t.lower()) + 0.01 for w in WORDS] for t in input]

    @staticmethod
    def name():
        return "keyword"

    def get_config(self):
        return {}

    @staticmethod
    def build_from_config(config):
        return KeywordEmbedder()


@pytest.fixture
def store(tmp_path):
    docs = tmp_path / "docs"
    for group, text in {
        "finance": "budget",  # the closest possible match for a budget question
        "engineering": "deploy",
        "public": "holiday",
    }.items():
        (docs / group).mkdir(parents=True)
        (docs / group / f"{text}.md").write_text(text, encoding="utf-8")
    ingest(docs, tmp_path / "c", tmp_path / "t.sqlite", 100, 0, KeywordEmbedder())
    return open_collection(tmp_path / "c", KeywordEmbedder()), db.connect(tmp_path / "t.sqlite")


def test_forbidden_chunk_is_never_returned_even_when_closest(store):
    # Control: with finance allowed, the finance chunk really is the closest match.
    allowed = retrieve(*store, "budget", ["public", "finance"], k=3)
    assert allowed[0]["group"] == "finance"
    # The key test: same question, finance not allowed.
    blocked = retrieve(*store, "budget", ["public", "engineering"], k=3)
    assert blocked and all(h["group"] != "finance" for h in blocked)
    assert {h["group"] for h in blocked} <= {"public", "engineering"}


def test_empty_groups_returns_nothing(store):
    assert retrieve(*store, "budget", [], k=3) == []


def test_every_group_combination_stays_inside_its_groups(store):
    groups = ["public", "engineering", "finance"]
    for allowed in ([], ["public"], ["public", "finance"], groups):
        for q in ("budget", "deploy", "holiday"):
            assert {h["group"] for h in retrieve(*store, q, allowed, k=5)} <= set(allowed)


def test_quarantined_document_is_never_returned_and_release_restores_it(store):
    _, conn = store
    db.set_quarantine(conn, "finance/budget.md")
    assert all(h["doc_id"] != "finance/budget.md" for h in retrieve(*store, "budget", ["finance", "public"], k=5))
    assert retrieve(*store, "budget", ["finance"], k=5) == []
    db.set_quarantine(conn, "finance/budget.md", on=False)
    assert retrieve(*store, "budget", ["finance"], k=5)[0]["doc_id"] == "finance/budget.md"


def test_quarantine_needs_no_argument_from_the_caller(store):
    """Fail closed: the retriever reads the flag itself. There is no parameter to forget."""
    db.set_quarantine(store[1], "finance/budget.md")
    assert retrieve(*store, "budget", ["finance"]) == []


def test_unknown_document_cannot_be_quarantined(store):
    with pytest.raises(KeyError):
        db.set_quarantine(store[1], "finance/typo.md")


def test_quarantine_survives_a_changed_file(tmp_path, store):
    _, conn = store
    db.set_quarantine(conn, "finance/budget.md")
    (tmp_path / "docs" / "finance" / "budget.md").write_text("budget budget", encoding="utf-8")
    ingest(tmp_path / "docs", tmp_path / "c", tmp_path / "t.sqlite", 100, 0, KeywordEmbedder())
    assert db.quarantined_docs(conn) == ["finance/budget.md"]
    assert retrieve(*store, "budget", ["finance"]) == []


def test_old_database_gets_the_quarantine_column(tmp_path):
    import sqlite3

    old = sqlite3.connect(tmp_path / "old.sqlite")
    old.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, grp TEXT NOT NULL, sha256 TEXT NOT NULL)")
    old.execute("INSERT INTO documents VALUES ('public/a.md', 'public', 'x')")
    old.commit()
    old.close()
    conn = db.connect(tmp_path / "old.sqlite")
    assert db.quarantined_docs(conn) == []
    db.set_quarantine(conn, "public/a.md")
    assert db.quarantined_docs(conn) == ["public/a.md"]


def test_threshold_drops_far_chunks(store):
    near = retrieve(*store, "holiday", ["public", "finance"], k=5, threshold=0.1)
    assert [h["group"] for h in near] == ["public"]
