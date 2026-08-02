"""Self-tests for the interception harness. LIVE: needs chromium + a cached
session; run with ``pytest -m live``."""

import pytest

pytestmark = pytest.mark.live


def test_get_passes_through(harness):
    page = harness.context.new_page()
    resp = page.goto("https://www.bazos.cz/", wait_until="domcontentloaded")
    assert resp.status < 400
    assert not harness.aborted  # a plain GET escapes nothing to abort
    page.close()


def test_non_get_is_aborted_and_recorded(harness):
    page = harness.context.new_page()
    page.goto("https://www.bazos.cz/", wait_until="domcontentloaded")
    # Fire a POST from the page; the guard must abort it (network error) + record.
    page.evaluate(
        "() => fetch('https://www.bazos.cz/insert.php', {method:'POST', body:'x'})"
        ".catch(() => null)")
    page.wait_for_timeout(500)
    assert any(r["method"] == "POST" and "insert.php" in r["url"]
               for r in harness.aborted)
    page.close()


def test_upload_interceptor_fulfills_and_captures(harness):
    harness.intercept("**/upload.php", harness.upload_ok)
    page = harness.context.new_page()
    page.goto("https://www.bazos.cz/", wait_until="domcontentloaded")
    body = page.evaluate(
        "async () => { const r = await fetch('https://knihy.bazos.cz/upload.php',"
        "{method:'POST', body:'photo-bytes'}); return await r.text(); }")
    assert body == '["fake1.jpg"]'                 # fulfilled (real /upload.php shape)
    assert harness.last_payload("**/upload.php") == "photo-bytes"
    assert not any("upload.php" in r["url"] for r in harness.aborted)
    page.close()
