import importlib.util
import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("check_pdf_data", ROOT / "eval" / "check_pdf_data.py")
check_pdf_data = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_pdf_data)


def copy_world(tmp_path):
    shutil.copytree(ROOT / "data" / "docs_pdf", tmp_path / "data" / "docs_pdf")
    (tmp_path / "eval").mkdir()
    shutil.copy(ROOT / "eval" / "pdf_questions.jsonl", tmp_path / "eval" / "pdf_questions.jsonl")
    return tmp_path


def test_the_pdf_set_passes_its_own_checks():
    errors, pages, questions = check_pdf_data.check()
    assert errors == [] and len(pages) == 6 and len(questions) == 12


def test_a_hint_that_is_not_on_the_named_page_is_caught(tmp_path):
    root = copy_world(tmp_path)
    path = root / "eval" / "pdf_questions.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[0]["gold_page"] = 3  # the evidence is on page 2
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    errors, *_ = check_pdf_data.check(root)
    assert any("pq01 hint is not on" in e for e in errors)


def test_a_canary_in_a_public_document_is_caught(tmp_path):
    root = copy_world(tmp_path)
    import sys

    sys.path.insert(0, str(ROOT / "tests"))
    from pdfmaker import make_pdf

    (root / "data" / "docs_pdf" / "public" / "leaky.pdf").write_bytes(
        make_pdf([["A public page that wrongly mentions CANARY-ENG-12345678 in its text."]]))
    errors, *_ = check_pdf_data.check(root)
    assert any("canary in public document public/leaky.pdf" in e for e in errors)


def test_a_question_whose_type_disagrees_with_the_askers_access_is_caught(tmp_path):
    root = copy_world(tmp_path)
    path = root / "eval" / "pdf_questions.jsonl"
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    rows[2]["asker"] = "guest"  # pq03 is marked answerable but a guest cannot read engineering
    path.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    errors, *_ = check_pdf_data.check(root)
    assert any("pq03 is answerable but the asker may not read" in e for e in errors)
