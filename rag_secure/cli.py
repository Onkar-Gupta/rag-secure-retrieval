import argparse

import yaml

from rag_secure import __version__, db, ingest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rag")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("ingest", help="chunk and index the documents in docs_dir")
    q = sub.add_parser("quarantine", help="hide a document from every search")
    q.add_argument("doc_id", help="for example finance/budget_2026.md")
    q.add_argument("--release", action="store_true", help="show the document again")
    args = parser.parse_args(argv)
    if args.command is None:
        return
    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if args.command == "ingest":
        counts = ingest.ingest(
            cfg["docs_dir"], cfg["chroma_dir"], cfg["db_path"], cfg["chunk_size"], cfg["chunk_overlap"]
        )
        print(
            f"documents added {counts['added']}, skipped {counts['skipped']}, "
            f"removed {counts['removed']}, chunks written {counts['chunks']}"
        )
    elif args.command == "quarantine":
        try:
            db.set_quarantine(db.connect(cfg["db_path"]), args.doc_id, on=not args.release)
        except KeyError as e:
            raise SystemExit(f"error: {e.args[0]}") from None
        print(f"{args.doc_id}: {'released' if args.release else 'quarantined'}")
