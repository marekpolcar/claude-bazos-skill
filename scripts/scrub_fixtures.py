"""Deterministic PII scrub: raw authed captures -> repo fixtures.

Reads a real->fake identity map from ``~/.bazos-inzerce/scrub-identity.json``
(NEVER in the repo), substitutes each real identity string with its fake
counterpart, and writes the result into ``tests/fixtures/``. Only the specific
identity *values* are replaced — tags, attribute names, field names and the
honeypot are never touched, because we only ever ``str.replace`` the exact PII
strings, not markup tokens.

``scrub_text`` is pure and unit-tested. The CLI is a maintainer tool run after
``capture_fixtures.py`` produces raw authed HTML.

Usage:
    "$HOME/.bazos-inzerce/venv/bin/python3" scripts/scrub_fixtures.py
"""

import json
import os
import sys

HOME_DIR = os.path.expanduser("~/.bazos-inzerce")
IDENTITY_FILE = os.path.join(HOME_DIR, "scrub-identity.json")
CAPTURES_DIR = os.path.join(HOME_DIR, "captures")


def load_identity(path=IDENTITY_FILE):
    """Load the real->fake map. Accepts a flat ``{real: fake}`` dict, or a
    ``{"replacements": {real: fake}}`` wrapper."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict) and "replacements" in data:
        data = data["replacements"]
    if not isinstance(data, dict):
        raise ValueError("scrub-identity.json must be a {real: fake} object")
    return {str(k): str(v) for k, v in data.items()}


def scrub_text(text, replacements):
    """Replace every real identity string with its fake counterpart.

    Longest keys first so a real value that is a substring of another
    (e.g. a phone inside a longer id) does not get partially rewritten.
    """
    for real in sorted(replacements, key=len, reverse=True):
        if real:
            text = text.replace(real, replacements[real])
    return text


def scrub_file(src, dst, replacements):
    with open(src, encoding="utf-8") as f:
        raw = f.read()
    scrubbed = scrub_text(raw, replacements)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(scrubbed)
    return scrubbed


def main(argv=None):
    argv = argv if argv is not None else sys.argv[1:]
    out_dir = argv[0] if argv else os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "tests", "fixtures"
    )
    if not os.path.exists(IDENTITY_FILE):
        print(f"error: {IDENTITY_FILE} not found — create a real->fake map first "
              f"(never commit it).", file=sys.stderr)
        return 2
    if not os.path.isdir(CAPTURES_DIR):
        print(f"error: {CAPTURES_DIR} not found — run capture_fixtures.py first.",
              file=sys.stderr)
        return 2
    repl = load_identity()
    os.makedirs(out_dir, exist_ok=True)
    n = 0
    for name in sorted(os.listdir(CAPTURES_DIR)):
        if not name.endswith(".html"):
            continue
        src = os.path.join(CAPTURES_DIR, name)
        dst = os.path.join(out_dir, name)
        scrub_file(src, dst, repl)
        print(f"scrubbed {name} -> {dst}")
        n += 1
    print(f"done: {n} file(s). Run the hygiene test before committing.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
