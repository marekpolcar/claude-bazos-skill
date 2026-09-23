"""Playwright driver + CLI for bazos-inzerce: vlozit / smazat / upravit.

Pure, offline-tested helpers (photo prep, schema→form mapping) are separated
from the live Playwright flow. The driver never touches the honeypot
(`sfdsfrtret`) or hidden `vkm`. Real submits/deletes run headed; tests drive the
live pages headless under the interception harness (all writes intercepted).

See references/form-contract.md for the field contract.
"""

import argparse
import datetime
import os
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager

import ad_schema
import auth
import category as category_mod

PREVIEW_DIR = os.path.expanduser("~/.bazos-inzerce/previews")

# schema key -> live form field name (note telefon→telefoni, email→maili)
FIELD_MAP = {
    "nadpis": "nadpis",
    "popis": "popis",
    "cena": "cena",
    "lokalita": "lokalita",
    "jmeno": "jmeno",
    "telefon": "telefoni",
    "email": "maili",
    "heslobazar": "heslobazar",
}
SELECT_FIELDS = {"category", "cenavyber", "typ"}  # <select> widgets, not text inputs


# --- pure helpers (offline-tested) ------------------------------------------

def form_field_values(ad):
    """schema ad dict → ``{form_field_name: str_value}`` for the text inputs.

    Excludes photos, sekce, and the <select> fields (category/cenavyber), which
    the driver sets separately. Derived wrappers are unwrapped.
    """
    out = {}
    for schema_key, form_key in FIELD_MAP.items():
        v = ad_schema._value(ad.get(schema_key))
        if v is None or (isinstance(v, str) and not v.strip()):
            continue
        out[form_key] = str(v)
    return out


def submit_blockers(ad, existing_ads):
    """Reasons a publish must refuse (binding safety constraints), or [].

    Enforced in code at the --submit boundary, not only in SKILL.md prose:
    idempotency (already published), never-fabricate (unconfirmed derived
    fields), and the mandatory pre-insert dedupe (bazoš auto-deletes the OLDER
    of two identical ads).
    """
    import moje as moje_mod
    reasons = []
    if ad_schema._value(ad.get("published_url")):
        reasons.append("already published (published_url present) — skip or renew")
    derived = ad_schema.derived_fields(ad)
    if derived:
        reasons.append(f"unconfirmed derived fields (confirm first): {derived}")
    dup = moje_mod.find_by_title(existing_ads,
                                 ad_schema._value(ad.get("nadpis")) or "")
    if dup:
        reasons.append(f"duplicate already live (id {dup['id']}) — bazoš would "
                       "auto-delete the older; skip")
    return reasons


# Fields the folder cannot and must not supply: contact comes from the session,
# sekce/category from the live resolver — both arrive at publish time.
SESSION_OR_RESOLVER_FIELDS = ("jmeno", "telefon", "email", "sekce", "category")
_MISSING_PHOTO_MSG = "je potřeba alespoň 1 fotka"  # ad_schema's exact wording


def zkontrolovat_report(folder):
    """Offline folder check → {valid, problems, derived, missing_photos}.

    A photo-less folder (from-name draft, photos still TODO) reports
    missing_photos=true instead of a photo problem. ``valid`` means the
    folder's own contract is complete; unconfirmed ``derived`` fields do NOT
    invalidate — confirming them is the publish guard's job (second gate).
    """
    import parse_inzerat
    try:
        ad = parse_inzerat.parse_folder(folder)
    except Exception as e:
        return {"valid": False,
                "problems": [f"nelze načíst složku: {e}"],
                "derived": [],
                "missing_photos": False}
    for f in SESSION_OR_RESOLVER_FIELDS:
        ad.setdefault(f, "(doplní se při publikaci)")
    problems = ad_schema.validate(ad)
    missing_photos = not (ad_schema._value(ad.get("photos")) or [])
    if missing_photos:
        problems = [m for m in problems if m != _MISSING_PHOTO_MSG]
    return {"valid": not problems and not missing_photos,
            "problems": problems,
            "derived": ad_schema.derived_fields(ad),
            "missing_photos": missing_photos}


