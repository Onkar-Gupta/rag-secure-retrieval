"""The HTTP service, with a fake model and a tiny keyword embedder (no Ollama, no model download)."""

import re
import sqlite3

import pytest
from fastapi.testclient import TestClient
from test_retriever import KeywordEmbedder

from rag_secure import security, serve
from rag_secure.ingest import ingest, open_collection

NF = "I could not find an answer in the documents you can access."
USERS = {
    "guest": {"groups": ["public"], "api_key_hash": security.hash_key("k-guest")},
    "eng": {"groups": ["public", "engineering"], "api_key_hash": security.hash_key("k-eng")},
    "admin": {"groups": ["public", "engineering", "finance"], "api_key_hash": security.hash_key("k-admin")},
}
DOCS = {"finance": "budget", "engineering": "deploy", "public": "holiday"}


def fake_llm(system, user):
    """Answers by citing the first chunk in the context, like a well-behaved model."""
    first = re.search(r"<<<DOC (.+?)>>>", user)
    return f"Answer from context [{first.group(1)}]." if first else NF


def build(tmp_path, docs=DOCS, llm=fake_llm, **cfg_over):
    root = tmp_path / "w"
    for group, word in docs.items():
        (root / "docs" / group).mkdir(parents=True)
        (root / "docs" / group / f"{word}.md").write_text(word, encoding="utf-8")
    cfg = {"docs_dir": str(root / "docs"), "chroma_dir": str(root / "c"), "db_path": str(root / "t.sqlite"),
           "chunk_size": 100, "chunk_overlap": 0, "top_k": 3, "relevance_threshold": 0.5,
           "not_found_response": NF, "max_question_chars": 100, "admin_users": ["admin"],
           "api_key_header": "X-API-Key", "log_question_text": False, **cfg_over}
    ingest(cfg["docs_dir"], cfg["chroma_dir"], cfg["db_path"], 100, 0, KeywordEmbedder())
    col = open_collection(cfg["chroma_dir"], KeywordEmbedder())
    return TestClient(serve.create_app(cfg, USERS, col, llm, KeywordEmbedder())), cfg


def post(client, key, question, **extra):
    headers = {"X-API-Key": key} if key else {}
    return client.post("/ask", json={"question": question, **extra}, headers=headers)


@pytest.fixture
def app(tmp_path):
    return build(tmp_path)


