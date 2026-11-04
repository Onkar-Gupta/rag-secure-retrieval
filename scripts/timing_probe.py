"""Search-time probe. Follows the 4 Nov 2026 Amendment in eval/protocol.md (section 11).

Does the search take a different time for the same user and question when other groups' documents
are in the index?  FULL index vs PUBLIC-ONLY index, user `guest`, 120 questions, 200 timed repeats each.

    python scripts/timing_probe.py        # writes reports/timing_probe.json
"""

import json
import random
import shutil
import statistics
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "eval"))

import run_eval as ev
import yaml

from rag_secure import db
from rag_secure.ingest import ingest, open_collection
from rag_secure.retriever import retrieve

WARMUP, REPEATS, RESAMPLES, SEED = 20, 200, 10000, 0


def build(docs, tmp, name, cfg):
    ingest(docs, Path(tmp) / name, Path(tmp) / f"{name}.sqlite", cfg["chunk_size"], cfg["chunk_overlap"])
    return open_collection(Path(tmp) / name), db.connect(Path(tmp) / f"{name}.sqlite")


def timed(col, conn, text, vec, groups, k):
    t = time.perf_counter_ns()
    hits = retrieve(col, conn, text, groups, k=k, embedding=vec)
    return time.perf_counter_ns() - t, [h["chunk_id"] for h in hits]


def main():
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    questions = ev.load_questions()
    vecs = ev.embed_questions(questions)
    groups = ev.load_users()["guest"]["groups"]
    with tempfile.TemporaryDirectory() as tmp:
        public_only = Path(tmp) / "public_docs"
        shutil.copytree(ROOT / "data" / "docs" / "public", public_only / "public")
        full = build(ROOT / "data" / "docs", tmp, "full", cfg)
        pub = build(public_only, tmp, "pub", cfg)
        diffs, med_full, med_pub, same_ids = [], [], [], 0
        started = time.time()
        for n, q in enumerate(questions, 1):
            args = (q["question"], vecs[q["id"]], groups, cfg["top_k"])
            for _ in range(WARMUP):
                timed(*full, *args)
                timed(*pub, *args)
            tf, tp, ids_f, ids_p = [], [], None, None
            for _ in range(REPEATS):
                a, ids_f = timed(*full, *args)
                b, ids_p = timed(*pub, *args)
                tf.append(a)
                tp.append(b)
            mf, mp = statistics.median(tf), statistics.median(tp)
            med_full.append(mf)
            med_pub.append(mp)
            diffs.append(mf - mp)
            same_ids += ids_f == ids_p
            print(f"\r[{n}/{len(questions)}] {time.time() - started:.0f}s", end="", flush=True)
        print()
    rng = random.Random(SEED)
    m = len(diffs)
    meds = sorted(statistics.median(diffs[rng.randrange(m)] for _ in range(m)) for _ in range(RESAMPLES))
    ci = [meds[int(0.025 * RESAMPLES)] / 1e6, meds[int(0.975 * RESAMPLES) - 1] / 1e6]
    result = {
        "question": "does search time differ for guest with and without other groups' documents",
        "n_questions": m, "warmup": WARMUP, "repeats": REPEATS, "resamples": RESAMPLES, "seed": SEED,
        "median_ms_full": statistics.median(med_full) / 1e6,
        "median_ms_public_only": statistics.median(med_pub) / 1e6,
        "median_difference_ms": statistics.median(diffs) / 1e6,
        "ci95_ms": ci,
        "rule_interval_includes_zero": ci[0] <= 0 <= ci[1],
        "same_top5_ids_in_both_indexes": f"{same_ids} of {m}",
        "meta": ev.meta(),
    }
    ev.write(ROOT / "reports" / "timing_probe.json", result)
    print(json.dumps({k: v for k, v in result.items() if k != "meta"}, indent=1))


if __name__ == "__main__":
    main()
