"""Demo sessions and uploads (fake model, keyword embedder; no Ollama)."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from pdfmaker import make_pdf
from test_serve import NF, build

from rag_secure import demo
from rag_secure.ingest import open_collection


def start(tmp_path, **over):
    client, cfg = build(tmp_path, demo_mode=True, **over)
    return client, cfg


def session(client):
    r = client.post("/session")
    assert r.status_code == 200
    return r.json()


def up(client, key, name, body=b"budget plan notes", **kw):
    headers = {"X-API-Key": key, "X-Filename": name, **kw.pop("headers", {})}
    return client.post("/upload", content=body, headers=headers, **kw)


def ask(client, key, q):
    return client.post("/ask", json={"question": q}, headers={"X-API-Key": key}).json()


def test_demo_off_by_default_has_no_session_route(tmp_path):
    client, _ = build(tmp_path)
    assert client.post("/session").status_code == 404


def test_session_sees_public_and_own_upload_but_not_other_groups(tmp_path):
    client, cfg = start(tmp_path)
    a = session(client)
    assert a["groups"] == ["public", a["group"]]
    assert ask(client, a["key"], "holiday")["found"]  # public
    assert not ask(client, a["key"], "budget")["found"]  # finance is hidden
    assert not ask(client, a["key"], "deploy")["found"]  # engineering is hidden
    assert up(client, a["key"], "notes.md").status_code == 200
    got = ask(client, a["key"], "budget")
    assert got["found"] and got["sources"][0].startswith(f"{a['group']}/notes.md")
    assert (Path(cfg["docs_dir"]) / a["group"] / "notes.md").exists()


def test_one_session_cannot_read_another_sessions_upload(tmp_path):
    client, _ = start(tmp_path)
    a, b = session(client), session(client)
    assert up(client, a["key"], "notes.md").status_code == 200
    r = ask(client, b["key"], "budget")
    assert r["answer"] == NF and r["sources"] == []


def test_upload_ignores_a_group_named_by_the_caller(tmp_path):
    client, cfg = start(tmp_path)
    a = session(client)
    r = up(client, a["key"], "x.md", headers={"X-Group": "finance"}, params={"group": "finance"})
    assert r.status_code == 200
    assert (Path(cfg["docs_dir"]) / a["group"] / "x.md").exists()
    assert not (Path(cfg["docs_dir"]) / "finance" / "x.md").exists()


@pytest.mark.parametrize("name,status", [
    ("../x.pdf", 400), ("a/b.pdf", 400), ("/abs.pdf", 400), ("C:x.pdf", 400), ("a\\b.pdf", 400),
    ("a" * 101 + ".pdf", 400), ("CON.pdf", 400), ("nul.txt", 400), (".hidden.md", 400),
    ("run.exe", 415), ("page.html", 415), ("noextension", 415),
])
def test_bad_file_names_are_refused_and_nothing_is_written(tmp_path, name, status):
    client, cfg = start(tmp_path)
    a = session(client)
    assert up(client, a["key"], name).status_code == status
    assert not list((Path(cfg["docs_dir"]) / a["group"]).glob("*")) if (Path(cfg["docs_dir"]) / a["group"]).exists() else True
    assert not (Path(cfg["docs_dir"]).parent / "x.pdf").exists()


def test_null_byte_in_a_name_is_refused():
    assert demo.clean_name("a\x00b.pdf")[0] == 400


def test_too_large_fourth_file_duplicate_and_corrupt_pdf(tmp_path):
    client, _ = start(tmp_path, demo_max_file_mb=0.001, demo_max_files=3)
    a = session(client)
    assert up(client, a["key"], "big.md", body=b"x" * 2000).status_code == 413
    for n in "123":
        assert up(client, a["key"], f"f{n}.md", body=b"budget").status_code == 200
    assert up(client, a["key"], "f4.md", body=b"budget").status_code == 409  # fourth file
    assert up(client, a["key"], "f1.md", body=b"budget").status_code == 409  # duplicate name
    client2, cfg2 = start(tmp_path / "second")
    b = session(client2)
    assert up(client2, b["key"], "bad.pdf", body=b"this is not a pdf").status_code == 422
    assert not (Path(cfg2["docs_dir"]) / b["group"] / "bad.pdf").exists()
    assert up(client2, b["key"], "empty.md", body=b"").status_code == 400


def test_pdf_upload_is_indexed_with_its_page(tmp_path):
    client, _ = start(tmp_path)
    a = session(client)
    r = up(client, a["key"], "plan.pdf", body=make_pdf(["intro", "budget figures"]))
    assert r.status_code == 200 and r.json()["chunks"] >= 1


def test_keys_missing_wrong_static_and_demo_off_are_refused(tmp_path):
    client, _ = start(tmp_path)
    assert up(client, "", "x.md").status_code == 401
    assert up(client, "wrong", "x.md").status_code == 401
    assert up(client, "k-admin", "x.md").status_code == 403  # a real user, not a session
    off, _ = build(tmp_path / "off")
    assert up(off, "k-admin", "x.md").status_code == 403


def test_demo_full_returns_503(tmp_path):
    client, _ = start(tmp_path, demo_max_sessions=2)
    session(client), session(client)
    assert client.post("/session").status_code == 503


def test_expired_session_is_refused_and_its_files_and_chunks_are_gone(tmp_path):
    client, cfg = start(tmp_path)
    t = [0.0]
    sessions = client.app.state.sessions
    sessions.clock, sessions.ttl = (lambda: t[0]), 10
    a = session(client)
    assert up(client, a["key"], "notes.md").status_code == 200
    col = open_collection(cfg["chroma_dir"], __import__("test_retriever").KeywordEmbedder())
    assert col.get(where={"group": a["group"]})["ids"]
    t[0] = 11
    assert ask_status(client, a["key"]) == 401
    assert not (Path(cfg["docs_dir"]) / a["group"]).exists()
    assert not col.get(where={"group": a["group"]})["ids"]
    import sqlite3
    left = sqlite3.connect(cfg["db_path"]).execute("SELECT COUNT(*) FROM documents WHERE grp=?", (a["group"],)).fetchone()[0]
    assert left == 0


def ask_status(client, key):
    return client.post("/ask", json={"question": "budget"}, headers={"X-API-Key": key}).status_code


def test_stopping_the_server_removes_session_folders_and_a_crash_leftover(tmp_path):
    client, cfg = start(tmp_path)
    leftover = Path(cfg["docs_dir"]) / (demo.PREFIX + "deadbeef")
    leftover.mkdir()
    (leftover / "old.md").write_text("budget", encoding="utf-8")
    with TestClient(client.app) as running:  # runs startup and shutdown
        assert not leftover.exists()
        a = session(running)
        assert up(running, a["key"], "n.md").status_code == 200
        folder = Path(cfg["docs_dir"]) / a["group"]
        assert folder.exists()
    assert not folder.exists()


def test_remove_folders_never_touches_a_real_group(tmp_path):
    (tmp_path / "finance").mkdir()
    demo.remove_folders(tmp_path, ["finance", "../finance"])
    assert (tmp_path / "finance").exists()


def test_page_assets_and_mode_and_me(tmp_path):
    client, _ = start(tmp_path)
    page = client.get("/")
    assert page.status_code == 200 and "<title>Ginger & Simba</title>" in page.text
    for path in ("/ui/app.css", "/ui/app.js", "/ui/fonts/bricolage-latin.woff2"):
        assert client.get(path).status_code == 200
    assert client.get("/mode").json()["demo"] is True
    assert client.get("/me").status_code == 401
    a = session(client)
    me = client.get("/me", headers={"X-API-Key": a["key"]}).json()
    assert me["groups"] == ["public", a["group"]]


def test_mode_when_demo_is_off_and_for_a_real_user(tmp_path):
    client, _ = build(tmp_path)
    assert client.get("/mode").json()["demo"] is False
    assert client.get("/me", headers={"X-API-Key": "k-eng"}).json() == {"name": "eng", "groups": ["public", "engineering"]}


def test_source_context_rebuilds_the_page_and_marks_the_chunk(tmp_path):
    from test_retriever import KeywordEmbedder

    from rag_secure import db as _db
    from rag_secure import source
    from rag_secure.ingest import ingest as _ingest

    docs = tmp_path / "docs" / "public"
    docs.mkdir(parents=True)
    text = "".join(f"sentence {i:03d}. " for i in range(40))
    (docs / "long.md").write_text(text, encoding="utf-8")
    _ingest(tmp_path / "docs", tmp_path / "c", tmp_path / "t.sqlite", 60, 20, KeywordEmbedder())
    conn = _db.connect(tmp_path / "t.sqlite")
    ids = [r[0] for r in conn.execute("SELECT chunk_id FROM chunks ORDER BY chunk_id")]
    for cid in (ids[0], ids[3], ids[-1]):
        got = source.context(conn, cid, 60, 20)
        assert got["before"] + got["highlight"] + got["after"] == text
        assert got["highlight"] == conn.execute("SELECT text FROM chunks WHERE chunk_id=?", (cid,)).fetchone()[0]
    assert source.context(conn, "nope#0000", 60, 20) is None


def test_source_and_file_follow_the_same_group_rules_as_search(tmp_path):
    client, cfg = start(tmp_path)
    a, b = session(client), session(client)
    assert up(client, a["key"], "notes.md", body=b"budget plan notes").status_code == 200
    chunk = f"{a['group']}/notes.md#0000"
    doc = f"{a['group']}/notes.md"
    own = client.get("/source", params={"chunk": chunk}, headers={"X-API-Key": a["key"]})
    assert own.status_code == 200 and own.json()["highlight"] == "budget plan notes" and own.json()["kind"] == "text"
    f = client.get("/file", params={"doc": doc}, headers={"X-API-Key": a["key"]})
    assert f.status_code == 200 and f.content == b"budget plan notes"
    for path, params in (("/source", {"chunk": chunk}), ("/file", {"doc": doc})):  # another session: same 404 as missing
        other = client.get(path, params=params, headers={"X-API-Key": b["key"]})
        missing = client.get(path, params={k: v + "x" for k, v in params.items()}, headers={"X-API-Key": b["key"]})
        assert other.status_code == 404 and other.json() == missing.json()
        assert client.get(path, params=params).status_code == 401
    # a session cannot read the engineering document, and admin can; a quarantined one is hidden from everyone
    eng_chunk, eng_doc = "engineering/deploy.md#0000", "engineering/deploy.md"
    assert client.get("/source", params={"chunk": eng_chunk}, headers={"X-API-Key": a["key"]}).status_code == 404
    assert client.get("/source", params={"chunk": eng_chunk}, headers={"X-API-Key": "k-admin"}).status_code == 200
    from rag_secure import db as _db
    _db.set_quarantine(_db.connect(cfg["db_path"]), eng_doc)
    assert client.get("/file", params={"doc": eng_doc}, headers={"X-API-Key": "k-admin"}).status_code == 404
    for bad in ("../w/t.sqlite", "..\\w\t.sqlite", "/etc/passwd", "", "public/../../w/t.sqlite"):
        assert client.get("/file", params={"doc": bad}, headers={"X-API-Key": "k-admin"}).status_code == 404


def test_pdf_source_reports_the_right_page(tmp_path):
    client, _ = start(tmp_path)
    a = session(client)
    assert up(client, a["key"], "plan.pdf", body=make_pdf(["intro page", "budget figures page"])).status_code == 200
    page2 = client.post("/ask", json={"question": "budget"}, headers={"X-API-Key": a["key"]}).json()["sources"][0]
    got = client.get("/source", params={"chunk": page2}, headers={"X-API-Key": a["key"]}).json()
    assert got["kind"] == "pdf" and got["page"] == 2 and "budget" in got["highlight"]
    pdf = client.get("/file", params={"doc": got["doc_id"]}, headers={"X-API-Key": a["key"]})
    assert pdf.headers["content-type"] == "application/pdf" and pdf.content[:4] == b"%PDF"