def test_health_needs_no_key_and_reveals_nothing(app):
    r = app[0].get("/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


@pytest.mark.parametrize("key", [None, "", "wrong", "K-GUEST"])
def test_missing_or_wrong_key_gets_the_same_401(app, key):
    r = post(app[0], key, "holiday")
    assert r.status_code == 401 and r.json() == {"detail": "invalid or missing API key"}


def test_a_user_with_access_gets_a_cited_answer(app):
    r = post(app[0], "k-eng", "deploy")
    assert r.status_code == 200
    body = r.json()
    assert body["found"] is True and body["sources"] == ["engineering/deploy.md#0000"]
    assert "engineering/deploy.md#0000" in body["answer"]


def test_a_user_without_access_gets_the_fixed_reply_and_the_model_is_never_called(tmp_path):
    def never(system, user):
        raise AssertionError("the model must not be called")

    client, _ = build(tmp_path, llm=never)
    r = post(client, "k-guest", "budget")
    assert r.status_code == 200
    assert r.json() == {"answer": NF, "sources": [], "found": False, "provenance": []}
    assert "finance" not in r.text and "budget.md" not in r.text


def test_explain_shows_only_the_callers_own_chunks_with_flags(app):
    body = post(app[0], "k-eng", "deploy", explain=True).json()
    why = body["explanation"]
    assert why["outcome"] == "answered" and why["cutoff"] == 0.5
    assert {h["group"] for h in why["retrieved"]} <= {"public", "engineering"}
    top = why["retrieved"][0]
    assert top["chunk_id"] == "engineering/deploy.md#0000" and top["used"] and top["cited"]
    assert top["snippet"] == "deploy" and top["distance"] == pytest.approx(0, abs=1e-3)
    assert "explanation" not in post(app[0], "k-eng", "deploy").json()  # off unless asked


def test_a_guest_reply_is_identical_whether_or_not_a_finance_document_exists(tmp_path):
    """The no-leak property: nothing a guest receives depends on documents they may not see."""
    with_finance, _ = build(tmp_path / "a")
    without_finance, _ = build(tmp_path / "b", docs={"engineering": "deploy", "public": "holiday"})
    for question in ("budget", "holiday", "what is the budget", "zzz"):
        a = post(with_finance, "k-guest", question, explain=True)
        b = post(without_finance, "k-guest", question, explain=True)
        assert a.status_code == b.status_code == 200
        assert a.json() == b.json(), question


@pytest.mark.parametrize("question, why", [
    ("x" * 101, "longer than 100"), ("   ", "empty"), ("hi" + chr(0x200B) + "there", "U[+]200B"),
])
def test_bad_questions_get_422_with_a_reason(app, question, why):
    r = post(app[0], "k-eng", question)
    assert r.status_code == 422 and re.search(why, r.json()["detail"])


def test_wrong_types_are_rejected_before_any_work(app):
    r = app[0].post("/ask", json={"question": 42}, headers={"X-API-Key": "k-eng"})
    assert r.status_code == 422
    assert app[0].post("/ask", json={}, headers={"X-API-Key": "k-eng"}).status_code == 422


def test_model_down_gives_a_clean_503(tmp_path):
    def down(system, user):
        raise RuntimeError("Ollama is not reachable at http://localhost:11434")

    client, _ = build(tmp_path, llm=down)
    r = post(client, "k-eng", "deploy")
    assert r.status_code == 503 and r.json() == {"detail": "the language model is not available"}
    assert "localhost" not in r.text  # internal addresses stay internal


def test_ingest_is_admin_only_and_records_the_uploader(app):
    client, cfg = app
    assert client.post("/ingest").status_code == 401
    assert client.post("/ingest", headers={"X-API-Key": "k-guest"}).status_code == 403
    assert client.post("/ingest", headers={"X-API-Key": "k-eng"}).status_code == 403
    new = f"{cfg['docs_dir']}/public/extra.md"
    with open(new, "w", encoding="utf-8") as f:
        f.write("extra")
    r = client.post("/ingest", headers={"X-API-Key": "k-admin"})
    assert r.status_code == 200 and r.json()["added"] == 1
    conn = sqlite3.connect(cfg["db_path"])
    assert conn.execute("SELECT uploader FROM documents WHERE doc_id='public/extra.md'").fetchone() == ("admin",)


def test_query_log_keeps_a_hash_not_the_text_by_default(app):
    client, cfg = app
    post(client, "k-eng", "deploy")
    post(client, "k-guest", "budget")
    rows = sqlite3.connect(cfg["db_path"]).execute(
        "SELECT user, question_hash, question_text, chunk_ids, found FROM query_log ORDER BY id").fetchall()
    assert [r[0] for r in rows] == ["eng", "guest"]
    assert all(r[1] and len(r[1]) == 16 and r[2] is None for r in rows)
    assert rows[0][3] == "engineering/deploy.md#0000" and rows[0][4] == 1
    assert rows[1][3] == "" and rows[1][4] == 0  # nothing reached the model for the guest


def test_query_log_can_keep_the_text_when_asked(tmp_path):
    client, cfg = build(tmp_path, log_question_text=True)
    post(client, "k-eng", "deploy")
    text = sqlite3.connect(cfg["db_path"]).execute("SELECT question_text FROM query_log").fetchone()
    assert text == ("deploy",)


def test_rejected_requests_leave_no_log_row(app):
    client, cfg = app
    post(client, "wrong", "deploy")
    post(client, "k-eng", "x" * 500)
    assert sqlite3.connect(cfg["db_path"]).execute("SELECT COUNT(*) FROM query_log").fetchone() == (0,)


def test_every_source_carries_provenance_and_the_model_never_sees_it(tmp_path):
    seen = []

    def spy(system, user):
        seen.append(system + user)
        return fake_llm(system, user)

    client, _ = build(tmp_path, llm=spy)
    body = post(client, "k-eng", "deploy").json()
    assert body["sources"] == ["engineering/deploy.md#0000"]
    [p] = body["provenance"]
    assert set(p) == {"chunk_id", "doc_id", "group", "uploader", "ingested_at"}
    assert p["doc_id"] == "engineering/deploy.md" and p["group"] == "engineering" and p["uploader"] == "cli"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", p["ingested_at"])
    assert all("uploader" not in text and "ingested_at" not in text for text in seen)  # response-only data


def test_provenance_follows_the_uploader_and_a_quarantined_source_never_appears(app):
    client, cfg = app
    from rag_secure import db

    db.set_quarantine(db.connect(cfg["db_path"]), "engineering/deploy.md")
    body = post(client, "k-eng", "deploy").json()
    assert body["sources"] == [] and body["provenance"] == [] and body["found"] is False
