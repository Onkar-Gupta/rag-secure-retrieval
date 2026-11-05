"""Builds the static replay page in docs/ from reports/replay.json (GitHub Pages serves docs/).

    python scripts/build_replay_page.py

Copies the stylesheet, font, mascots and the three PDFs, and writes docs/replay-data.js from the saved run.
docs/index.html and docs/replay.js are written by hand. Nothing here calls a model.
"""

import json
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
UI = ROOT / "rag_secure" / "ui"
OUT = ROOT / "docs"
TOPICS = [
    ("general_knowledge", "General knowledge", "Places, inventions and the human body."),
    ("literature", "Literature", "Famous novels, a play and a detective."),
    ("science", "Science", "Physics, the solar system, DNA and chemistry."),
]


def main():
    run = json.loads((ROOT / "reports" / "replay.json").read_text(encoding="utf-8"))
    (OUT / "fonts").mkdir(parents=True, exist_ok=True)
    (OUT / "pdf").mkdir(exist_ok=True)
    css = (UI / "app.css").read_text(encoding="utf-8").replace("/ui/fonts/", "fonts/")
    (OUT / "app.css").write_text(css, encoding="utf-8")
    shutil.copy(UI / "fonts" / "bricolage-latin.woff2", OUT / "fonts")
    shutil.copy(UI / "fonts" / "OFL.txt", OUT / "fonts")
    shutil.copytree(UI / "img", OUT / "img", dirs_exist_ok=True)
    topics = []
    for tid, title, blurb in TOPICS:
        shutil.copy(ROOT / "data" / "replay" / f"{tid}.pdf", OUT / "pdf")
        qs = []
        for r in (r for r in run["rows"] if r["topic"] == tid):
            qs.append({"id": r["id"], "kind": r["kind"], "question": r["question"], "right": r["right_answer"],
                       "answer": r["answer"], "found": r["found"], "ms": r["latency_ms"],
                       "sources": [{"chunk_id": p["chunk_id"], "page": p["page"], "doc": p["doc_id"].split("/")[-1],
                                    "added": p["ingested_at"], **ps}
                                   for p, ps in zip(r["provenance"], r["passages"])],
                       "working": [{"chunk": h["chunk_id"], "used": h["used"], "cited": h["cited"], "snippet": h["snippet"]}
                                   for h in r["explanation"]["retrieved"]]})
        topics.append({"id": tid, "title": title, "blurb": blurb, "pdf": f"pdf/{tid}.pdf", "questions": qs})
    meta = {"date": run["meta"]["date"][:10], "commit": run["meta"]["commit"][:7], "model": run["settings"]["model"]}
    (OUT / "replay-data.js").write_text("window.REPLAY = " + json.dumps({"meta": meta, "topics": topics}, indent=1) + ";\n",
                                        encoding="utf-8")
    print(f"built {OUT}")


if __name__ == "__main__":
    main()