def _convert_to_jpeg(src, dst):
    import fotky
    fotky.convert_to_jpeg(src, dst)


def prepare_photos(photos, workdir):
    """Convert non-JPEG photos to JPEG (bazos accepts .jpeg only), cap at 20,
    preserve order. Returns the list of upload-ready JPEG paths."""
    os.makedirs(workdir, exist_ok=True)
    prepared = []
    for i, p in enumerate(photos[:ad_schema.MAX_PHOTOS]):
        ext = os.path.splitext(p)[1].lower()
        if ext in ad_schema.JPEG_EXTS:
            prepared.append(p)
        elif ext in ad_schema.CONVERTIBLE_EXTS:
            dst = os.path.join(workdir, f"photo_{i:02d}.jpg")
            _convert_to_jpeg(p, dst)
            prepared.append(dst)
        else:
            raise ValueError(f"unsupported photo format (not convertible): {p}")
    return prepared


def _timestamp():
    return datetime.datetime.now().strftime("%Y%m%d-%H%M%S")


# --- live Playwright flow ----------------------------------------------------

@contextmanager
def _session_page(context, storage_state, headed):
    """Yield a page on the given context, or build a fresh one from the session.

    ``context`` injected (harness tests) → used as-is, no browser owned. Else a
    browser is launched (``headed`` for real writes) from ``storage_state`` /
    ``auth.get_storage_state`` and torn down afterwards.
    """
    owns = context is None
    pw = browser = page = None
    try:
        if owns:
            from playwright.sync_api import sync_playwright
            pw = sync_playwright().start()
            browser = pw.chromium.launch(headless=not headed)
            state = storage_state or auth.get_storage_state()
            context = browser.new_context(storage_state=state, user_agent=auth.UA)
        page = context.new_page()
        yield page
    finally:  # tears down even if setup above raised (no orphaned Chromium)
        if page is not None:
            page.close()
        if owns:
            if context is not None:
                context.close()
            if browser is not None:
                browser.close()
            if pw is not None:
                pw.stop()


def _assert_not_gate(page):
    if page.query_selector("form[name=formovereni]"):
        raise auth.AuthError("page came back as the SMS gate — session not verified")


def _page_error_text(page):
    """Best-effort on-page error text (calibrated against the real error markup
    at the live checkpoint); None if nothing obvious."""
    for sel in (".chyba", ".error", ".alert", ".varovani", ".upozorneni"):
        el = page.query_selector(sel)
        if el:
            t = (el.inner_text() or "").strip()
            if t:
                return t
    return None


def _click_administrace(page, value):
    """Click a manage-page action button (``<input name="administrace" value=…>``).

    ``/smazat/<id>.php`` is a combined manage page (title "Vymazání/Úprava"): its
    ``administrace`` submits ("Upravit", "Vymazat") both POST to ``deletei2.php``.
    Returns True if the named action was found and clicked.
    """
    for el in page.query_selector_all('input[name="administrace"]'):
        if (el.get_attribute("value") or "").strip().lower() == value.lower():
            el.click()
            return True
    return False


def _assert_edit_form_targets_ad(page, ad_id):
    """Refuse to save an edit unless the form carries the ad's hidden ``idad``.

    The edit form is the same ``formpridani`` that ``insert.php`` uses; only the
    server-injected ``idad`` makes the submit UPDATE this ad instead of CREATING a
    new one (and bazoš auto-deletes the older of two identical ads). A missing or
    mismatched ``idad`` means we're not really on this ad's editor — abort.
    """
    el = page.query_selector('input[name="idad"]')
    idad = el.get_attribute("value") if el else None
    if idad != str(ad_id):
        raise RuntimeError(
            f"edit form idad={idad!r} != {ad_id!r} — refusing to save (would "
            "create a duplicate instead of updating this ad)")


