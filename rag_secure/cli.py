import argparse

from rag_secure import __version__


def main(argv=None):
    parser = argparse.ArgumentParser(prog="rag")
    parser.add_argument("--version", action="version", version=__version__)
    parser.parse_args(argv)
