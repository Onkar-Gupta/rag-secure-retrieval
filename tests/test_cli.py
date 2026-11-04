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
