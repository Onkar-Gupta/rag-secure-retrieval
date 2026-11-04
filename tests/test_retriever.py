"""Filtered retrieval. The key regression test: a forbidden chunk never comes back, even when it
is the closest match. Uses real Chroma with a tiny keyword embedder so we control the distances."""

import pytest
from chromadb import Documents, EmbeddingFunction, Embeddings

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
def col(tmp_path):
    docs = tmp_path / "docs"
    for group, text in {
        "finance": "budget",  # the closest possible match for a budget question
        "engineering": "deploy",
        "public": "holiday",
    }.items():
        (docs / group).mkdir(parents=True)
        (docs / group / f"{text}.md").write_text(text, encoding="utf-8")
    ingest(docs, tmp_path / "c", tmp_path / "t.sqlite", 100, 0, KeywordEmbedder())
    return open_collection(tmp_path / "c", KeywordEmbedder())


def test_forbidden_chunk_is_never_returned_even_when_closest(col):
    # Control: with finance allowed, the finance chunk really is the closest match.
    allowed = retrieve(col, "budget", ["public", "finance"], k=3)
    assert allowed[0]["group"] == "finance"
    # The key test: same question, finance not allowed.
    blocked = retrieve(col, "budget", ["public", "engineering"], k=3)
    assert blocked and all(h["group"] != "finance" for h in blocked)
    assert {h["group"] for h in blocked} <= {"public", "engineering"}


def test_empty_groups_returns_nothing(col):
    assert retrieve(col, "budget", [], k=3) == []


def test_every_group_combination_stays_inside_its_groups(col):
    groups = ["public", "engineering", "finance"]
    for allowed in ([], ["public"], ["public", "finance"], groups):
        for q in ("budget", "deploy", "holiday"):
            assert {h["group"] for h in retrieve(col, q, allowed, k=5)} <= set(allowed)


def test_excluded_document_is_never_returned(col):
    hits = retrieve(col, "budget", ["finance", "public"], k=5, exclude_docs=["finance/budget.md"])
    assert all(h["doc_id"] != "finance/budget.md" for h in hits)
    assert retrieve(col, "budget", ["finance"], k=5, exclude_docs=["finance/budget.md"]) == []


def test_threshold_drops_far_chunks(col):
    near = retrieve(col, "holiday", ["public", "finance"], k=5, threshold=0.1)
    assert [h["group"] for h in near] == ["public"]
