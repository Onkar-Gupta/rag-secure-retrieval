"""Builds the three PDFs for the static replay page, and the 15 test questions with the right answers.

    python scripts/make_replay_pdfs.py

Writes data/replay/<topic>.pdf (3 pages each) and data/replay/questions.jsonl. The text is original,
CC0, and states only widely published facts. It is fixed here, so everything is rebuilt identically.
Each topic has 4 questions the PDF answers and 1 it does not (the right reply is "not found").
"""

# ruff: noqa: ISC004  (page texts are long strings written over several lines on purpose)
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tests"))
from pdfmaker import make_pdf

OUT = ROOT / "data" / "replay"

TOPICS = {
    "general_knowledge": [
        ("Places",
         "The capital of Australia is Canberra, not Sydney or Melbourne. Mount Everest is the highest "
         "mountain above sea level, at 8,849 metres. The Pacific Ocean is the largest ocean on Earth. "
         "Vatican City is the smallest country in the world by area."),
        ("Inventions and events",
         "The World Wide Web was proposed by Tim Berners-Lee in 1989, while he worked at CERN. The first "
         "people to walk on the Moon were Neil Armstrong and Buzz Aldrin, during the Apollo 11 mission in "
         "July 1969. The Berlin Wall came down in November 1989."),
        ("The body and the calendar",
         "An adult human body has 206 bones. A leap year has 366 days and comes round every four years, "
         "with some exceptions for century years. There are seven continents: Africa, Antarctica, Asia, "
         "Australia, Europe, North America and South America."),
    ],
    "literature": [
        ("Novels of the 1800s",
         "Pride and Prejudice was written by Jane Austen and published in 1813. It follows Elizabeth Bennet "
         "and her changing opinion of the proud Mr Darcy. Frankenstein was written by Mary Shelley and first "
         "published in 1818. Its main character is the scientist Victor Frankenstein."),
        ("The sea and the stage",
         "Moby-Dick was written by Herman Melville and published in 1851. The story is told by a sailor who "
         "asks the reader to call him Ishmael, and it follows Captain Ahab's hunt for a white whale. Hamlet "
         "is a play by William Shakespeare. It is set at the castle of Elsinore in Denmark."),
        ("A detective",
         "Sherlock Holmes was created by Arthur Conan Doyle. He first appeared in the novel A Study in "
         "Scarlet, published in 1887. Holmes lives at 221B Baker Street in London and works with his friend "
         "Doctor John Watson."),
    ],
    "science": [
        ("Physics",
         "Water boils at 100 degrees Celsius at sea level. The speed of light in a vacuum is 299,792,458 "
         "metres per second. Light from the Sun takes a little over 8 minutes to reach the Earth."),
        ("The solar system",
         "The solar system has eight planets. Jupiter is the largest planet. The planet closest to the Sun "
         "is Mercury. The Earth takes about 365 days to go once round the Sun."),
        ("Life and chemistry",
         "James Watson and Francis Crick described the double helix structure of DNA in 1953. Plants use "
         "photosynthesis to turn light, water and carbon dioxide into sugars and oxygen. Carbon has the "
         "atomic number 6."),
    ],
}

# (topic, kind, question, right answer, where). kind: answerable | absent
QUESTIONS = [
    ("general_knowledge", "answerable", "What is the capital of Australia?", "Canberra", "page 1"),
    ("general_knowledge", "answerable", "How tall is Mount Everest?", "8,849 metres", "page 1"),
    ("general_knowledge", "answerable", "Who proposed the World Wide Web, and in which year?", "Tim Berners-Lee, 1989", "page 2"),
    ("general_knowledge", "answerable", "How many bones does an adult human body have?", "206", "page 3"),
    ("general_knowledge", "absent", "What is the population of Canberra?", "not in the document: should say it could not find an answer", "none"),
    ("literature", "answerable", "Who wrote Pride and Prejudice, and when was it published?", "Jane Austen, 1813", "page 1"),
    ("literature", "answerable", "In which year was Frankenstein first published?", "1818", "page 1"),
    ("literature", "answerable", "Who tells the story of Moby-Dick?", "Ishmael", "page 2"),
    ("literature", "answerable", "At which castle is Hamlet set?", "Elsinore", "page 2"),
    ("literature", "absent", "Which actor first played Sherlock Holmes on stage?", "not in the document: should say it could not find an answer", "none"),
    ("science", "answerable", "At what temperature does water boil at sea level?", "100 degrees Celsius", "page 1"),
    ("science", "answerable", "What is the speed of light in a vacuum?", "299,792,458 metres per second", "page 1"),
    ("science", "answerable", "Which planet is the largest?", "Jupiter", "page 2"),
    ("science", "answerable", "In which year did Watson and Crick describe the structure of DNA?", "1953", "page 3"),
    ("science", "absent", "What is the boiling point of mercury?", "not in the document: should say it could not find an answer", "none"),
]


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for topic, pages in TOPICS.items():
        (OUT / f"{topic}.pdf").write_bytes(make_pdf([[t, ""] + textwrap.wrap(b, 80) for t, b in pages]))
    with (OUT / "questions.jsonl").open("w", encoding="utf-8") as f:
        for i, (topic, kind, q, right, where) in enumerate(QUESTIONS, 1):
            f.write(json.dumps({"id": f"r{i:02d}", "topic": topic, "kind": kind, "question": q,
                                "right_answer": right, "where": where}) + "\n")
    print(f"wrote {len(TOPICS)} PDFs and {len(QUESTIONS)} questions to {OUT}")


if __name__ == "__main__":
    main()
