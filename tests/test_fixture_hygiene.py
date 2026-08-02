"""Hygiene gate: NO personal data may enter the repo via fixtures.

Scans every committed fixture for phone-like (Czech mobile) and email-like
strings and asserts each is a known non-PII value (the fake identity, or bazos's
own system domains). This is what makes the "no personal data in the repo" claim
in the README verifiable — third-party seller PII from list/detail pages, or the
user's own identity from an authed capture, would trip it.
"""

import glob
import os
import re

import scrub_fixtures

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")

# Czech mobile numbers: optional +420, then 6/7 + 8 digits. The (?<!\d)/(?!\d)
# boundaries keep it from matching a 9-digit run embedded in a longer number
# (e.g. an ISBN like 9788076882164 is not a phone).
PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?420[\s\-]?)?([67]\d{2}[\s\-]?\d{3}[\s\-]?\d{3})(?!\d)")
EMAIL_RE = re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}")

# The only phone allowed to appear anywhere in fixtures: the fake identity's.
ALLOWED_PHONES = {"777123456"}
# Emails may only be the fake identity or bazos's own system domains (not user PII).
ALLOWED_EMAIL_DOMAINS = {"example.com", "bazos.cz"}


def _fixture_files():
    # every committed text fixture, recursively — .md folder fixtures included,
    # so the "no PII in the repo" guarantee covers the whole tree (PLAN Step 5).
    out = []
    for ext in ("*.html", "*.md", "*.txt"):
        out += glob.glob(os.path.join(FIXTURES, "**", ext), recursive=True)
    return sorted(out)


def _norm_phone(s):
    return re.sub(r"\D", "", s)


def test_there_are_fixtures():
    assert _fixture_files(), "no fixtures found — nothing to vet"


def test_scan_includes_md_folder_fixtures():
    # the guarantee must cover the .md folder fixtures, not just top-level .html
    files = _fixture_files()
    assert any(f.endswith(".md") for f in files)
    assert any(os.path.join("kniha", "inzerat.md") in f for f in files)
    assert any(os.path.join("kniha-bez-fotek", "inzerat.md") in f for f in files)


def test_no_unexpected_phone_numbers():
    offenders = []
    for path in _fixture_files():
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for m in PHONE_RE.finditer(text):
            if _norm_phone(m.group(1)) not in ALLOWED_PHONES:
                offenders.append((os.path.basename(path), m.group(0)))
    assert not offenders, f"non-whitelisted phone-like strings in fixtures: {offenders}"


def test_no_unexpected_emails():
    offenders = []
    for path in _fixture_files():
        with open(path, encoding="utf-8") as f:
            text = f.read()
        for m in EMAIL_RE.finditer(text):
            domain = m.group(0).rsplit("@", 1)[1].lower()
            if domain not in ALLOWED_EMAIL_DOMAINS:
                offenders.append((os.path.basename(path), m.group(0)))
    assert not offenders, f"non-whitelisted emails in fixtures: {offenders}"


def test_scrub_text_replaces_real_with_fake():
    repl = {
        "Marek Skutečný": "Jan Novák",
        "608111222": "777123456",
        "marek.real@gmail.com": "jan.novak@example.com",
    }
    raw = ('<input name="jmeno" value="Marek Skutečný">'
           '<span>608111222</span> marek.real@gmail.com')
    out = scrub_fixtures.scrub_text(raw, repl)
    assert "Marek Skutečný" not in out
    assert "608111222" not in out
    assert "marek.real@gmail.com" not in out
    assert "Jan Novák" in out and "777123456" in out and "jan.novak@example.com" in out
    # markup untouched
    assert 'name="jmeno"' in out


def test_scrub_text_longest_key_first():
    # A short key that is a substring of a longer one must not corrupt it.
    repl = {"420": "000", "420777123456": "FULLNUM"}
    assert scrub_fixtures.scrub_text("420777123456", repl) == "FULLNUM"
