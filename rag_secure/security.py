import hashlib
import hmac
import re
import secrets
import unicodedata

import yaml


def hash_key(api_key):
    """SHA-256 of an API key, as 64 hex characters. Keys are long random strings, so a plain fast hash
    is enough here (this is not for passwords). The users file stores only this hash."""
    return hashlib.sha256(api_key.encode()).hexdigest()


def new_key():
    """A fresh random API key and its hash: (key, hash). Show the key once; store only the hash."""
    key = secrets.token_urlsafe(32)
    return key, hash_key(key)


def load_users(path):
    """{name: {"groups": [...], "api_key_hash": "<64 hex>"}} from a YAML file with a top-level
    `users:` map. Fails loudly on a missing or malformed entry, or on two users sharing one key."""
    with open(path, encoding="utf-8") as f:
        users = yaml.safe_load(f)["users"]
    seen = {}
    for name, user in users.items():
        if not user.get("groups"):
            raise ValueError(f"user '{name}' has no groups")
        digest = str(user.get("api_key_hash", ""))
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError(f"user '{name}' needs an api_key_hash of 64 hex characters (see: rag new-key)")
        if digest in seen:
            raise ValueError(f"users '{seen[digest]}' and '{name}' share one API key")
        seen[digest] = name
    return users


def user_for_key(users, api_key):
    """(name, groups) for a valid API key, else None. The key is hashed and every stored hash is
    compared, in constant time. This is a lookup, not real sign-in: whoever holds a key is that user."""
    if not api_key or not isinstance(api_key, str):
        return None
    digest = hash_key(api_key)
    found = None
    for name, user in users.items():
        if hmac.compare_digest(user["api_key_hash"].encode(), digest.encode()):
            found = (name, list(user["groups"]))
    return found


def check_question(text, max_chars):
    """Return the question with whitespace tidied. Raises TypeError for non-text and ValueError for
    anything else wrong.

    Rejects non-text, empty input, input over `max_chars`, and invisible control or format
    characters (null bytes, zero-width spaces, right-to-left overrides), which are used to hide
    text from a human reader. This is hygiene, not a defence against prompt injection: keyword
    blocklists are easy to bypass, so the real defences are the group filter and the delimiters.
    """
    if not isinstance(text, str):
        raise TypeError("question must be text")
    for ch in text:
        if ch not in "\n\r\t" and unicodedata.category(ch) in ("Cc", "Cf"):
            raise ValueError(f"question contains a control or invisible character (U+{ord(ch):04X})")
    cleaned = " ".join(text.split())
    if not cleaned:
        raise ValueError("question is empty")
    if len(cleaned) > max_chars:
        raise ValueError(f"question is longer than {max_chars} characters")
    return cleaned