def _delete_confirmed(page, ad_id):
    """True iff the delete took effect (call on the post-"Vymazat" page).

    Calibrated by a real delete (Task 6): the manage page's "Vymazat" deletes
    IMMEDIATELY — ``deletei2.php`` returns "Inzerát byl vymazán z našeho bazaru."
    with **no** second confirmation step, and lists your remaining ads only as
    ``<a>`` manage links (never buttons). Trust that success marker; fall back to
    confirming the ad is gone from moje-inzeraty.

    Deliberately does NOT click any "confirm" control: there is no confirm step,
    and the sibling ads' "Smazat/Upravit/Topovat" links (which contain "smaz")
    would be a mis-click hazard if bazoš ever rendered them as buttons.
    """
    if "byl vymazán" in page.content().lower():
        return True
    return _verify_absent(page, ad_id)


def _fill_insert_form(page, values, category_value, cenavyber_value=None,
                      typ_label=None):
    # Some sections (Reality) carry a required <select name="type"> Prodej /
    # Pronájem. The conformance canary does not see it and the preview does not
    # fail on it — left unset, the ad would be refused or filed as the wrong
    # type — so refuse here, before anything is filled.
    if page.query_selector('select[name="type"]'):
        if not typ_label:
            raise ValueError("rubrika vyžaduje Typ (Prodej/Pronájem): doplň "
                             "'- **Typ:** Pronájem' do inzerat.md nebo --typ")
        page.select_option('select[name="type"]', label=typ_label)
    for name, val in values.items():
        page.fill(f'[name="{name}"]', val)
    page.select_option('select[name="category"]', category_value)
    if cenavyber_value:
        page.select_option('select[name="cenavyber"]', cenavyber_value)


def _files_wired(page):
    return page.eval_on_selector_all(
        'input[name="files[]"]',
        "els => els.filter(e => e.value && e.value.length).length")


def _clear_dropzone(page):
    """Reset any files already staged, so a retry re-uploads instead of appending
    (avoids duplicate photos when the first attempt partially succeeded)."""
    try:
        page.set_input_files("input.dz-hidden-input", [])
    except Exception:
        pass
    # best-effort: tell a Dropzone instance to drop its previews too
    try:
        page.evaluate(
            "() => { if (window.Dropzone) { "
            "document.querySelectorAll('.dropzone').forEach(el => { "
            "const dz = window.Dropzone.forElement ? "
            "Dropzone.forElement(el) : null; if (dz) dz.removeAllFiles(true); }); "
            "} }")
    except Exception:
        pass


def _set_photos_and_wait(page, photos, timeout_ms=30000):
    """Set files on Dropzone's hidden input and wait for it to wire ``files[]`` to n.

    The live form uses Dropzone: the upload widget is ``input.dz-hidden-input``
    (an unnamed, visually-hidden input Dropzone injects), NOT a named field.
    Each file POSTs to ``/upload.php``, which returns a JSON array of the stored
    filename(s) (``["d_….jpg"]``); Dropzone's success callback then injects a
    hidden ``<input name="files[]" value="d_….jpg">`` into ``formpridani`` — those
    are what the insert submit actually carries. On a first miss, clear and retry
    ONCE (§9); then report (caller decides).
    """
    for attempt in (1, 2):
        if attempt == 2:
            _clear_dropzone(page)
        page.set_input_files("input.dz-hidden-input", photos)
        try:
            page.wait_for_function(
                "n => Array.from(document.querySelectorAll('input[name=\"files[]\"]'))"
                ".filter(e => e.value && e.value.length).length >= n",
                arg=len(photos), timeout=timeout_ms)
            return True
        except Exception:
            if attempt == 2:
                return _files_wired(page) >= len(photos)
    return False


def _honeypot_untouched(page):
    """Strict: the honeypot + hidden vkm must be present and unmodified."""
    hp = page.get_attribute('input[name="sfdsfrtret"]', "value")
    vkm = page.get_attribute('input[name="vkm"]', "value")
    return hp == "afdggfd" and vkm == "m"


def _honeypot_untouched_if_present(page):
    """Tolerant variant for forms where the honeypot's presence is unconfirmed
    (edit form — Task 7 live discovery). Absent honeypot → nothing to assert."""
    if page.query_selector('input[name="sfdsfrtret"]') is None:
        return True
    return _honeypot_untouched(page)


