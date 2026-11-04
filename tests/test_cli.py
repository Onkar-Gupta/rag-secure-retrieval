import pytest

from rag_secure import __version__
from rag_secure.cli import main


def test_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == __version__


def test_quarantine_command(tmp_path, capsys):
    from rag_secure import db

    dbfile = tmp_path / "t.sqlite"
    conn = db.connect(dbfile)
    conn.execute("INSERT INTO documents (doc_id, grp, sha256) VALUES ('finance/a.md', 'finance', 'x')")
    conn.commit()
    cfg = tmp_path / "config.yaml"
    cfg.write_text(f"db_path: {dbfile.as_posix()}" + chr(10), encoding="utf-8")
    main(["--config", str(cfg), "quarantine", "finance/a.md"])
    assert db.quarantined_docs(conn) == ["finance/a.md"]
    main(["--config", str(cfg), "quarantine", "finance/a.md", "--release"])
    assert db.quarantined_docs(conn) == []
    with pytest.raises(SystemExit) as exc:
        main(["--config", str(cfg), "quarantine", "finance/nope.md"])
    assert "unknown document" in str(exc.value)


def test_ask_rejects_unknown_user_and_bad_questions_before_any_model_call(tmp_path):
    cfg = tmp_path / "config.yaml"
    users = tmp_path / "users.yaml"
    users.write_text(
        "users:\n  guest:\n    groups: [public]\n    api_key_hash: '" + "0" * 64 + "'\n", encoding="utf-8")
    cfg.write_text(f"users_file: {users.as_posix()}\nmax_question_chars: 20\n", encoding="utf-8")
    with pytest.raises(SystemExit, match="unknown user"):
        main(["--config", str(cfg), "ask", "hello", "--user", "nobody"])
    with pytest.raises(SystemExit, match="longer than 20"):
        main(["--config", str(cfg), "ask", "x" * 30, "--user", "guest"])
    with pytest.raises(SystemExit, match="control or invisible"):
        main(["--config", str(cfg), "ask", "hi" + chr(0x200B) + "there", "--user", "guest"])


def test_new_key_prints_a_key_once_and_a_matching_quoted_hash_line(capsys):
    import re

    from rag_secure import security

    main(["new-key"])
    out = capsys.readouterr().out
    key = re.search(r"give it to the user\): (\S+)", out).group(1)
    line = re.search(r'api_key_hash: "([0-9a-f]{64})"', out).group(1)
    assert security.hash_key(key) == line and key not in line
