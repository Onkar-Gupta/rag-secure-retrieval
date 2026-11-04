"""Demo sessions: a visitor gets a private group, uploads files into it and asks about them.

Only used when `demo_mode: true`. A session is a random group `demo-session-<hex>` and a random key,
held in memory. Its files live in a folder of that name under docs_dir, so the existing ingest()
indexes them into that group and nothing else is needed to keep them apart. Expired sessions have
their folder removed and are pruned from the index by the next ingest().
"""

import re
import secrets
import shutil
import time
from pathlib import Path

from rag_secure import security

PREFIX = "demo-session-"
SUFFIXES = {".pdf", ".md", ".txt"}
NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9 _().-]{0,99}")
RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


class DemoFull(Exception):
    pass


class Sessions:
    """In-memory sessions. `clock` is injectable so tests can expire sessions without waiting."""

    def __init__(self, ttl, max_sessions, clock=time.monotonic):
        self.ttl, self.max, self.clock = ttl, max_sessions, clock
        self.by_hash = {}  # key hash -> {"group", "born", "files"}

    def create(self):
        if len(self.by_hash) >= self.max:
            raise DemoFull
        key = secrets.token_urlsafe(32)
        group = PREFIX + secrets.token_hex(8)
        self.by_hash[security.hash_key(key)] = {"group": group, "born": self.clock(), "files": []}
        return key, group

    def lookup(self, key):
        """(group, session) for a live key, else None."""
        s = self.by_hash.get(security.hash_key(key)) if isinstance(key, str) else None
        return None if s is None or self.clock() - s["born"] >= self.ttl else (s["group"], s)

    def pop_expired(self):
        """Remove expired sessions and return their groups."""
        gone = [h for h, s in self.by_hash.items() if self.clock() - s["born"] >= self.ttl]
        return [self.by_hash.pop(h)["group"] for h in gone]

    def pop_all(self):
        groups = [s["group"] for s in self.by_hash.values()]
        self.by_hash.clear()
        return groups

    def is_session_group(self, group):
        return any(s["group"] == group for s in self.by_hash.values())


def clean_name(raw):
    """The file name if it is safe, else a (status, message) tuple. No path parts, no odd characters,
    no Windows device names, and only .pdf, .md or .txt."""
    if not isinstance(raw, str) or not NAME.fullmatch(raw) or Path(raw).stem.split(".")[0].upper() in RESERVED:
        return 400, "bad file name (letters, digits, spaces and _ ( ) . - only, up to 100 characters)"
    if Path(raw).suffix.lower() not in SUFFIXES:
        return 415, "only .pdf, .md and .txt files are accepted"
    return raw


def remove_folders(docs_dir, groups):
    for g in groups:
        if g.startswith(PREFIX):  # never delete anything that is not a demo session folder
            shutil.rmtree(Path(docs_dir) / g, ignore_errors=True)


def leftover_groups(docs_dir):
    """Session folders left behind by a crash."""
    root = Path(docs_dir)
    return [p.name for p in root.glob(PREFIX + "*") if p.is_dir()] if root.is_dir() else []