def _insert_ok_marker(page):
    """True if the page is bazoš's insert/edit success confirmation.

    Both insert and edit-save POST to ``insert.php`` and land on the same page:
    "Inzerát byl vložen/změněn" (vložen = inserted, změněn = changed).
    """
    t = page.content().lower()
    return "byl vložen" in t or "změněn" in t


def _insert_result(page, nadpis, screenshot_dir):
    """Resolve the outcome of an insert submit — never claim an unverified success.

    Real success is NOT a redirect to ``/inzerat/<id>/``: bazoš lands back on
    ``insert.php`` showing "Inzerát byl vložen/změněn" plus your ad list (and a
    topování upsell). Confirm via that marker and read the new ad's id from the
    listed anchors by matching ``nadpis``. A direct ``/inzerat/`` URL, should it
    ever occur, is accepted as a fallback.
    """
    import moje
    html = page.content()
    ok = _insert_ok_marker(page) or re.search(r"/inzerat/\d+/", page.url)
    if ok:
        match = moje.find_by_title(moje.parse_moje_inzeraty(html), nadpis or "")
        if match:
            return {"url": match["url"], "id": match["id"]}
        m = re.search(r"/inzerat/(\d+)/", page.url)
        if m:
            return {"url": page.url, "id": m.group(1)}
        # published (marker seen) but id not resolvable — report without a false id
        return {"published": True, "id": None, "url": page.url,
                "warning": "ad published but its id could not be read from the "
                           "confirmation page — verify via `moje`"}
    err = _page_error_text(page)
    os.makedirs(screenshot_dir or PREVIEW_DIR, exist_ok=True)
    shot = os.path.join(screenshot_dir or PREVIEW_DIR,
                        f"{_timestamp()}-vlozit-error.png")
    page.screenshot(path=shot, full_page=True)
    return {"error": err or "submit did not yield a live ad",
            "url": page.url, "screenshot": shot}


