"""Freeze guard. The dev tuning, the frozen settings and the single test-split run all assume today's
documents, chunks, questions, prompts and settings. This test fails if any of them changes.

If a change is intended: write a dated Amendment in eval/protocol.md first, rerun the dev split, and
update the constants below in the SAME commit as the Amendment. Never edit them to make a red test green
without that. Hashes use text, not raw bytes, so Windows and Linux line endings give the same result.
The embedder is a fake one: chunking and prompt building do not depend on it.
"""

import hashlib
import json
from pathlib import Path

import yaml
from test_ingest import FakeEmbedder

from rag_secure import db, generator
from rag_secure.ingest import ingest

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "docs"

# Values written on 4 Nov 2026, before any hardening change.
EXPECTED_SETTINGS = {
    "chunk_size": 300, "chunk_overlap": 100, "top_k": 5, "relevance_threshold": 0.6079088449478149,
    "not_found_response": "I could not find an answer in the documents you can access.",
    "model": "phi4-mini:3.8b", "temperature": 0, "seed": 0, "max_tokens": 300,
}
EXPECTED_HASHES = {
    "documents": "14a3f635fae6e217ce7ef0757b49ac17f546247815caf74f264927865d8f5e87",
    "chunks": "9f4b73f9993f9f5be90b76a16bc949d501fcbafbaf24553c073079f0b04127a4",
    "questions": "8ab33e464027af2e5d8f14bef5f46c96f2c845faa5562b9eae89276b431baf11",
    "prompts": "649b00732e5605323afb4a0c86d10ed555dd9e108ebb188de164f2086acbea49",
}


def sha(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def settings():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    return {k: cfg[k] for k in EXPECTED_SETTINGS}


def compute(tmp_path):
    cfg = settings()
    texts = {p.relative_to(DOCS).as_posix(): p.read_text(encoding="utf-8")
             for p in sorted(DOCS.rglob("*")) if p.suffix in (".md", ".txt")}
    questions = (ROOT / "eval" / "questions.jsonl").read_text(encoding="utf-8")
    users = yaml.safe_load((ROOT / "eval" / "users.yaml").read_text(encoding="utf-8"))["users"]
    groups = {name: u["groups"] for name, u in sorted(users.items())}  # keys may change; groups may not

    ingest(DOCS, tmp_path / "c", tmp_path / "t.sqlite", cfg["chunk_size"], cfg["chunk_overlap"], FakeEmbedder())
    conn = db.connect(tmp_path / "t.sqlite")
    rows = conn.execute(
        "SELECT c.chunk_id, c.doc_id, d.grp, c.page, c.text FROM chunks c JOIN documents d USING (doc_id) "
        "ORDER BY c.chunk_id").fetchall()

    prompts = []
    for line in questions.splitlines():
        q = json.loads(line)
        docs = q["gold_doc_ids"] or ["public/company_overview.md"]
        marks = ",".join("?" * len(docs))
        hits = [{"chunk_id": cid, "text": text} for cid, text in conn.execute(
            f"SELECT chunk_id, text FROM chunks WHERE doc_id IN ({marks}) ORDER BY chunk_id LIMIT 5", docs)]
        for delimit in (True, False):
            prompts.append([q["id"], delimit, generator.build_prompt(q["question"], hits, cfg["not_found_response"], delimit)])
    return {
        "documents": sha(texts),
        "chunks": sha([list(r) for r in rows]),
        "questions": sha([questions, groups]),
        "prompts": sha(prompts),
    }


def test_frozen_settings_are_unchanged():
    assert settings() == EXPECTED_SETTINGS


def test_documents_chunks_questions_and_prompts_are_unchanged(tmp_path):
    got = compute(tmp_path)
    assert got == EXPECTED_HASHES, (
        "A frozen input changed. If this is intended, add a dated Amendment to eval/protocol.md, rerun the "
        "dev split, and update EXPECTED_HASHES in the same commit. Differences: "
        + ", ".join(k for k in got if got[k] != EXPECTED_HASHES[k]))


def test_the_guard_notices_a_prompt_change(tmp_path, monkeypatch):
    """The guard is only useful if it can fail: a one-character prompt change must change the prompts hash."""
    real = generator.build_prompt

    def tampered(question, hits, not_found, delimit=True):
        system, user = real(question, hits, not_found, delimit)
        return system + " ", user

    monkeypatch.setattr(generator, "build_prompt", tampered)
    got = compute(tmp_path)
    assert got["prompts"] != EXPECTED_HASHES["prompts"]
    assert got["chunks"] == EXPECTED_HASHES["chunks"]  # and only the prompts hash moved


def test_the_guard_notices_a_document_change(tmp_path, monkeypatch):
    """A one-character change in one document must change the documents and chunks hashes."""
    original = Path.read_text

    def edited(self, *args, **kwargs):
        text = original(self, *args, **kwargs)
        return text + "x" if self.name == "budget_2026.md" else text

    monkeypatch.setattr(Path, "read_text", edited)
    got = compute(tmp_path)
    assert got["documents"] != EXPECTED_HASHES["documents"]
    assert got["chunks"] != EXPECTED_HASHES["chunks"]
