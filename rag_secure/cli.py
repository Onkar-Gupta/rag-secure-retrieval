import argparse

import yaml

from rag_secure import __version__, ingest


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rag")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--config", default="config.yaml")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("ingest", help="chunk and index the documents in docs_dir")
    args = parser.parse_args(argv)
    if args.command == "ingest":
        with open(args.config, encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        counts = ingest.ingest(
            cfg["docs_dir"], cfg["chroma_dir"], cfg["db_path"], cfg["chunk_size"], cfg["chunk_overlap"]
        )
        print(f"documents added {counts['added']}, skipped {counts['skipped']}, chunks written {counts['chunks']}")