def vlozit(ad, *, preview=True, context=None, storage_state=None,
           screenshot_dir=None):
    """Insert an ad. ``preview=True`` fills + screenshots + stops (no submit).

    ``context`` (a Playwright context) is injectable for harness-guarded tests;
    otherwise one is built from ``storage_state`` / ``auth.get_storage_state``.
    Returns a preview dict or, on submit, ``{"url","id"}``.
    """
    problems = ad_schema.validate(ad)
    if problems:
        raise ValueError("ad invalid: " + "; ".join(problems))

    sekce = ad_schema._value(ad.get("sekce"))
    category_value = ad_schema._value(ad.get("category"))
    cenavyber_value = ad_schema._value(ad.get("cenavyber"))
    typ_value = ad_schema._value(ad.get("typ"))
    values = form_field_values(ad)
    workdir = tempfile.mkdtemp(prefix="bazos-photos-")
    try:
        photos = prepare_photos(ad_schema._value(ad["photos"]), workdir)

        with _session_page(context, storage_state, headed=not preview) as page:
            page.goto(f"https://{sekce}.bazos.cz/pridat-inzerat.php",
                      wait_until="load")
            _assert_not_gate(page)
            _fill_insert_form(page, values, category_value, cenavyber_value,
                              typ_value)
            photos_ok = _set_photos_and_wait(page, photos)
            if not _honeypot_untouched(page):
                raise RuntimeError("honeypot/vkm changed during fill — aborting")

            if preview:
                os.makedirs(screenshot_dir or PREVIEW_DIR, exist_ok=True)
                shot = os.path.join(screenshot_dir or PREVIEW_DIR,
                                    f"{_timestamp()}-vlozit.png")
                page.screenshot(path=shot, full_page=True)
                return {
                    "screenshot": shot,
                    "fields": values,
                    "category": {"sekce": sekce, "value": category_value},
                    "photos": photos,
                    "photos_ok": photos_ok,
                }

            page.click('form[name="formpridani"] input[type="submit"]')
            try:  # wait for the success marker OR an ad-detail URL, then classify
                page.wait_for_function(
                    "() => /byl vlo\\u017een/i.test(document.body.innerText) "
                    "|| /\\/inzerat\\/\\d+\\//.test(location.href)",
                    timeout=30000)
            except Exception:
                pass  # _insert_result inspects the page and reports the error
            return _insert_result(page, ad_schema._value(ad.get("nadpis")),
                                  screenshot_dir)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def smazat(ad_id, sekce, *, preview=True, context=None, storage_state=None,
           heslobazar=None, screenshot_dir=None):
    """Delete an ad by id via the manage page. ``preview=True`` screenshots it + stops.

    ``/smazat/<id>.php`` is the combined manage page (its ``heslobazar`` is
    pre-filled for your own logged-in ads — bazoš doesn't re-check it for the
    owner session); deletion is its "Vymazat" action, which POSTs to
    ``deletei2.php`` and deletes IMMEDIATELY (calibrated Task 6: no second
    confirmation step). On confirm, clicks "Vymazat" and verifies the delete took
    effect (success marker, else absence from moje-inzeraty). Never batched — the
    orchestrator confirms the target title interactively (``--yes`` never applies
    to delete).
    """
    url = f"https://{sekce}.bazos.cz/smazat/{ad_id}.php"
    with _session_page(context, storage_state, headed=not preview) as page:
        page.goto(url, wait_until="load")
        _assert_not_gate(page)  # unverified session → the manage page IS the gate
        title = _delete_page_title(page)

        if preview:
            os.makedirs(screenshot_dir or PREVIEW_DIR, exist_ok=True)
            shot = os.path.join(screenshot_dir or PREVIEW_DIR,
                                f"{_timestamp()}-smazat-{ad_id}.png")
            page.screenshot(path=shot, full_page=True)
            return {"screenshot": shot, "id": ad_id, "sekce": sekce, "title": title}

        # Password is pre-filled for own ads; only override if explicitly given.
        if heslobazar:
            pw_field = page.query_selector('input[name="heslobazar"]') \
                or page.query_selector('input[name="heslo"]')
            if pw_field:
                pw_field.fill(heslobazar)
        if not _click_administrace(page, "Vymazat"):
            raise RuntimeError("no 'Vymazat' action on the manage page — "
                               "cannot delete (unexpected page shape)")
        page.wait_for_load_state("load")
        deleted = _delete_confirmed(page, ad_id)
        return {"deleted": deleted, "id": ad_id, "sekce": sekce, "title": title}


def _delete_page_title(page):
    """Best-effort ad title on the delete confirm page (for the safety check)."""
    el = page.query_selector("h1, h2, .nadpisdetail, title")
    return el.inner_text().strip() if el else None


def _verify_absent(page, ad_id):
    page.goto("https://www.bazos.cz/moje-inzeraty.php", wait_until="load")
    import moje
    ads = moje.parse_moje_inzeraty(page.content())
    return not any(a["id"] == str(ad_id) for a in ads)


