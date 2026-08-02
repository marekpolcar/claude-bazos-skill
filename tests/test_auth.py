"""Unit tests for auth — pure helpers + the cache-only guard. No network,
no Keychain."""

import json
import os
import stat

import pytest

import auth


class FakeCookie:
    def __init__(self, name, value, domain, path="/", secure=False,
                 expires=None, http_only=False):
        self.name = name
        self.value = value
        self.domain = domain
        self.path = path
        self.secure = secure
        self.expires = expires
        self._http_only = http_only

    def has_nonstandard_attr(self, attr):
        return attr == "HttpOnly" and self._http_only


FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


# --- is_verified ---

def test_is_verified_true_on_authed_fixture():
    assert auth.is_verified(_read("moje_inzeraty_authed.html"), "777123456") is True


def test_is_verified_false_on_anon_fixture():
    assert auth.is_verified(_read("moje_inzeraty_anon.html"), "777123456") is False


def test_is_verified_false_without_phone():
    assert auth.is_verified(_read("moje_inzeraty_authed.html"), "") is False


# --- cookies_to_storage_state ---

def test_storage_state_preserves_domain_and_samesite():
    cookies = [
        FakeCookie("bid", "abc", ".bazos.cz", secure=True, expires=1893456000),
        FakeCookie("bkod", "xyz", ".bazos.cz", http_only=True),
    ]
    state = auth.cookies_to_storage_state(cookies)
    assert state["origins"] == []
    by_name = {c["name"]: c for c in state["cookies"]}
    assert by_name["bid"]["domain"] == ".bazos.cz"        # leading dot preserved
    assert by_name["bid"]["secure"] is True
    assert by_name["bid"]["expires"] == 1893456000.0
    assert by_name["bkod"]["httpOnly"] is True
    assert by_name["bkod"]["expires"] == -1               # session cookie
    assert all(c["sameSite"] in ("Strict", "Lax", "None") for c in state["cookies"])
    assert all(c["sameSite"] == "Lax" for c in state["cookies"])


# --- get_identity ---

def test_get_identity_url_decodes():
    cookies = [
        FakeCookie("bjmeno", "Jan%20Nov%C3%A1k", ".bazos.cz"),
        FakeCookie("btelefon", "777123456", ".bazos.cz"),
        FakeCookie("bmail", "jan.novak@example.com", ".bazos.cz"),
        FakeCookie("irrelevant", "x", ".google.com"),
    ]
    ident = auth.get_identity(cookies)
    assert ident == {
        "jmeno": "Jan Novák",
        "telefon": "777123456",
        "email": "jan.novak@example.com",
    }


# --- state hygiene ---

def test_write_state_atomic_is_0600(tmp_path):
    path = str(tmp_path / "state.json")
    auth._write_state_atomic(path, {"cookies": [], "origins": []})
    mode = stat.S_IMODE(os.stat(path).st_mode)
    assert mode == 0o600
    assert json.load(open(path)) == {"cookies": [], "origins": []}


# --- get_storage_state guard ---

def test_interactive_false_empty_cache_raises_without_keychain(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_ensure_dir", lambda: None)
    boom = lambda *a, **k: (_ for _ in ()).throw(AssertionError("must not extract"))
    monkeypatch.setattr(auth, "_extract_and_validate", boom)
    monkeypatch.setattr(auth, "_chrome_cookies", boom)
    with pytest.raises(auth.AuthError):
        auth.get_storage_state(interactive=False, state_path=str(tmp_path / "nope.json"))


def test_cache_hit_returns_cached(tmp_path, monkeypatch):
    monkeypatch.setattr(auth, "_ensure_dir", lambda: None)
    path = tmp_path / "state.json"
    payload = {"cookies": [{"name": "bid", "value": "x"}], "origins": []}
    path.write_text(json.dumps(payload), encoding="utf-8")
    assert auth.get_storage_state(interactive=False, state_path=str(path)) == payload
