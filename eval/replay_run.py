"""Static replay run. Follows the 5 Nov 2026 Amendment "static replay set" in eval/protocol.md. Run once:

    python eval/replay_run.py

Needs Ollama running. Indexes each topic of data/replay/ as its own group in a temporary folder, asks the
15 questions as a reader of that topic only, and saves answers, sources, passages and timings to
reports/replay.json. Judging the answers against the right answers is done by hand afterwards.
"""

import argparse
import json
import shutil
import sys
import tempfile
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import run_eval as ev

from rag_secure import db, generator, ingest, source
from rag_secure.ingest import open_collection

SRC = ROOT / "data" / "replay"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, default=ROOT / "reports" / "replay.json")
    ap.add_argument("--rerun-reason", default=None)
    ap.add_argument("--allow-dirty", action="store_true")
    args = ap.parse_args()
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    ev.frozen_settings()
    ev.check_ollama(cfg["ollama_url"])
    info = ev.meta()
    if info["working_tree_dirty"] and not args.allow_dirty:
        raise SystemExit("The working tree has uncommitted changes. Commit them first.")
    if args.out.exists() and not args.rerun_reason:
        raise SystemExit(f"{args.out} exists. The Amendment allows ONE run; pass --rerun-reason to override.")

    questions = [json.loads(line) for line in (SRC / "questions.jsonl").read_text(encoding="utf-8").splitlines()]
    llm = generator.ollama_llm(cfg["model"], cfg["ollama_url"], cfg["temperature"], cfg["seed"], cfg["max_tokens"])
    rows = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        tmp = Path(t)
        for pdf in SRC.glob("*.pdf"):
            (tmp / "docs" / pdf.stem).mkdir(parents=True, exist_ok=True)
            shutil.copy(pdf, tmp / "docs" / pdf.stem / pdf.name)
        c = dict(cfg, docs_dir=str(tmp / "docs"), chroma_dir=str(tmp / "chroma"), db_path=str(tmp / "r.sqlite"))
        ingest.ingest(c["docs_dir"], c["chroma_dir"], c["db_path"], c["chunk_size"], c["chunk_overlap"])
        col = open_collection(c["chroma_dir"])
        conn = db.connect(c["db_path"])
        for q in questions:
            start = time.perf_counter()
            result, trace = generator.ask_with_trace(q["question"], [q["topic"]], col, conn, c, llm)
            ms = (time.perf_counter() - start) * 1000
            passages = [source.context(conn, cid, c["chunk_size"], c["chunk_overlap"]) for cid in result["sources"]]
            rows.append({**q, "answer": result["answer"], "found": result["found"], "sources": result["sources"],
                         "provenance": db.provenance(conn, result["sources"]), "passages": passages,
                         "explanation": generator.explanation(result, trace, c["relevance_threshold"]),
                         "latency_ms": round(ms)})
            print(f"{q['id']} {q['topic']:<18} found={result['found']!s:<5} {ms:6.0f} ms  {result['answer'][:70]}", flush=True)
        conn.close()
    ev.write(args.out, {"meta": info, "settings": {k: cfg[k] for k in ("chunk_size", "chunk_overlap", "top_k", "relevance_threshold",
                                                                      "model", "temperature", "seed")}, "rows": rows})


if __name__ == "__main__":
    main()
