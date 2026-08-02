"""Hybrid auth + identity (DESIGN §4).

"Login" on bazos is a verified-device cookie (`bid`+`bkod`), not an account.
This module turns the user's own Chrome session into a Playwright
``storage_state`` and extracts the verified identity from cookies — so the model
never interrogates the user for data the session already has.

Pure/offline: ``cookies_to_storage_state``, ``is_verified``, ``get_identity``
(with injected cookies), atomic state write. Live/user-gated:
``get_storage_state`` extraction (browser_cookie3 → live validate → headed
fallback). ``interactive=False`` is strictly cache-only — it never pops the
Keychain (browser_cookie3) and never launches a browser.
"""

import json
import os
import stat
import tempfile
from urllib.parse import unquote

import category

BASE_DIR = os.path.expanduser("~/.bazos-inzerce")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
PROFILE_DIR = os.path.join(BASE_DIR, "profile")

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")


class AuthError(RuntimeError):
    """No usable verified bazos session."""


# --- pure helpers -----------------------------------------------------------

def _http_only(c):
    fn = getattr(c, "has_nonstandard_attr", None)
    try:
        return bool(fn("HttpOnly")) if fn else False
    except Exception:
        return False


def cookies_to_storage_state(cookies):
    """Cookiejar cookies → Playwright ``storage_state`` dict.

    Preserves ``domain`` exactly (a leading-dot ``.bazos.cz`` must apply on
    ``knihy.bazos.cz``) and defaults ``sameSite`` to ``Lax`` (cookiejar carries
    none; Playwright requires Strict/Lax/None).
    """
    out = []
    for c in cookies:
        out.append({
            "name": c.name,
            "value": c.value,
            "domain": c.domain,                 # exact, incl. leading dot
            "path": getattr(c, "path", "/") or "/",
            "expires": float(c.expires) if getattr(c, "expires", None) else -1,
            "httpOnly": _http_only(c),
            "secure": bool(getattr(c, "secure", False)),
            "sameSite": "Lax",
        })
    return {"cookies": out, "origins": []}


def is_verified(html, phone):
    """True iff the page renders the verified user (own phone shown, no SMS gate)."""
    if not phone:
        return False
    return phone in html and not category.is_gate(html)


def get_identity(cookies=None):
    """``{"jmeno","telefon","email"}`` from the URL-decoded bjmeno/btelefon/bmail
    cookies. This is the source for the schema's contact fields."""
    if cookies is None:
        cookies = _chrome_cookies()
    vals = {c.name: c.value for c in cookies if "bazos" in c.domain}
    return {
        "jmeno": unquote(vals.get("bjmeno", "")),
        "telefon": unquote(vals.get("btelefon", "")),
        "email": unquote(vals.get("bmail", "")),
    }


# --- state hygiene ----------------------------------------------------------

def _ensure_dir():
    os.makedirs(BASE_DIR, mode=0o700, exist_ok=True)
    os.chmod(BASE_DIR, 0o700)  # makedirs mode is umask-masked; enforce


def _write_state_atomic(path, state):
    _ensure_dir()
    d = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".state-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


def _load_cached_state(path):
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return None


# --- live extraction (user-gated) -------------------------------------------

def _chrome_cookies():
    import browser_cookie3 as bc3
    return bc3.chrome(domain_name="bazos")


def _validate_live(state, phone):
    """Load moje-inzeraty with the extracted cookies; True iff verified."""
    import requests
    s = requests.Session()
    s.headers["User-Agent"] = UA
    for c in state["cookies"]:
        s.cookies.set(c["name"], c["value"], domain=c["domain"], path=c["path"])
    r = s.get("https://www.bazos.cz/moje-inzeraty.php", timeout=25,
              allow_redirects=True)
    return is_verified(category._text(r), phone)


def _extract_and_validate():
    """browser_cookie3 → storage_state, validated against the live site."""
    cookies = list(_chrome_cookies())
    baz = [c for c in cookies if "bazos" in c.domain]
    if not any(c.name == "bkod" for c in baz):
        raise AuthError("no bkod cookie in Chrome — not a verified bazos device")
    state = cookies_to_storage_state(baz)
    identity = get_identity(cookies)
    if not _validate_live(state, identity["telefon"]):
        raise AuthError("Chrome bazos session did not validate (expired?)")
    return state


def _headed_login():
    """One-time headed login into the persistent profile; returns storage_state.

    LIVE / user-gated: opens a real browser, lets the user log in + SMS-verify,
    waits for the verified signal, then captures the session.
    """
    from playwright.sync_api import sync_playwright
    _ensure_dir()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            PROFILE_DIR, headless=False, user_agent=UA)
        page = ctx.new_page()
        page.goto("https://www.bazos.cz/moje-inzeraty.php", wait_until="load")
        # Wait (up to 5 min) for the user to finish login + SMS verification.
        page.wait_for_function(
            "() => !document.querySelector('form[name=formovereni]') "
            "&& /odhl\\u00e1sit/i.test(document.body.innerText)",
            timeout=300_000)
        state = ctx.storage_state()
        ctx.close()
    return state


class _CookieView:
    __slots__ = ("name", "value", "domain")

    def __init__(self, name, value, domain):
        self.name, self.value, self.domain = name, value, domain


def get_identity_from_state(state):
    """Identity from a storage_state's cookies (no Keychain prompt)."""
    return get_identity(_CookieView(c["name"], c["value"], c.get("domain", ""))
                        for c in state.get("cookies", []))


def requests_session(state=None):
    """A ``requests`` session carrying the cached bazos cookies (for the cheap
    GET-only paths: canary, sections, categories, moje-inzeraty)."""
    import requests
    if state is None:
        state = _load_cached_state(STATE_FILE)
        if state is None:
            raise AuthError("no cached session — run get_storage_state() first")
    s = requests.Session()
    s.headers["User-Agent"] = UA
    for c in state["cookies"]:
        s.cookies.set(c["name"], c["value"], domain=c["domain"],
                      path=c.get("path", "/"))
    return s


def get_storage_state(interactive=True, state_path=STATE_FILE):
    """Return a Playwright storage_state for a verified bazos session.

    Cache-first (``state.json``). On a miss: if ``interactive`` is False, raise
    (cache-only — never touches browser_cookie3 or launches a browser); if True,
    extract from Chrome (browser_cookie3, validated live), falling back to a
    one-time headed login. The working state is persisted (0600).
    """
    _ensure_dir()
    cached = _load_cached_state(state_path)
    if cached:
        return cached
    if not interactive:
        raise AuthError("no cached bazos session and interactive=False")
    try:
        state = _extract_and_validate()
    except AuthError:
        state = _headed_login()
    _write_state_atomic(state_path, state)
    return state