def upravit(ad_id, sekce, changes, *, preview=True, context=None,
            storage_state=None, heslobazar=None, screenshot_dir=None):
    """Edit an ad via the manage page, apply ``changes`` (subset of ad fields),
    preview or save.

    bazoš has no GET edit URL (``/upravit/<id>.php`` is 404). Editing is the
    "Upravit" action on ``/smazat/<id>.php``, which POSTs to ``deletei2.php`` and
    returns the same insert form (``formpridani``→``insert.php``) pre-filled and
    carrying a hidden ``idad`` — so saving UPDATES this ad rather than creating a
    duplicate. Field names match the insert form (form-contract.md).
    """
    manage_url = f"https://{sekce}.bazos.cz/smazat/{ad_id}.php"
    with _session_page(context, storage_state, headed=not preview) as page:
        page.goto(manage_url, wait_until="load")
        _assert_not_gate(page)
        if heslobazar:  # pre-filled for own ads; override only if given
            pw = page.query_selector('input[name="heslobazar"]')
            if pw:
                pw.fill(heslobazar)
        if not _click_administrace(page, "Upravit"):
            raise RuntimeError("no 'Upravit' action on the manage page — "
                               "cannot edit (unexpected page shape)")
        page.wait_for_load_state("load")
        _assert_not_gate(page)
        _assert_edit_form_targets_ad(page, ad_id)  # guard: update, not duplicate
        applied = _apply_changes(page, changes)

        if preview:
            os.makedirs(screenshot_dir or PREVIEW_DIR, exist_ok=True)
            shot = os.path.join(screenshot_dir or PREVIEW_DIR,
                                f"{_timestamp()}-upravit-{ad_id}.png")
            page.screenshot(path=shot, full_page=True)
            return {"screenshot": shot, "id": ad_id, "sekce": sekce,
                    "changed": applied}

        if not _honeypot_untouched_if_present(page):
            raise RuntimeError("honeypot/vkm changed during edit — aborting")
        page.click('input[type="submit"][value="Odeslat"]')
        page.wait_for_load_state("load")
        # The save posts to insert.php and lands on the shared "vložen/změněn"
        # confirmation — verify it rather than assuming the edit stuck.
        saved = _insert_ok_marker(page)
        res = {"updated": saved, "id": ad_id, "sekce": sekce, "url": page.url,
               "changed": applied}
        if not saved:
            res["warning"] = ("edit save not confirmed on-page — verify the live "
                              "ad (on-page error: %s)" % (_page_error_text(page) or "none"))
        return res


def _apply_changes(page, changes):
    """Stage ``changes`` (schema keys) onto the edit form; return applied fields."""
    applied = {}
    for schema_key, value in changes.items():
        value = ad_schema._value(value)
        if schema_key in SELECT_FIELDS:
            page.select_option(f'select[name="{schema_key}"]', str(value))
        else:
            form_key = FIELD_MAP.get(schema_key, schema_key)
            page.fill(f'[name="{form_key}"]', str(value))
        applied[schema_key] = str(value)
    return applied


# --- CLI: single-purpose steps the model chains per SKILL.md -----------------
# Every command prints JSON on stdout. The model gathers/validates/asks between
# steps; the CLI never fabricates fields.

def parse_set(pairs):
    """``["cena=111", "cenavyber=Dohodou"]`` → ``{"cena": 111, ...}`` (int-cast)."""
    out = {}
    for item in pairs or []:
        k, _, v = item.partition("=")
        out[k.strip()] = int(v) if v.strip().isdigit() else v.strip()
    return out


def _emit(obj):
    import json
    print(json.dumps(obj, ensure_ascii=False, indent=2))


def _build_parser():
    p = argparse.ArgumentParser(prog="bazos", description="bazos.cz ad driver")
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("preflight", help="check deps/chromium/session")
    sub.add_parser("sections", help="list live sekce (anon)")
    sub.add_parser("identity", help="print verified identity from the session")
    sub.add_parser("moje", help="list your own live ads")
    c = sub.add_parser("canary", help="conformance check of a sekce insert form")
    c.add_argument("--sekce", required=True)
    g = sub.add_parser("categories", help="list a sekce's live category options")
    g.add_argument("--sekce", required=True)

    f = sub.add_parser("fotky", help="EXIF/GPS strip + orientation fix + "
                                     "downscale + JPEG conversion, in place")
    f.add_argument("folder")
    f.add_argument("--max-edge", type=int, default=1200)

    o = sub.add_parser("prodano", help="record a sold outcome into inzerat.md")
    o.add_argument("folder")
    o.add_argument("--cena", required=True, type=int)
    o.add_argument("--datum", help="YYYY-MM-DD (default: today)")

    z = sub.add_parser("zkontrolovat", help="offline folder check (no session, "
                                            "no browser)")
    z.add_argument("folder")

    v = sub.add_parser("vlozit", help="insert an ad from a prodej/<x>/ folder")
    v.add_argument("folder")
    v.add_argument("--sekce", required=True)
    v.add_argument("--category", required=True, help="category option value")
    v.add_argument("--cenavyber")
    v.add_argument("--typ", help="Prodej / Pronájem (sekce reality)")
    v.add_argument("--submit", action="store_true", help="publish (default preview)")

    d = sub.add_parser("smazat", help="delete an ad by id")
    d.add_argument("id")
    d.add_argument("--sekce", required=True)
    d.add_argument("--heslo")
    d.add_argument("--confirm", action="store_true", help="delete (default preview)")

    u = sub.add_parser("upravit", help="edit an ad by id")
    u.add_argument("id")
    u.add_argument("--sekce", required=True)
    u.add_argument("--set", action="append", metavar="k=v", help="field to change")
    u.add_argument("--save", action="store_true", help="save (default preview)")
    return p


