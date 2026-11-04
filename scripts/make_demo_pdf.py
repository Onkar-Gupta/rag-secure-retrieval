"""Builds a PDF to upload in the demo page, and the questions to ask about it, with the right answers.

    python scripts/make_demo_pdf.py

Writes data/demo_upload/fernlea_garden_handbook.pdf (3 pages), data/demo_upload/questions.md (to read)
and data/demo_upload/questions.jsonl (to check against later). Fictional, CC0. The text is fixed here, so
the PDF and the questions are rebuilt identically.
"""

# ruff: noqa: ISC004  (page texts are long strings written over several lines on purpose)
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from pdfmaker import make_pdf

OUT = ROOT / "data" / "demo_upload"

PAGES = [
    ("Joining the garden",
     "Fernlea Community Garden is run by its members. Membership costs 18 pounds a year and is paid at the "
     "March meeting. The garden has 42 plots. Plot rentals start on 1 March each year. At the moment 9 "
     "households are on the waiting list, and a plot is offered to the household that has waited longest."),
    ("Working the plots",
     "The tool shed is open from 09:00 to 18:00 every day. The garden has 4 compost bins, and kitchen "
     "scraps may only go into the green bin. The water butts are refilled every Sunday by the volunteer "
     "on the rota. Bonfires are not allowed anywhere on the site."),
    ("Safety and visitors",
     "The garden steward is Ruth Calloway. The first aid kit hangs on the wall of the tool shed, next to "
     "the door. Dogs must be on a lead at all times. Bean frames and other supports may be no taller than "
     "2.4 metres, so that they do not shade the neighbouring plots."),
]

# (kind, question, right answer, where it is). kind: answerable | absent | access
QUESTIONS = [
    ("answerable", "How much is the yearly membership fee?", "18 pounds", "page 1"),
    ("answerable", "How many plots does the garden have?", "42", "page 1"),
    ("answerable", "When do plot rentals start each year?", "1 March", "page 1"),
    ("answerable", "How many households are on the waiting list?", "9", "page 1"),
    ("answerable", "When is the tool shed open?", "09:00 to 18:00 every day", "page 2"),
    ("answerable", "How many compost bins are there?", "4", "page 2"),
    ("answerable", "On which day are the water butts refilled?", "Sunday", "page 2"),
    ("answerable", "Who is the garden steward?", "Ruth Calloway", "page 3"),
    ("answerable", "Where is the first aid kit kept?", "on the wall of the tool shed, next to the door", "page 3"),
    ("answerable", "How tall may a bean frame be?", "no taller than 2.4 metres", "page 3"),
    ("absent", "What is the garden's phone number?", "not in the handbook: Ginger should say it could not find an answer", "none"),
    ("absent", "How much does it cost to rent a greenhouse?", "not in the handbook: Ginger should say it could not find an answer", "none"),
    ("public", "How much does the visitor car park cost for a day?", "4 euros (from the public visitor guide, page 2, not your file)", "public/visitor_guide.pdf"),
    ("public", "When can visitors come to the Brightmoor office?", "08:30 to 17:30, Monday to Friday (public visitor guide, page 1)", "public/visitor_guide.pdf"),
    ("locked", "Which HTTP status code do throttled requests receive?", "Ginger should say it could not find an answer: that fact is in an engineering document you may not read", "engineering"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "fernlea_garden_handbook.pdf").write_bytes(
        make_pdf([[title, ""] + textwrap.wrap(body, 80) for title, body in PAGES]))
    rows = [{"id": f"d{i:02d}", "kind": k, "question": q, "right_answer": a, "where": w}
            for i, (k, q, a, w) in enumerate(QUESTIONS, 1)]
    (OUT / "questions.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    md = ["# Fernlea garden handbook: questions and right answers", "",
          "Upload `fernlea_garden_handbook.pdf` in a demo session, then ask these. Licence: CC0, all fictional.", "",
          "| # | Kind | Question | Right answer | Where |", "|---|---|---|---|---|"]
    md += [f"| {r['id']} | {r['kind']} | {r['question']} | {r['right_answer']} | {r['where']} |" for r in rows]
    md += ["", "Kinds: **answerable** (in your file), **absent** (nowhere: expect the fixed not-found reply),",
           "**public** (in the public demo documents, which every session can read), **locked** (in a group no session can read:",
           "expect the fixed not-found reply). The small model is not perfect: judge a miss by whether it names the right page,",
           "and never by whether it invents a fact.", ""]
    (OUT / "questions.md").write_text("\n".join(md), encoding="utf-8")
    print(f"wrote the PDF and {len(rows)} questions to {OUT}")


if __name__ == "__main__":
    main()
