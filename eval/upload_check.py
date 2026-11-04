"""Upload check for demo sessions. Follows the 5 Nov 2026 Amendment "demo sessions and uploads"
in eval/protocol.md. Run once:

    python eval/upload_check.py

Needs Ollama running. Refuses a dirty working tree and a second run (pass --rerun-reason to override).
Writes reports/upload_check.json.
"""

import argparse
import json
import re
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

import yaml
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import run_eval as ev

from rag_secure import db, demo, generator, ingest, serve
from rag_secure.ingest import open_collection
from rag_secure.retriever import retrieve

SES_CANARY = re.compile(r"CANARY-SES-[0-9a-f]{8}")
MB = 1024 * 1024


def clock_with_offset():
    offset = [0.0]
    return (lambda: time.monotonic() + offset[0]), offset


def make_app(tmp, cfg, users, llm):
    """A fresh service in `tmp` with the 30 main documents indexed and demo mode on."""
    docs = tmp / "docs"
    shutil.copytree(ROOT / "data" / "docs", docs)
    c = dict(cfg, docs_dir=str(docs), chroma_dir=str(tmp / "chroma"), db_path=str(tmp / "t.sqlite"), demo_mode=True)
    ingest.ingest(docs, c["chroma_dir"], c["db_path"], c["chunk_size"], c["chunk_overlap"])
    app = serve.create_app(c, users, open_collection(c["chroma_dir"]), llm)
    clock, offset = clock_with_offset()
    app.state.sessions.clock = clock
    return app, c, offset


def new_session(client):
    r = client.post("/session")
    assert r.status_code == 200, r.text
    return r.json()


def upload(client, key, name, body, **kw):
    return client.post("/upload", content=body, headers={"X-API-Key": key, "X-Filename": name, **kw.pop("headers", {})}, **kw)


def snapshot(tmp):
    """Every file under tmp except the index files, which change on every ingest."""
    skip = (tmp / "chroma",)
    return {p.relative_to(tmp).as_posix() for p in tmp.rglob("*")
            if p.is_file() and not any(s in p.parents for s in skip) and not p.name.startswith("t.sqlite")}


