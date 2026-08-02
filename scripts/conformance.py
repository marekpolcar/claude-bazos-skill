"""Conformance canary (DESIGN §10): live bazos vs the recorded contract.

Cheap drift detector — run before a batch session. Names exactly what changed so
the driver's assumptions are never silently stale. A rotated honeypot value in
particular is a likely account-flag risk, so it is checked explicitly.

Split for testability:
- ``check_html(pages)`` — **pure** over already-fetched HTML; empty list = conforms.
- ``check(base_url, session)`` — thin fetch wrapper around it (the LIVE canary).
"""

import re

import category

# The insert form's expected contract (from authed discovery; the LIVE canary
# reconfirms it). ``category`` is the <select>; the rest are input/textarea names.
CONTRACT = {
    "insert_fields": [
        "category", "nadpis", "popis", "cena", "cenavyber",
        "lokalita", "jmeno", "telefoni", "maili", "heslobazar",
    ],
    "honeypot": {"name": "sfdsfrtret", "value": "afdggfd"},
    "hidden": {"vkm": "m"},
    "photo_input": "souborp[]",
    "upload_url": "/upload.php",              # verified live (Dropzone) — see below
    "delete_url_re": r"/smazat/\d+\.php",     # stable delete URL shape
}


def _tag_with_name(html, name):
    for m in re.finditer(r"<(?:input|select|textarea)\b[^>]*>", html, re.I):
        tag = m.group(0)
        if re.search(r'\bname="%s"' % re.escape(name), tag):
            return tag
    return None


def _value_of(tag):
    if not tag:
        return None
    m = re.search(r'\bvalue="([^"]*)"', tag)
    return m.group(1) if m else None


def check_html(pages):
    """Pure contract check over fetched HTML.

    ``pages`` maps a role → HTML string. Recognized roles:
    ``insert_form`` (required for the field/honeypot/select checks) and optional
    ``delete_page`` (checks the /smazat/<id>.php URL shape). Returns a list of
    human-readable violations; empty == conforms.
    """
    violations = []
    form = pages.get("insert_form")
    if form is None:
        return ["no insert_form page supplied"]

    if category.is_gate(form):
        return ["insert form is the SMS gate — session not verified"]

    # <select name="category"> must exist with options
    try:
        opts = category.parse_category_options(form)
        if not opts:
            violations.append("category <select> present but has no options")
    except category.GateError:
        violations.append("insert form is the SMS gate — session not verified")
    except ValueError:
        violations.append('missing <select name="category">')

    # required field names present
    for name in CONTRACT["insert_fields"]:
        if _tag_with_name(form, name) is None:
            violations.append(f"missing insert-form field '{name}'")

    # honeypot: name present AND value unchanged (rotation is the danger)
    hp = CONTRACT["honeypot"]
    hp_tag = _tag_with_name(form, hp["name"])
    if hp_tag is None:
        violations.append(f"honeypot '{hp['name']}' missing (form changed?)")
    elif _value_of(hp_tag) != hp["value"]:
        violations.append(
            f"honeypot '{hp['name']}' value changed: "
            f"{_value_of(hp_tag)!r} != {hp['value']!r}")

    # hidden vkm=m on the insert form
    for name, expected in CONTRACT["hidden"].items():
        tag = _tag_with_name(form, name)
        if tag is None:
            violations.append(f"hidden field '{name}' missing")
        elif _value_of(tag) != expected:
            violations.append(
                f"hidden '{name}' value changed: {_value_of(tag)!r} != {expected!r}")

    # photo file input
    if _tag_with_name(form, CONTRACT["photo_input"]) is None:
        violations.append(f"photo input '{CONTRACT['photo_input']}' missing")

    # upload endpoint — only assertable when the Dropzone JS is present (live form).
    if "dropzone" in form.lower() and CONTRACT["upload_url"] not in form:
        violations.append(f"upload endpoint '{CONTRACT['upload_url']}' not referenced")

    # delete URL shape — checked when a delete page is supplied
    delete_page = pages.get("delete_page")
    if delete_page is not None and not re.search(CONTRACT["delete_url_re"], delete_page):
        violations.append(f"delete URL shape {CONTRACT['delete_url_re']!r} not found")

    return violations


def check(base_url, session):
    """LIVE canary: fetch ``<base_url>/pridat-inzerat.php`` (authed) and check it.

    ``base_url`` e.g. ``https://knihy.bazos.cz``. Returns violations (empty ==
    conforms). Delete-shape is left to the driver's interception tests since it
    needs a real ad id.
    """
    r = session.get(f"{base_url}/pridat-inzerat.php", timeout=25, allow_redirects=True)
    return check_html({"insert_form": category._text(r)})
