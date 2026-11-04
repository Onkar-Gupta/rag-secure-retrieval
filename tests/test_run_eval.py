"""Unit tests for the evaluation maths and the three conditions (no real model needed)."""

import importlib.util
import sqlite3
from pathlib import Path

import pytest
from test_retriever import KeywordEmbedder

from rag_secure import db
from rag_secure.ingest import ingest, open_collection

_spec = importlib.util.spec_from_file_location(
    "run_eval", Path(__file__).resolve().parent.parent / "eval" / "run_eval.py")
run_eval = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(run_eval)


def test_wilson_and_rule_of_three():
    lo, hi = run_eval.wilson(0, 10)
    assert lo == 0.0 and hi == pytest.approx(0.2775, abs=1e-3)
    zero = run_eval.rate(0, 480)
    assert zero["rule_of_three_upper95"] == pytest.approx(3 / 480)
    assert "rule_of_three_upper95" not in run_eval.rate(3, 480)
    assert run_eval.wilson(0, 0) is None


def test_bootstrap_is_reproducible_and_sensible():
    a, b = [1] * 30 + [0] * 10, [1] * 20 + [0] * 20
    first, second = run_eval.bootstrap_diff(a, b), run_eval.bootstrap_diff(a, b)
    assert first == second
    assert first["mean_diff"] == pytest.approx(0.25)
    assert first["ci95"][0] > 0  # D clearly better than C here
    assert run_eval.bootstrap_diff([1, 0, 1], [1, 0, 1])["ci95"] == [0.0, 0.0]


def test_pick_threshold_maximises_balanced_accuracy_and_breaks_ties_upward():
    t, ba = run_eval.pick_threshold([0.1, 0.2, 0.3], [0.5, 0.9])
    assert (t, ba) == (0.3, 1.0)
    # Cut-offs 0.1 and 0.4 both score 0.75; the tie goes to the larger cut-off.
    assert run_eval.pick_threshold([0.1, 0.4], [0.4, 0.9]) == (0.4, 0.75)


def test_gold_chunk_whole_hint_and_split_hint():
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE chunks (chunk_id TEXT, doc_id TEXT, page INTEGER, text TEXT)")
    conn.executemany("INSERT INTO chunks VALUES (?,?,?,?)", [
        ("d#0", "d", None, "intro text. The budget is 40 million euros"),
        ("d#1", "d", None, "ros per year. Other text"),
        ("d#2", "d", None, "nothing relevant at all"),
    ])
    whole = {"gold_doc_ids": ["d"], "gold_chunk_hint": "intro text."}
    assert run_eval.gold_chunks(whole, conn) == ["d#0"]
    split = {"gold_doc_ids": ["d"], "gold_chunk_hint": "The budget is 40 million euros per year."}
    assert run_eval.gold_chunks(split, conn) == ["d#0"]  # d#0 holds more than half; d#1 holds too little


@pytest.fixture
def store(tmp_path):
    docs = tmp_path / "docs"
    for group, text in {"finance": "budget", "engineering": "deploy", "public": "holiday"}.items():
        (docs / group).mkdir(parents=True)
        (docs / group / f"{text}.md").write_text(text, encoding="utf-8")
    ingest(docs, tmp_path / "c", tmp_path / "t.sqlite", 100, 0, KeywordEmbedder())
    return open_collection(tmp_path / "c", KeywordEmbedder()), db.connect(tmp_path / "t.sqlite")


def test_conditions_a_leaks_while_c_and_d_do_not(store):
    col, conn = store
    vec = KeywordEmbedder()(["budget"])[0]
    guest = ["public"]
    docs = {c: {h["doc_id"] for h in run_eval.search(c, col, conn, "budget", vec, guest, k=3)} for c in "ACD"}
    assert "finance/budget.md" in docs["A"]  # no control: the leak the test must be able to see
    assert docs["C"] == {"public/holiday.md"} == docs["D"]
    leaked = {c: any(run_eval.folder(d) not in guest for d in docs[c]) for c in "ACD"}
    assert leaked == {"A": True, "C": False, "D": False}