def refusal_cases(cfg, users):
    """Part 2: every refusal in the pre-registered list, plus the extra cases named in the report."""
    results = []
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        tmp = Path(t)
        app, c, offset = make_app(tmp, cfg, users, lambda s, u: "")
        with TestClient(app) as client:
            a = new_session(client)
            own = Path(c["docs_dir"]) / a["group"]

            def case(label, expected, send, may_write=False):
                before = snapshot(tmp)
                got = send()
                after = snapshot(tmp)
                new = after - before
                outside = [f for f in new if not f.startswith(f"docs/{a['group']}/")]
                ok = (got == expected) and not outside and (may_write or not new)
                results.append({"case": label, "expected": expected, "got": got, "ok": ok, "written_outside_session": outside})

            for name, status in [("../x.pdf", 400), ("a/b.pdf", 400), ("/abs.pdf", 400), ("C:x.pdf", 400),
                                 ("a\\b.pdf", 400), ("a" * 101 + ".pdf", 400), ("CON.pdf", 400), ("nul.txt", 400),
                                 ("run.exe", 415), ("page.html", 415), ("noextension", 415)]:
                case(f"file name {name[:30]!r}", status, lambda n=name: upload(client, a["key"], n, b"budget").status_code)
            # HTTP cannot carry a null byte in a header, so this one case calls the name check directly
            results.append({"case": "file name with a null byte (name check called directly)", "expected": 400,
                            "got": demo.clean_name("a\x00b.pdf")[0], "ok": demo.clean_name("a\x00b.pdf")[0] == 400,
                            "written_outside_session": []})
            case("file over the size limit", 413, lambda: upload(client, a["key"], "big.md", b"x" * (5 * MB + 1)).status_code)
            case("request that names a group lands in the session's own group", 200,
                 lambda: upload(client, a["key"], "one.md", b"hello", headers={"X-Group": "finance"},
                                params={"group": "finance"}).status_code, may_write=True)
            results[-1]["ok"] = results[-1]["ok"] and (own / "one.md").exists() and not (Path(c["docs_dir"]) / "finance" / "one.md").exists()
            for n in ("two", "three"):
                case(f"file {n} accepted", 200, lambda n=n: upload(client, a["key"], f"{n}.md", b"hello").status_code, may_write=True)
            case("fourth file", 409, lambda: upload(client, a["key"], "four.md", b"hello").status_code)
            case("missing key", 401, lambda: client.post("/upload", content=b"x", headers={"X-Filename": "x.md"}).status_code)
            case("wrong key", 401, lambda: upload(client, "wrong-key", "x.md", b"x").status_code)
            case("a real user's key (not a session)", 403, lambda: upload(client, "demo-key-admin", "x.md", b"x").status_code)
            case("unreadable PDF", 422, lambda: upload(client, new_session(client)["key"], "bad.pdf", b"not a pdf").status_code)
            while len(app.state.sessions.by_hash) < 20:
                new_session(client)
            case("21st session", 503, lambda: client.post("/session").status_code)
            offset[0] += c["demo_ttl_seconds"] + 1
            case("expired session", 401, lambda: upload(client, a["key"], "late.md", b"x").status_code)
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reports", type=Path, default=ROOT / "reports")
    ap.add_argument("--rerun-reason", default=None)
    ap.add_argument("--allow-dirty", action="store_true")
    args = ap.parse_args()
    s = ev.frozen_settings()
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    ev.check_ollama(cfg["ollama_url"])
    info = ev.meta()
    if info["working_tree_dirty"] and not args.allow_dirty:
        raise SystemExit("The working tree has uncommitted changes. Commit them first (or use --allow-dirty for practice).")
    target = args.reports / "upload_check.json"
    if target.exists():
        if not args.rerun_reason:
            raise SystemExit(f"{target} already exists. The Amendment allows ONE run; pass --rerun-reason to override.")
        target = args.reports / f"upload_check_run{len(list(args.reports.glob('upload_check_run*.json'))) + 2}.json"

    users = ev.load_users()
    qs = [json.loads(line) for line in (ROOT / "eval" / "session_questions.jsonl").read_text(encoding="utf-8").splitlines()]
    byid = {q["id"]: q for q in qs}
    cross = [q for q in ev.load_questions() if q["type"] == "cross_group"]
    llm = generator.ollama_llm(cfg["model"], cfg["ollama_url"], cfg["temperature"], cfg["seed"], cfg["max_tokens"])
    vecs = ev.embed_questions(qs + cross)
    main_canaries = ev.canary_folders()
    print("[upload-check] part 2 first: refusals", flush=True)
    refusals = refusal_cases(cfg, users)

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as t:
        tmp = Path(t)
        app, c, offset = make_app(tmp, cfg, users, llm)
        with TestClient(app) as client:
            sess = []
            for n in range(1, 6):
                a = new_session(client)
                r = upload(client, a["key"], f"notes_{n}.md", (ROOT / "data" / "session_docs" / f"session_{n}.md").read_bytes())
                assert r.status_code == 200, r.text
                sess.append(a)
            own_canary = {n: SES_CANARY.findall((ROOT / "data" / "session_docs" / f"session_{n}.md").read_text(encoding="utf-8"))[0]
                          for n in range(1, 6)}
            col, conn = open_collection(c["chroma_dir"]), db.connect(c["db_path"])

            # Part 1: isolation, retrieval only, with a no-filter control
            runs = {"D": 0, "A": 0}
            leaks = {"D": [], "A": []}
            own_in_top5 = [0, 0]
            jobs = [(a, q) for a in range(5) for q in qs] + [(0, q) for q in cross]
            for ai, q in jobs:
                groups = ["public", sess[ai]["group"]]
                vec = vecs[q["id"]]
                ctx = {"D": retrieve(col, conn, q["question"], groups, k=c["top_k"], embedding=vec, threshold=c["relevance_threshold"])}
                res = col.query(query_embeddings=[vec], n_results=c["top_k"])
                ctx["A"] = [{"doc_id": m["doc_id"]} for m, d in zip(res["metadatas"][0], res["distances"][0])
                            if d <= c["relevance_threshold"]]
                for cond in "DA":
                    runs[cond] += 1
                    if any(ev.folder(h["doc_id"]) not in groups for h in ctx[cond]):
                        leaks[cond].append(f"{q['id']} as session {ai + 1}")
                if q.get("kind") == "topic" and q["session"] == ai + 1:
                    top = retrieve(col, conn, q["question"], groups, k=c["top_k"], embedding=vec)
                    own_in_top5[1] += 1
                    own_in_top5[0] += any(h["doc_id"].startswith(sess[ai]["group"] + "/") for h in top)

            # Part 1b: 50 attacker answers through the real model, 25 own-document answers
            print("[upload-check] model answers", flush=True)
            llm("Reply with the single word OK.", "Say OK.")
            ask_jobs = []
            for i in range(1, 6):
                for j in range(1, 6):
                    if j != i:
                        ask_jobs += [(i, f"s{j}_canary0"), (i, f"s{j}_topic0a")]
                ask_jobs += [(i, f"s{i}_pull0"), (i, f"s{i}_pull1")]
            own_jobs = [(i, f"s{i}_topic{k}a") for i in range(1, 6) for k in range(5)]
            attack, own, secs = [], [], []
            started = time.perf_counter()
            for n, (i, qid) in enumerate(ask_jobs + own_jobs, 1):
                t0 = time.perf_counter()
                body = client.post("/ask", json={"question": byid[qid]["question"]},
                                   headers={"X-API-Key": sess[i - 1]["key"]}).json()
                secs.append(time.perf_counter() - t0)
                groups = ["public", sess[i - 1]["group"]]
                if n <= len(ask_jobs):
                    bad = [x for x in SES_CANARY.findall(body["answer"]) if x != own_canary[i]]
                    bad += [x for x in ev.CANARY.findall(body["answer"]) if main_canaries.get(x) not in groups]
                    bad_src = [x for x in body["sources"] if ev.folder(x) not in groups]
                    attack.append({"asker": i, "id": qid, "canary_strings_from_elsewhere": bad, "forbidden_sources": bad_src,
                                   "answer": body["answer"]})
                else:
                    own.append({"asker": i, "id": qid, "cited_own_document": any(x.startswith(sess[i - 1]["group"] + "/") for x in body["sources"]),
                                "answer": body["answer"]})
                ev.progress(n, len(ask_jobs) + len(own_jobs), started, qid)
            print(flush=True)

            # Part 3: cleanup after expiry
            offset[0] += c["demo_ttl_seconds"] + 1
            client.post("/session")  # any session call sweeps expired sessions
            conn2 = db.connect(c["db_path"])
            cleanup = []
            for a in sess:
                cleanup.append({"group": a["group"], "folder_gone": not (Path(c["docs_dir"]) / a["group"]).exists(),
                                "chunks_in_chroma": len(open_collection(c["chroma_dir"]).get(where={"group": a["group"]})["ids"]),
                                "rows_in_sqlite": conn2.execute("SELECT COUNT(*) FROM documents WHERE grp=?", (a["group"],)).fetchone()[0]})

    canary_bad = sum(len(x["canary_strings_from_elsewhere"]) for x in attack)
    src_bad = sum(len(x["forbidden_sources"]) for x in attack)
    summary = {
        "retrieval_runs_per_condition": runs["D"],
        "forbidden_chunks_in_context_D": ev.rate(len(leaks["D"]), runs["D"]),
        "forbidden_chunks_in_context_A_control": ev.rate(len(leaks["A"]), runs["A"]),
        "attacker_answers": len(attack), "canary_strings_from_elsewhere_in_answers": canary_bad,
        "forbidden_sources_in_answers": src_bad,
        "refusal_cases": refusals, "cleanup": cleanup,
        "own_document_in_top5_for_own_topic_questions": ev.rate(own_in_top5[0], own_in_top5[1]),
        "own_answers_citing_own_document": ev.rate(sum(x["cited_own_document"] for x in own), len(own)),
        "median_seconds_per_answer": statistics.median(secs), "p90_seconds_per_answer": sorted(secs)[int(0.9 * len(secs)) - 1],
        "leak_examples_D": leaks["D"],
    }
    summary["verdict"] = {
        "pass_mark_1_isolation": not leaks["D"] and canary_bad == 0 and src_bad == 0,
        "pass_mark_2_every_refusal_correct_and_nothing_written_outside": all(r["ok"] for r in refusals),
        "pass_mark_3_cleanup_5_of_5": all(x["folder_gone"] and x["chunks_in_chroma"] == 0 and x["rows_in_sqlite"] == 0 for x in cleanup)
        and len(cleanup) == 5,
        "control_A_leaks_so_the_test_can_see_leaks": bool(leaks["A"]),
    }
    result = {"stage": "upload-check", "rerun_reason": args.rerun_reason, "model": cfg["model"], "settings": s,
              "summary": summary, "attacker_answers_detail": attack, "own_answers_detail": own, "meta": info}
    ev.write(target, result)
    print(json.dumps(summary["verdict"], indent=1))


if __name__ == "__main__":
    main()
