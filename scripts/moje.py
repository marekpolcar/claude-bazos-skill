"""moje-inzeraty listing (read operation).

Turns the user's own live ads into ``{id, title, sekce, url}`` records so
``smazat``/``upravit`` can target by title, and the pre-insert dedupe check can
run (bazos auto-deletes the OLDER of two identical ads — a re-run without dedupe
silently kills the live ad). Also the renewal anchor after the 2-month expiry.
"""

import re
import unicodedata

import category

# One title anchor per ad: /inzerat/<id>/<slug>.php, absolute or relative.
# Capture the FULL path (incl. slug) — the bare /inzerat/<id>/ form 404s.
_AD_RE = re.compile(
    r'<a\s+href="(?:https?://([a-z0-9]+)\.bazos\.cz)?(/inzerat/(\d+)/[^"]*)"[^>]*>(.*?)</a>',
    re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def parse_moje_inzeraty(html):
    """Parse the moje-inzeraty page → ``[{id, title, sekce, url}]`` (deduped by id)."""
    seen = set()
    out = []
    for sub, path, ad_id, label in _AD_RE.findall(html):
        title = _TAG_RE.sub("", label).strip()
        if not title or ad_id in seen:
            continue  # image-only anchors / duplicate id
        seen.add(ad_id)
        sekce = sub.lower() if sub else None
        url = f"https://{sekce}.bazos.cz{path}" if sekce else path
        out.append({"id": ad_id, "title": title, "sekce": sekce, "url": url})
    return out


def fetch_moje_inzeraty(session):
    r = session.get("https://www.bazos.cz/moje-inzeraty.php", timeout=25,
                    allow_redirects=True)
    return parse_moje_inzeraty(category._text(r))


def _norm(s):
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return re.sub(r"\s+", " ", s).strip().lower()


def find_by_title(ads, title):
    """Fuzzy-tolerant title match → the ad record or None.

    Case/diacritics-insensitive substring match either direction. Prefer an
    exact normalized equality; otherwise the longest-title substring match, so a
    query that is contained in several ads resolves to the most specific one.
    """
    q = _norm(title)
    if not q:
        return None
    exact = [a for a in ads if _norm(a["title"]) == q]
    if exact:
        return exact[0]
    matches = [a for a in ads if q in _norm(a["title"]) or _norm(a["title"]) in q]
    if not matches:
        return None
    return max(matches, key=lambda a: len(a["title"]))
