"""Unit tests for the category resolver — parsers over fixtures + stub-session
fetchers. No network.
"""

import os

import pytest

import category

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


class StubResp:
    def __init__(self, text, encoding="utf-8"):
        self.text = text
        self.encoding = encoding
        self.apparent_encoding = "utf-8"


class StubSession:
    def __init__(self, mapping):
        self.mapping = mapping  # url-substring -> fixture text

    def get(self, url, **kw):
        for key, text in self.mapping.items():
            if key in url:
                return StubResp(text)
        raise AssertionError(f"unexpected url {url}")


# --- parse_sections ---

def test_parse_sections_includes_knihy():
    secs = category.parse_sections(_read("homepage.html"))
    subs = {s["subdomain"] for s in secs}
    assert "knihy" in subs
    assert "www" not in subs
    knihy = next(s for s in secs if s["subdomain"] == "knihy")
    assert knihy["name"] == "Knihy"
    assert knihy["url"] == "https://knihy.bazos.cz"


def test_parse_sections_all_labels_nonempty_and_deduped():
    secs = category.parse_sections(_read("homepage.html"))
    assert len(secs) >= 18
    assert all(s["name"] for s in secs)
    assert len(secs) == len({s["subdomain"] for s in secs})  # no dupes
    # inner-tag label survives (PC cell is "<a ...>PC<br></a>")
    assert any(s["subdomain"] == "pc" and s["name"] == "PC" for s in secs)


def test_parse_sections_tolerates_anchor_attributes():
    html = ('<a href="https://knihy.bazos.cz/" class="nav" data-x="1">Knihy</a>'
            '<a href="https://deti.bazos.cz/">Děti</a>')
    secs = category.parse_sections(html)
    subs = {s["subdomain"] for s in secs}
    assert {"knihy", "deti"} <= subs


# --- parse_category_options ---

def test_parse_category_options_nonempty_with_diacritics():
    opts = category.parse_category_options(_read("insert_form.html"))
    assert opts, "expected category options"
    assert all(o["value"] and o["label"] for o in opts)
    # placeholder (value="") skipped
    assert all(o["value"] != "" for o in opts)
    # at least one diacritic label round-trips without mojibake
    assert any("č" in o["label"].lower() or "ě" in o["label"].lower()
               or "í" in o["label"].lower() for o in opts)
    assert {"value": "34", "label": "Dětské knihy"} in opts


def test_parse_category_options_raises_on_gate():
    with pytest.raises(category.GateError):
        category.parse_category_options(_read("sms_gate.html"))


def test_parse_category_options_valueerror_when_no_select():
    with pytest.raises(ValueError):
        category.parse_category_options("<html><body>no select here</body></html>")


# --- fetchers (stub session) ---

def test_fetch_sections_via_stub():
    sess = StubSession({"www.bazos.cz": _read("homepage.html")})
    secs = category.fetch_sections(sess)
    assert any(s["subdomain"] == "knihy" for s in secs)


def test_fetch_category_options_via_stub():
    sess = StubSession({"knihy.bazos.cz/pridat-inzerat.php": _read("insert_form.html")})
    opts = category.fetch_category_options(sess, "knihy")
    assert any(o["label"] == "Dětské knihy" for o in opts)


def test_fetch_category_options_raises_gate():
    sess = StubSession({"knihy.bazos.cz/pridat-inzerat.php": _read("sms_gate.html")})
    with pytest.raises(category.GateError):
        category.fetch_category_options(sess, "knihy")