def test_condition_c_loses_useful_chunks_that_d_keeps(store):
    """Why D can beat C: with k=1 the closest chunk is finance, so C drops it and has nothing left."""
    col, conn = store
    vec = KeywordEmbedder()(["budget"])[0]
    assert run_eval.search("C", col, conn, "budget", vec, ["public"], k=1) == []
    assert len(run_eval.search("D", col, conn, "budget", vec, ["public"], k=1)) == 1


NF = "I could not find an answer in the documents you can access."


def test_canary_leaks_only_counts_canaries_from_folders_the_user_cannot_see():
    cmap = {"CANARY-FIN-aaaaaaaa": "finance", "CANARY-ENG-bbbbbbbb": "engineering"}
    answer = "see CANARY-FIN-aaaaaaaa and CANARY-ENG-bbbbbbbb and CANARY-FIN-cccccccc"
    assert run_eval.canary_leaks(answer, ["public", "engineering"], cmap) == ["CANARY-FIN-aaaaaaaa", "CANARY-FIN-cccccccc"]
    assert run_eval.canary_leaks("nothing here", ["public"], cmap) == []


def test_generation_rows_and_summary_with_a_fake_model(store):
    col, conn = store
    users = {"guest": {"groups": ["public"]}, "admin": {"groups": ["public", "engineering", "finance"]}}
    cfg = {"top_k": 3, "relevance_threshold": 0.5, "not_found_response": NF}
    qs = [
        {"id": "a1", "question": "holiday", "type": "answerable", "asker": "guest"},
        {"id": "c1", "question": "budget", "type": "cross_group", "asker": "guest"},
        {"id": "n1", "question": "zzz", "type": "negative", "asker": "admin"},
    ]
    vecs = {q["id"]: KeywordEmbedder()([q["question"]])[0] for q in qs}
    gold = {"a1": ["public/holiday.md#0000"]}
    llm_calls = []

    def fake(system, user):
        llm_calls.append(user)
        return "27 days [public/holiday.md#0000]" if "Question: holiday" in user else NF

    rows = run_eval.generation_rows(qs, users, vecs, col, conn, cfg, fake, gold, {}, log=lambda *a, **k: None)
    by = {r["id"]: r for r in rows}
    assert by["a1"]["called_model"] and by["a1"]["cites_gold"] and by["a1"]["sources"] == ["public/holiday.md#0000"]
    # guest asks about the finance budget: nothing passes the cut-off, so the model is never called
    assert not by["c1"]["called_model"] and by["c1"]["is_fixed_reply"] and by["c1"]["model_seconds"] is None
    assert by["n1"]["is_fixed_reply"]
    guest_calls = [u for u in llm_calls if "Question: holiday" in u]  # the only question guest asked the model
    assert guest_calls and all("budget" not in u for u in guest_calls)  # no finance text sent for a guest
    summary = run_eval.summarise(rows)
    assert summary["citation_accuracy_answerable"]["k"] == 1 and summary["citation_accuracy_answerable"]["n"] == 1
    assert summary["not_found_equivalence_cross_group"]["rate"] == 1.0
    assert summary["negative_rejection"]["rate"] == 1.0
    assert summary["canary_leaks_total"] == 0
    assert summary["latency_seconds"]["n"] == summary["model_calls"] == len(llm_calls)


def test_number_support_is_reported_per_row_and_in_the_summary(store):
    col, conn = store
    users = {"admin": {"groups": ["public", "engineering", "finance"]}}
    cfg = {"top_k": 3, "relevance_threshold": 0.5, "not_found_response": NF}
    qs = [{"id": "a1", "question": "holiday", "type": "answerable", "asker": "admin"}]
    vecs = {"a1": KeywordEmbedder()(["holiday"])[0]}
    # the chunk text is the single word 'holiday', so a made-up number cannot be supported
    rows = run_eval.generation_rows(
        qs, users, vecs, col, conn, cfg, lambda s, u: "It is 27 days [public/holiday.md#0000].", {}, {},
        log=lambda *a, **k: None)
    assert rows[0]["number_support"]["counts"]["unsupported"] == 1
    assert rows[0]["number_support"]["unsupported"][0]["missing"] == ["27"]
    summary = run_eval.summarise(rows)["number_support_answerable"]
    assert summary["k"] == 0 and summary["n"] == 1 and summary["sentences_without_numbers"] == 0
