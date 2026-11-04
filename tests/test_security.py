"""Users, API keys, question checks, and who uploaded each document."""

import sqlite3
from pathlib import Path

import pytest
from test_ingest import FakeEmbedder

from rag_secure import db, security
from rag_secure.ingest import ingest

USERS = Path(__file__).parent.parent / "eval" / "users.yaml"


@pytest.fixture(scope="module")
def users():
    return security.load_users(USERS)


def test_every_demo_user_maps_to_its_own_groups(users):
    expected = {"guest": ["public"], "eng": ["public", "engineering"],
                "fin": ["public", "finance"], "admin": ["public", "engineering", "finance"]}
    for name, groups in expected.items():
        assert security.user_for_key(users, users[name]["api_key"]) == (name, groups)


@pytest.mark.parametrize("bad", [None, "", "wrong-key", "TBC-key-guest ", "tbc-key-guest", 123, ["x"]])
def test_unknown_or_malformed_keys_are_rejected(users, bad):
    assert security.user_for_key(users, bad) is None


def test_a_key_never_unlocks_another_users_groups(users):
    name, groups = security.user_for_key(users, users["guest"]["api_key"])
    assert name == "guest" and "finance" not in groups and "engineering" not in groups


def test_good_question_is_tidied():
    assert security.check_question("  What is\n the   budget?\t", 100) == "What is the budget?"


@pytest.mark.parametrize("bad, why", [
    ("", "empty"),
    ("   \n\t ", "empty"),
    ("x" * 101, "longer than 100"),
    ("hello" + chr(0) + "world", "U[+]0000"),
    ("hide" + chr(0x200B) + "me", "U[+]200B"),
    ("flip" + chr(0x202E) + "text", "U[+]202E"),
])
def test_bad_questions_are_rejected_with_a_reason(bad, why):
    with pytest.raises(ValueError, match=why):
        security.check_question(bad, 100)


@pytest.mark.parametrize("bad", [None, 42, ["x"]])
def test_non_text_questions_are_rejected(bad):
    with pytest.raises(TypeError):
        security.check_question(bad, 100)


def test_length_limit_is_exact_and_counts_after_tidying():
    assert security.check_question("x" * 100, 100) == "x" * 100
    assert security.check_question("x" * 50 + " " * 400 + "y" * 49, 100).count("x") == 50


def test_uploader_is_recorded_and_updated_on_change(tmp_path):
    docs = tmp_path / "docs"
    (docs / "public").mkdir(parents=True)
    f = docs / "public" / "a.md"
    f.write_text("x" * 25, encoding="utf-8")
    ingest(docs, tmp_path / "c", tmp_path / "t.sqlite", 10, 3, FakeEmbedder(), uploader="admin")
    conn = sqlite3.connect(tmp_path / "t.sqlite")
    assert conn.execute("SELECT uploader FROM documents").fetchone() == ("admin",)
    f.write_text("y" * 25, encoding="utf-8")
    ingest(docs, tmp_path / "c", tmp_path / "t.sqlite", 10, 3, FakeEmbedder(), uploader="eng")
    assert conn.execute("SELECT uploader FROM documents").fetchone() == ("eng",)
    # an unchanged file is skipped, so its recorded uploader stays
    ingest(docs, tmp_path / "c", tmp_path / "t.sqlite", 10, 3, FakeEmbedder(), uploader="fin")
    assert conn.execute("SELECT uploader FROM documents").fetchone() == ("eng",)


def test_old_database_without_uploader_column_is_upgraded(tmp_path):
    old = sqlite3.connect(tmp_path / "old.sqlite")
    old.execute("CREATE TABLE documents (doc_id TEXT PRIMARY KEY, grp TEXT NOT NULL, sha256 TEXT NOT NULL)")
    old.execute("INSERT INTO documents VALUES ('public/a.md', 'public', 'x')")
    old.commit()
    old.close()
    conn = db.connect(tmp_path / "old.sqlite")
    assert conn.execute("SELECT uploader, quarantined FROM documents").fetchone() == (None, 0)
