"""The retrieval leak check in miniature: the real sample documents, the real embedding model,
every question asked as every user, condition D. No result may come from a group the user lacks."""

import json
from pathlib import Path

import pytest
import yaml

from rag_secure import db
from rag_secure.ingest import ingest, open_collection
from rag_secure.retriever import retrieve

ROOT = Path(__file__).parent.parent


@pytest.fixture(scope="module")
def store(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("real")
    ingest(ROOT / "data" / "docs", tmp / "c", tmp / "t.sqlite", 500, 100)
    return open_collection(tmp / "c"), db.connect(tmp / "t.sqlite")


def test_no_leaks_for_any_question_and_user(store):
    users = yaml.safe_load((ROOT / "eval" / "users.yaml").read_text(encoding="utf-8"))["users"]
    questions = [
        json.loads(line)["question"]
        for line in (ROOT / "eval" / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert len(questions) == 120
    runs = leaks = 0
    for user in users.values():
        for q in questions:
            hits = retrieve(*store, q, user["groups"], k=5)
            runs += 1
            leaks += sum(h["group"] not in user["groups"] for h in hits)
    assert runs == 480
    assert leaks == 0


def test_admin_can_reach_finance_but_guest_cannot(store):
    q = "What is the total approved budget for 2026?"
    assert any(h["group"] == "finance" for h in retrieve(*store, q, ["public", "finance"], k=5))
    assert all(h["group"] == "public" for h in retrieve(*store, q, ["public"], k=5))


def test_leak_check_can_detect_a_leak(store):
    """Control (condition A): with no filter, the same finance question does return finance chunks."""
    q = "What is the total approved budget for 2026?"
    unfiltered = store[0].query(query_texts=[q], n_results=5)["metadatas"][0]
    assert any(m["group"] == "finance" for m in unfiltered)