def main(argv=None):  # pragma: no cover - thin CLI, orchestrated by SKILL.md
    import parse_inzerat
    import conformance
    import moje as moje_mod
    import preflight as preflight_mod

    args = _build_parser().parse_args(argv)

    if args.cmd == "preflight":
        problems = preflight_mod.check()
        _emit({"ok": not problems, "problems": problems})
        return 0

    if args.cmd == "sections":
        _emit(category_mod.fetch_sections(auth.requests_session()))
        return 0

    if args.cmd == "identity":
        state = auth.get_storage_state()
        _emit(auth.get_identity_from_state(state))
        return 0

    if args.cmd == "moje":
        _emit(moje_mod.fetch_moje_inzeraty(auth.requests_session()))
        return 0

    if args.cmd == "canary":
        viol = conformance.check(f"https://{args.sekce}.bazos.cz",
                                 auth.requests_session())
        _emit({"conforms": not viol, "violations": viol})
        return 0

    if args.cmd == "categories":
        _emit(category_mod.fetch_category_options(auth.requests_session(), args.sekce))
        return 0

    if args.cmd == "fotky":
        import fotky as fotky_mod
        _emit(fotky_mod.process_folder(args.folder, max_edge=args.max_edge))
        return 0

    if args.cmd == "prodano":
        try:
            _emit(parse_inzerat.save_prodano(args.folder, args.cena, args.datum))
            return 0
        except ValueError as e:
            _emit({"ok": False, "error": str(e)})
            return 1

    if args.cmd == "zkontrolovat":
        _emit(zkontrolovat_report(args.folder))
        return 0

    if args.cmd == "vlozit":
        ad = parse_inzerat.parse_folder(args.folder)
        ad["sekce"] = args.sekce
        ad["category"] = args.category
        if args.cenavyber:
            ad["cenavyber"] = args.cenavyber
        if args.typ:
            ad["typ"] = args.typ
        ad.update(auth.get_identity_from_state(auth.get_storage_state()))
        problems = ad_schema.validate(ad)
        if problems:
            _emit({"ok": False, "problems": problems})
            return 1
        if args.submit:
            existing = moje_mod.fetch_moje_inzeraty(auth.requests_session())
            blockers = submit_blockers(ad, existing)
            if blockers:
                _emit({"ok": False, "refused": blockers})
                return 1
            # persist the ad-management password only when actually publishing
            parse_inzerat.ensure_heslobazar(ad, args.folder)
        try:
            res = vlozit(ad, preview=not args.submit)
        except ValueError as e:  # form needs a field the folder lacks (Typ)
            _emit({"ok": False, "problems": [str(e)]})
            return 1
        # Persist published_url ONLY on a confirmed publish (a real ad id + its
        # /inzerat/ url) — never on the error path, whose dict also carries a
        # "url" (the insert.php page the submit failed on).
        if args.submit and res.get("id"):
            parse_inzerat.save_published(args.folder, res["url"], res["id"])
        _emit(res)
        return 0

    if args.cmd == "smazat":
        _emit(smazat(args.id, args.sekce, preview=not args.confirm,
                     heslobazar=args.heslo))
        return 0

    if args.cmd == "upravit":
        _emit(upravit(args.id, args.sekce, parse_set(args.set),
                      preview=not args.save))
        return 0

    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
