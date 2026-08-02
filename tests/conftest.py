"""Interception test harness — write-guard over the LIVE bazos site (DESIGN §10).

Supersedes a local mock server: driver tests run against the real current page
with its real JS and real Dropzone, read-only, with **every non-GET request
aborted by default**. Only a test's explicit interceptors may fulfill a write
with a faked response — so no mutating request can escape to live bazos during
development. A categorical guarantee, not env-var discipline.

Everything here only instantiates Playwright inside the ``harness`` fixture, so
the offline unit suite (which never requests it) is unaffected. Driver
integration tests that use ``harness`` are marked ``@pytest.mark.live``.

NOTE on the ``/upload.php`` response format: calibrated live (Task 5) — an authed
upload POST returns ``200 text/html`` with a JSON **array** of the stored
filename(s), e.g. ``["d_19f23….jpg"]``. Dropzone's success callback reads that
array and injects one hidden ``<input name="files[]" value="…">`` per file into
``formpridani``. ``upload_ok`` mirrors that shape so the driver's ``files[]`` wait
resolves under the harness exactly as it does live.
"""

import re

import pytest

import auth


def _form_field(body, name):
    """Best-effort value of a submitted form field, from a urlencoded (edit) or
    multipart/form-data (insert) POST body — enough for fixtures to echo it back."""
    if not body:
        return ""
    from urllib.parse import parse_qs
    q = parse_qs(body)
    if name in q:
        return q[name][0]
    m = re.search(r'name="%s"\r?\n\r?\n(.*?)\r?\n--' % re.escape(name), body, re.S)
    return m.group(1).strip() if m else ""


class Harness:
    def __init__(self, context):
        self.context = context
        self.aborted = []          # non-GET requests the guard blocked
        self._payloads = {}         # pattern -> last captured raw post body
        self._counts = {}           # pattern -> call count (for fail-once)

    # --- guard -------------------------------------------------------------
    def install_guard(self):
        """Abort + record every non-GET; let GETs reach live bazos."""
        def guard(route, request):
            if request.method == "GET":
                route.continue_()
            else:
                self.aborted.append({"method": request.method, "url": request.url})
                route.abort()
        self.context.route("**/*", guard)

    # --- allowed interceptors (registered later → take precedence) ---------
    def intercept(self, pattern, handler):
        """Register a write-interceptor on top of the guard.

        ``handler(route, request, harness)`` — must fulfill/abort the route.
        """
        self.context.route(pattern, lambda route, request: handler(route, request, self))

    def _capture(self, pattern, request):
        try:
            self._payloads[pattern] = request.post_data
        except Exception:
            self._payloads[pattern] = None

    def last_payload(self, pattern):
        return self._payloads.get(pattern)

    # --- canned interceptors ----------------------------------------------
    def upload_ok(self, route, request, _h=None):
        self._capture("**/upload.php", request)
        n = self._counts.get("upload", 0) + 1
        self._counts["upload"] = n
        # Real /upload.php shape (see module note): text/html body carrying a JSON
        # array of the stored filename(s). Dropzone reads it and wires files[].
        route.fulfill(status=200, content_type="text/html; charset=UTF-8",
                      body='["fake%d.jpg"]' % n)

    def upload_fail_once(self, route, request, _h=None):
        n = self._counts.get("upload_fail", 0) + 1
        self._counts["upload_fail"] = n
        if n == 1:
            route.fulfill(status=500, content_type="text/plain", body="err")
        else:
            self.upload_ok(route, request)

    def insert_capture(self, route, request, _h=None):
        self._capture("**/insert.php", request)
        # Mirror the REAL success page (calibrated Task 9): insert.php does NOT
        # redirect to the ad detail — it returns "Inzerát byl vložen/změněn" plus
        # your ad list, from which the driver reads the new ad's id by matching the
        # submitted nadpis. Echo that nadpis into a /inzerat/<id>/ anchor.
        nadpis = _form_field(request.post_data, "nadpis")
        route.fulfill(status=200, content_type="text/html; charset=UTF-8",
                      body='<html><body><h2>Inzerát byl vložen/změněn</h2>'
                           'Vaše inzeráty:'
                           '<a href="https://knihy.bazos.cz/inzerat/999000111/x.php">'
                           '%s</a></body></html>' % nadpis)

    def write_capture(self, url_pattern):
        """Generic capture-and-OK interceptor factory for a given URL pattern."""
        def handler(route, request, _h=None):
            self._capture(url_pattern, request)
            route.fulfill(status=200, content_type="text/html",
                          body="<html><body>OK</body></html>")
        return handler

    def edit_form(self, ad_id):
        """Interceptor: fulfil ``deletei2.php`` (the "Upravit" action target) with a
        minimal but contract-faithful edit form for ``ad_id``.

        Mirrors the live editor captured in Task 7: a ``formpridani`` that POSTs to
        ``insert.php``, carrying the hidden ``idad`` (so a save updates, not
        duplicates) and the honeypot pair (``sfdsfrtret``/``vkm``). Lets the edit
        driver run under the guard without a live POST reaching bazoš.
        """
        def handler(route, request, _h=None):
            self._capture("**/deletei2.php", request)
            route.fulfill(status=200, content_type="text/html; charset=UTF-8",
                          body='<html><body>'
                               '<form name="formpridani" action="/insert.php" method="post">'
                               '<input type="hidden" name="idad" value="%s">'
                               '<input type="hidden" name="sfdsfrtret" value="afdggfd">'
                               '<input type="hidden" name="vkm" value="m">'
                               '<input type="text" name="nadpis" value="Puvodni">'
                               '<input type="text" name="cena" value="">'
                               '<input type="submit" name="Submit" value="Odeslat">'
                               '</form></body></html>' % ad_id)
        return handler


@pytest.fixture
def harness():
    """Guarded live Playwright context from the cached session (no Keychain).

    Uses ``get_storage_state(interactive=False)`` — a cached ``state.json`` must
    exist (run the Task 4 integration checkpoint once). Skips cleanly if not.
    """
    from playwright.sync_api import sync_playwright
    try:
        state = auth.get_storage_state(interactive=False)
    except auth.AuthError:
        pytest.skip("no cached bazos session (state.json) — run the auth checkpoint")
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(storage_state=state, user_agent=auth.UA)
        h = Harness(context)
        h.install_guard()
        try:
            yield h
        finally:
            context.close()
            browser.close()
