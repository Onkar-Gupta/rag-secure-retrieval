"""Check the pre-registered data: documents, canaries and questions. Standard library only."""
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "data" / "docs"
CANARY = re.compile(r"CANARY-(?:ENG|FIN)-[0-9a-f]{8}")
FOLDER = {"ENG": "engineering", "FIN": "finance"}


def check(root=ROOT):
    docs_dir = root / "data" / "docs"
    errors = []
    texts = {p.relative_to(docs_dir).as_posix(): p.read_text(encoding="utf-8")
             for p in docs_dir.rglob("*") if p.suffix in (".md", ".txt") and p.name != "LICENSE-DATA.txt"}
    # canaries: one per eng/fin doc, unique, in the right folder, none in public
    seen = {}
    for path, text in texts.items():
        found = CANARY.findall(text)
        group = path.split("/")[0]
        if group == "public" and found:
            errors.append(f"canary in public document {path}")
        if group in FOLDER.values() and len(found) != 1:
            errors.append(f"{path} has {len(found)} canaries, expected 1")
        for c in found:
            if c in seen and seen[c] != path:
                errors.append(f"canary {c} appears in {seen[c]} and {path}")
            seen[c] = path
            if FOLDER[c.split("-")[1]] != group:
                errors.append(f"canary {c} is in the wrong folder: {path}")
    questions = [json.loads(line) for line in
                 (root / "eval" / "questions.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    ids = Counter(q["id"] for q in questions)
    errors += [f"duplicate question id {i}" for i, n in ids.items() if n > 1]
    for q in questions:
        for g in q["gold_doc_ids"]:
            if g not in texts:
                errors.append(f"{q['id']}: gold doc missing {g}")
            elif q["gold_chunk_hint"] not in texts[g]:
                errors.append(f"{q['id']}: hint not found verbatim in {g}")
        if q["type"] == "negative" and q["gold_doc_ids"]:
            errors.append(f"{q['id']}: negative question has gold docs")
        if q["type"] == "cross_group" and q["asker"] in q["allowed_users"]:
            errors.append(f"{q['id']}: cross_group asker {q['asker']} is allowed")
        if q["type"] != "cross_group" and q["type"] != "negative" and q["asker"] not in q["allowed_users"] \
                and q["type"] != "poison":
            errors.append(f"{q['id']}: asker {q['asker']} not allowed")
        if CANARY.search(json.dumps(q)):
            errors.append(f"{q['id']}: canary string in question")
        if q["split"] not in ("dev", "test"):
            errors.append(f"{q['id']}: bad split")
        if q["type"] == "injection" and q.get("attack_marker") and q["attack_marker"] not in texts[q["gold_doc_ids"][0]]:
            errors.append(f"{q['id']}: marker not in its document")
    types = Counter(q["type"] for q in questions)
    splits = Counter((q["type"], q["split"]) for q in questions)
    groups = Counter(p.split("/")[0] for p in texts)
    return errors, groups, types, splits


def main():
    errors, groups, types, splits = check()
    print("documents per group:", dict(groups))
    print("questions per type:", dict(types))
    print("questions per (type, split):", dict(sorted(splits.items())))
    if errors:
        print("FAILED:\n" + "\n".join(errors))
        return 1
    print("OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
