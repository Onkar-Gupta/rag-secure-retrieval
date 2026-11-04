"""Search-time probe. Follows the 4 Nov 2026 Amendment in eval/protocol.md (section 11).

Does the search take a different time for the same user and question when other groups' documents
are in the index?  FULL index vs PUBLIC-ONLY index, user `guest`, 120 questions, 200 timed repeats each.

    python scripts/timing_probe.py        # writes reports/timing_probe.json
"""

import argparse
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
LATE_MARGIN_MS = 0.1  # a padded search measures the floor plus a few microseconds of timer overhead


def build(docs, tmp, name, cfg):
    ingest(docs, Path(tmp) / name, Path(tmp) / f"{name}.sqlite", cfg["chunk_size"], cfg["chunk_overlap"])
    return open_collection(Path(tmp) / name), db.connect(Path(tmp) / f"{name}.sqlite")


def timed(col, conn, text, vec, groups, k, floor_ms=0):
    t = time.perf_counter_ns()
    hits = retrieve(col, conn, text, groups, k=k, embedding=vec, floor_ms=floor_ms)
    return time.perf_counter_ns() - t, [h["chunk_id"] for h in hits]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--floor-ms", type=float, default=0, help="pad every search to this many ms")
    ap.add_argument("--margin-ms", type=float, default=None, help="equivalence margin for the interval")
    args_cli = ap.parse_args()
    floor, margin = args_cli.floor_ms, args_cli.margin_ms
    cfg = yaml.safe_load((ROOT / "config.yaml").read_text(encoding="utf-8"))
    questions = ev.load_questions()
    vecs = ev.embed_questions(questions)
    groups = ev.load_users()["guest"]["groups"]
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        public_only = Path(tmp) / "public_docs"
        shutil.copytree(ROOT / "data" / "docs" / "public", public_only / "public")
        full = build(ROOT / "data" / "docs", tmp, "full", cfg)
        pub = build(public_only, tmp, "pub", cfg)
        diffs, med_full, med_pub, same_ids, late = [], [], [], 0, 0
        started = time.time()
        for n, q in enumerate(questions, 1):
            args = (q["question"], vecs[q["id"]], groups, cfg["top_k"], floor)
            for _ in range(WARMUP):
                timed(*full, *args)
                timed(*pub, *args)
            tf, tp, ids_f, ids_p = [], [], None, None
            for _ in range(REPEATS):
                a, ids_f = timed(*full, *args)
                b, ids_p = timed(*pub, *args)
                tf.append(a)
                tp.append(b)
            late += sum(t > (floor + LATE_MARGIN_MS) * 1e6 for t in tf + tp) if floor else 0
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
        "floor_ms": floor,
        "margin_ms": margin,
        "rule_interval_within_margin": None if margin is None else (-margin <= ci[0] and ci[1] <= margin),
        "searches_later_than_floor": f"{late} of {m * REPEATS * 2}" if floor else "not applicable",
        "meta": ev.meta(),
    }
    ev.write(ROOT / "reports" / (f"timing_probe_padded_{floor:g}ms.json" if floor else "timing_probe.json"), result)
    print(json.dumps({k: v for k, v in result.items() if k != "meta"}, indent=1))


if __name__ == "__main__":
    main()
