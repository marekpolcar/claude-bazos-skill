"""LIVE integration for smazat + upravit against the user's own ads, all writes
intercepted (nothing is really deleted or saved). Run with ``pytest -m live``.

Both ops go through the real ``/smazat/<id>.php`` MANAGE page (GET, driven live)
and act via its ``administrace`` submits ("Upravit"/"Vymazat"), which POST to
``deletei2.php``. Because reaching the edit form / delete confirm requires that
POST — which the guard aborts — the tests intercept ``deletei2.php`` (and
``insert.php`` for the edit save) and fulfil it with a contract-faithful fixture.
So the real manage page + real ``administrace`` buttons are exercised live, while
no mutating request escapes to bazoš. The live-discovery of the manage-page shape
(URL, buttons, pre-filled password) was settled in Task 6/7 calibration.
"""

import os
from urllib.parse import urlparse

import pytest

import bazos
import category
import moje

pytestmark = pytest.mark.live


def _bazos_aborted(aborted):
    """Aborted requests whose HOST is a bazoš host — i.e. a real bazoš write the
    guard blocked. Excludes third-party beacons (google-analytics) that merely
    carry the page URL in a ``dl=…bazos.cz…`` query param.
    """
    return [r for r in aborted
            if (urlparse(r["url"]).hostname or "").endswith("bazos.cz")]


def _own_ad(harness):
    page = harness.context.new_page()
    page.goto("https://www.bazos.cz/moje-inzeraty.php", wait_until="load")
    html = page.content()
    page.close()
    if category.is_gate(html):
        pytest.skip("moje-inzeraty is the gate — session not verified")
    ads = moje.parse_moje_inzeraty(html)
    if not ads:
        pytest.skip("no own ads to target")
    return next((a for a in ads if a["sekce"]), ads[0])


def test_smazat_preview_screenshots_the_right_ad(harness, tmp_path):
    ad = _own_ad(harness)
    res = bazos.smazat(ad["id"], ad["sekce"], preview=True,
                       context=harness.context, screenshot_dir=str(tmp_path))
    assert os.path.exists(res["screenshot"])
    assert res["id"] == ad["id"]
    # read-only: no delete escaped
    assert not any("/smazat/" in r["url"] for r in harness.aborted)


def test_smazat_confirm_is_intercepted(harness, tmp_path):
    ad = _own_ad(harness)
    # deletion is the manage page's "Vymazat" action → POST deletei2.php
    harness.intercept("**/deletei2.php", harness.write_capture("**/deletei2.php"))
    bazos.smazat(ad["id"], ad["sekce"], preview=False, context=harness.context)
    # the Vymazat POST hit deletei2.php and was faked; no bazoš write escaped
    assert harness.last_payload("**/deletei2.php") is not None
    assert not _bazos_aborted(harness.aborted)


def test_upravit_preview_stages_change(harness, tmp_path):
    ad = _own_ad(harness)
    harness.intercept("**/deletei2.php", harness.edit_form(ad["id"]))
    res = bazos.upravit(ad["id"], ad["sekce"], {"cena": 111}, preview=True,
                        context=harness.context, screenshot_dir=str(tmp_path))
    assert os.path.exists(res["screenshot"])
    assert res["changed"].get("cena") == "111"
    # the "Upravit" POST was intercepted; no bazoš write escaped the guard
    assert harness.last_payload("**/deletei2.php") is not None
    assert not _bazos_aborted(harness.aborted)


def test_upravit_save_captures_change(harness, tmp_path):
    ad = _own_ad(harness)
    harness.intercept("**/deletei2.php", harness.edit_form(ad["id"]))
    harness.intercept("**/insert.php", harness.insert_capture)  # returns the marker
    res = bazos.upravit(ad["id"], ad["sekce"], {"cena": 111}, preview=False,
                        context=harness.context)
    # confirmed saved via the shared "vložen/změněn" marker (not blindly claimed)
    assert res["updated"] is True
    # the save POSTs the edit form to insert.php carrying the change + the ad's
    # idad (so it UPDATES this ad, not creates a duplicate)
    payload = harness.last_payload("**/insert.php")
    assert payload and "111" in payload and ad["id"] in payload
    assert not _bazos_aborted(harness.aborted)
