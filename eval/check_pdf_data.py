"""Checks the separate PDF test set: files, canaries and questions. Run: python eval/check_pdf_data.py"""

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from rag_secure.ingest import read_pages

CANARY = re.compile(r"CANARY-(?:ENG|FIN)-[0-9a-f]{8}")
FOLDER = {"ENG": "engineering", "FIN": "finance"}
GROUPS = {"guest": {"public"}, "eng": {"public", "engineering"}, "fin": {"public", "finance"},
          "admin": {"public", "engineering", "finance"}}
ABSENT_FROM_ALL_DOCUMENTS = ("gym", "wi-fi", "wifi")


def check(root=ROOT):
    pdf_dir, errors = root / "data" / "docs_pdf", []
    pages = {p.relative_to(pdf_dir).as_posix(): read_pages(p) for p in sorted(pdf_dir.rglob("*.pdf"))}
    if len(pages) != 6:
        errors.append(f"expected 6 PDFs, found {len(pages)}")
    seen = {}
    for doc, doc_pages in pages.items():
        group = doc.split("/")[0]
        found = [(n, c) for n, text in doc_pages for c in CANARY.findall(text)]
        if group == "public" and found:
            errors.append(f"canary in public document {doc}")
        if group in FOLDER.values():
            if len(found) != 1:
                errors.append(f"{doc} has {len(found)} canaries, expected 1")
            for n, c in found:
                if FOLDER[c.split("-")[1]] != group:
                    errors.append(f"canary {c} is in the wrong folder ({doc})")
                if c in seen:
                    errors.append(f"canary {c} appears twice ({seen[c]} and {doc})")
                seen[c] = doc
        for n, text in doc_pages:
            if len(text) < 20:
                errors.append(f"{doc} page {n} has almost no text")
    questions = [json.loads(line) for line in (root / "eval" / "pdf_questions.jsonl").read_text("utf-8").splitlines()]
    if len({q["id"] for q in questions}) != len(questions):
        errors.append("question ids are not unique")
    all_text = " ".join(t for ps in pages.values() for _, t in ps).lower()
    for q in questions:
        if CANARY.search(q["question"]):
            errors.append(f"{q['id']} mentions a canary")
        if q["asker"] not in GROUPS:
            errors.append(f"{q['id']} has an unknown asker")
        if q["type"] == "negative":
            if any(word in all_text for word in ABSENT_FROM_ALL_DOCUMENTS):
                errors.append("a negative question's topic appears in a document")
            continue
        doc, page = q["gold_doc"], q["gold_page"]
        if doc not in pages or not 1 <= page <= len(pages[doc]):
            errors.append(f"{q['id']} points at a missing page ({doc} page {page})")
            continue
        if q["gold_chunk_hint"] not in pages[doc][page - 1][1]:
            errors.append(f"{q['id']} hint is not on {doc} page {page}")
        may_read = doc.split("/")[0] in GROUPS[q["asker"]]
        if (q["type"] == "answerable") != may_read:
            errors.append(f"{q['id']} is {q['type']} but the asker {'may' if may_read else 'may not'} read the document")
    counts = Counter(q["type"] for q in questions)
    if counts != {"answerable": 6, "cross_group": 4, "negative": 2}:
        errors.append(f"unexpected question counts {dict(counts)}")
    return errors, pages, questions


def main():
    errors, pages, questions = check()
    for e in errors:
        print("ERROR:", e)
    print(f"{len(pages)} PDFs, {sum(len(p) for p in pages.values())} pages, {len(questions)} questions,",
          dict(Counter(q["type"] for q in questions)))
    print("OK" if not errors else f"{len(errors)} problem(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
