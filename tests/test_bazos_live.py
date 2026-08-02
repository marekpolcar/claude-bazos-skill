"""LIVE driver integration for vlozit — real bazos form, real Dropzone, all
writes intercepted. Run with ``pytest -m live`` (needs a verified session +
chromium). See test_harness.py for the guard itself.
"""

import os
import subprocess

import pytest

import auth
import bazos
import category

pytestmark = pytest.mark.live

SEKCE = "knihy"
INSERT_URL = f"https://{SEKCE}.bazos.cz/pridat-inzerat.php"


def _tiny_jpeg(tmp_path):
    """A real (portable) JPEG so Dropzone's client-side handling is exercised."""
    import base64
    png = tmp_path / "s.png"
    png.write_bytes(base64.b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGA"
        "WjR9awAAAABJRU5ErkJggg=="))
    jpg = tmp_path / "s.jpg"
    subprocess.run(["sips", "-s", "format", "jpeg", str(png), "--out", str(jpg)],
                   check=True, capture_output=True)
    return str(jpg)


def _live_category_value(harness):
    page = harness.context.new_page()
    page.goto(INSERT_URL, wait_until="load")
    html = page.content()
    page.close()
    if category.is_gate(html):
        pytest.skip("insert form is the SMS gate — session not verified")
    opts = category.parse_category_options(html)
    assert opts, "no live category options"
    return opts[0]["value"]


def _ad(harness, tmp_path):
    ident = auth.get_identity()  # from the live session cookies
    return {
        "nadpis": "TEST – nezveřejňovat (harness)",
        "popis": "Toto je test ovladače, nikdy se neodešle (guard).",
        "cena": 111,
        "sekce": SEKCE,
        "category": _live_category_value(harness),
        "lokalita": "110 00",
        "jmeno": ident["jmeno"] or "Jan Novák",
        "telefon": ident["telefon"] or "777123456",
        "email": ident["email"] or "jan.novak@example.com",
        "photos": [_tiny_jpeg(tmp_path)],
    }


def test_vlozit_preview_fills_and_leaves_honeypot(harness, tmp_path):
    harness.intercept("**/upload.php", harness.upload_ok)
    res = bazos.vlozit(_ad(harness, tmp_path), preview=True,
                       context=harness.context, screenshot_dir=str(tmp_path))
    assert os.path.exists(res["screenshot"])
    assert res["fields"]["telefoni"]
    # no mutating request escaped to live bazos
    assert not any(r["url"].endswith("/insert.php") for r in harness.aborted)


def test_vlozit_submit_captures_payload(harness, tmp_path):
    harness.intercept("**/upload.php", harness.upload_ok)
    harness.intercept("**/insert.php", harness.insert_capture)
    res = bazos.vlozit(_ad(harness, tmp_path), preview=False,
                       context=harness.context)
    # success is the "byl vložen" page; the driver reads the new ad's id from its
    # ad list by matching the submitted nadpis (insert_capture echoes it)
    assert res["id"] == "999000111"
    payload = harness.last_payload("**/insert.php")
    assert payload and "afdggfd" in payload   # honeypot present + unchanged
    assert "111" in payload                    # cena in the submitted body
