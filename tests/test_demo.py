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
