import hmac
import unicodedata

import yaml


def load_users(path):
    """{name: {"groups": [...], "api_key": "..."}} from a YAML file with a top-level `users:` map."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)["users"]


def user_for_key(users, api_key):
    """(name, groups) for a valid API key, else None. Every key is compared, in constant time.
    This is a lookup, not real authentication: keys sit in a file in plain text."""
    if not api_key or not isinstance(api_key, str):
        return None
    found = None
    for name, user in users.items():
        if hmac.compare_digest(str(user["api_key"]).encode(), api_key.encode()):
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
