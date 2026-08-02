"""Preflight: friendly environment check before the model drives bazos.

Gives an actionable hint (install into the venv) instead of a stack trace when
a dependency, chromium, or the cached session is missing.

    "$HOME/.bazos-inzerce/venv/bin/python3" scripts/preflight.py
"""

import importlib.util
import os
import sys

import auth  # local; on sys.path via the script dir / pytest pythonpath

REQUIRED_MODULES = ["playwright", "browser_cookie3", "requests", "PIL"]
VENV_HINT = ('install into the venv: '
             '"$HOME/.bazos-inzerce/venv/bin/python3" -m pip install -r '
             'requirements.txt && "$HOME/.bazos-inzerce/venv/bin/python3" -m '
             'playwright install chromium')


def missing_imports():
    return [m for m in REQUIRED_MODULES if importlib.util.find_spec(m) is None]


def chromium_ok():
    """True iff Playwright's chromium build is present on disk."""
    if importlib.util.find_spec("playwright") is None:
        return False
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            return bool(p.chromium.executable_path) and \
                os.path.exists(p.chromium.executable_path)
    except Exception:
        return False


def has_cached_state():
    return os.path.exists(auth.STATE_FILE)


def check():
    """Return a list of human-readable problems; empty == ready."""
    problems = []
    miss = missing_imports()
    if miss:
        problems.append(f"missing Python modules {miss} — {VENV_HINT}")
    elif not chromium_ok():
        problems.append("chromium not installed — "
                        '"$HOME/.bazos-inzerce/venv/bin/python3" -m playwright '
                        "install chromium")
    if not has_cached_state():
        problems.append(
            "no cached bazos session (~/.bazos-inzerce/state.json) — the first "
            "run extracts it from Chrome (Keychain: click Allow) or opens a "
            "one-time headed login.")
    return problems


def main(argv=None):  # pragma: no cover - thin CLI
    problems = check()
    if not problems:
        print("preflight OK — deps + chromium present, cached session found.")
        return 0
    print("preflight found issues:")
    for p in problems:
        print(f"  - {p}")
    # A missing session is a warning (first run resolves it), missing deps fatal.
    fatal = any("modules" in p or "chromium" in p for p in problems)
    return 1 if fatal else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
