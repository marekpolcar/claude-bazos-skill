"""Live category resolver (DESIGN §6): sections + a section's category options.

Two levels, both read **live** so bazos relabels/reorders without breaking us:

1. **Sekce** (subdomain) — from the homepage nav anchors (anonymous OK).
2. **Rubrika** — the ``<select name="category">`` on the section's authed
   ``pridat-inzerat.php``. This is **auth-gated**: an anonymous GET returns the
   SMS gate (``formovereni``) with zero options, so the fetcher raises
   ``GateError`` rather than returning silently empty.

No hardcoded category map — the model picks by label, seeded by the folder's
``kategorie_hint``.
"""

import re

_TAG_RE = re.compile(r"<[^>]+>")
_SECTION_A_RE = re.compile(
    r'<a\s+href="https://([a-z0-9]+)\.bazos\.cz/"[^>]*>(.*?)</a>', re.I | re.S)
_SELECT_RE = re.compile(
    r'<select[^>]*\bname="category"[^>]*>(.*?)</select>', re.I | re.S)
_OPTION_RE = re.compile(
    r'<option[^>]*\bvalue="([^"]*)"[^>]*>(.*?)</option>', re.I | re.S)


class GateError(RuntimeError):
    """The page came back as the SMS-verification gate, not the expected form.

    Distinguishable so the orchestrator can surface it and ask the user to
    (re)verify, rather than treating it as "no categories exist" (§9).
    """


def _strip_tags(s):
    return _TAG_RE.sub("", s).strip()


def is_gate(html):
    return "formovereni" in html.lower()


def parse_sections(html):
    """Homepage nav → ``[{"name","subdomain","url"}, …]`` (deduped, www excluded)."""
    seen = set()
    out = []
    for sub, label in _SECTION_A_RE.findall(html):
        sub = sub.lower()
        label = _strip_tags(label)
        if sub == "www" or not label or sub in seen:
            continue  # img-only anchors have empty label; www is not a section
        seen.add(sub)
        out.append({"name": label, "subdomain": sub, "url": f"https://{sub}.bazos.cz"})
    return out


def parse_category_options(html):
    """``<select name="category">`` → ``[{"value","label"}, …]`` (placeholder skipped).

    Raises ``GateError`` if the page is the SMS gate, ``ValueError`` if there is
    simply no category select (unexpected markup — surface, don't guess).
    """
    m = _SELECT_RE.search(html)
    if m is None:
        if is_gate(html):
            raise GateError("insert form is the SMS gate — session not verified")
        raise ValueError("no <select name=\"category\"> in page")
    opts = []
    for value, label in _OPTION_RE.findall(m.group(1)):
        value = value.strip()
        label = _strip_tags(label)
        # Skip the "Vyber kategorii" placeholder. bazos encodes it as value "0"
        # (its no-category sentinel), not an empty value — and submitting with
        # category=0 trips client-side validation, so the POST never fires. Never
        # offer it to the model as a real rubrika.
        if not value or value == "0":
            continue
        opts.append({"value": value, "label": label})
    return opts


def _text(resp):
    """Decode honoring charset; avoid the requests ISO-8859-1 default that would
    mojibake Czech diacritics when the server omits a charset."""
    enc = (resp.encoding or "").lower()
    if not enc or enc in ("iso-8859-1", "latin-1"):
        resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.text


def fetch_sections(session):
    r = session.get("https://www.bazos.cz/", timeout=25, allow_redirects=True)
    return parse_sections(_text(r))


def fetch_category_options(session, subdomain):
    """Authed GET of the section's insert form → category options.

    Requires a verified session; raises ``GateError`` on the SMS gate.
    """
    url = f"https://{subdomain}.bazos.cz/pridat-inzerat.php"
    r = session.get(url, timeout=25, allow_redirects=True)
    html = _text(r)
    if is_gate(html):
        raise GateError(f"{url} returned the SMS gate — verify the session")
    return parse_category_options(html)
