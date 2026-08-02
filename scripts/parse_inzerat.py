"""Parse a ``prodej/<x>/``-style folder into a partial ad dict.

Real metadata format (verified across all 8 prodej/ folders):

    # Inzerát: <title>

    - **Nadpis (Bazoš):** Albi Kouzelné čtení - Zpívánky 1, mluvicí kniha
    - **Cena:** 90 Kč
    - **Kategorie:** Knihy (dětské) / Děti
    - **Lokalita:** Brno-Žebětín, 641 00
    - **Fotky:** IMG_0551.JPG (přední strana), IMG_0552.JPG (vnitřní dvoustrana)

    ## Text inzerátu (k vložení)

    <body → popis>

Produces the schema fields this source can supply; ``jmeno/telefon/email`` come
from the session (auth.get_identity), ``sekce/category`` from the resolver.
Unknown metadata keys (e.g. ``ISBN:``) are ignored.
"""

import datetime
import os
import re
import secrets

import ad_schema

IMAGE_EXTS = ad_schema.JPEG_EXTS | ad_schema.CONVERTIBLE_EXTS

_KEY_RE = re.compile(r"^\s*-\s*\*\*(?P<key>[^:*]+?)\s*:\*\*\s*(?P<val>.*?)\s*$")
_IMG_RE = re.compile(r"[^\s,()\"']+\.(?:jpe?g|png|heic|heif|webp)", re.I)
_PSC_RE = re.compile(r"\d{3}\s?\d{2}")
_HEADING_RE = re.compile(r"^##\s", re.M)
_BODY_HEADING_RE = re.compile(r"^##\s*Text inzerátu", re.I | re.M)
_URL_RE = re.compile(r"https?://\S+")

INZERAT_MD = "inzerat.md"

# Field-name aliases allowed on the Odvozeno: line (human name → schema key).
_ODVOZENO_ALIASES = {"kategorie": "kategorie_hint"}


def _md_path(folder):
    return os.path.join(folder, INZERAT_MD)


def _read(folder):
    with open(_md_path(folder), encoding="utf-8") as f:
        return f.read()


def _parse_meta(raw):
    """Return list of (raw_key, value) metadata pairs, in document order."""
    pairs = []
    for line in raw.splitlines():
        m = _KEY_RE.match(line)
        if m:
            pairs.append((m.group("key").strip(), m.group("val").strip()))
    return pairs


def _find(pairs, prefix):
    """First value whose key starts with ``prefix`` (case-insensitive), or None."""
    p = prefix.lower()
    for key, val in pairs:
        if key.lower().startswith(p):
            return val
    return None


def _parse_cena(val):
    if not val:
        return None
    digits = re.sub(r"[^\d]", "", val)
    return int(digits) if digits else None


def _extract_body(raw):
    """Text under the '## Text inzerátu…' heading, up to the next '## ' or EOF."""
    m = _BODY_HEADING_RE.search(raw)
    if not m:
        return ""
    start = raw.index("\n", m.end()) + 1 if "\n" in raw[m.end():] else len(raw)
    nxt = _HEADING_RE.search(raw, start)
    body = raw[start:nxt.start()] if nxt else raw[start:]
    return body.strip()


def _list_images(folder):
    names = [n for n in os.listdir(folder)
             if os.path.splitext(n)[1].lower() in IMAGE_EXTS]
    return sorted(names, key=str.lower)


def _resolve_photos(folder, fotky_val):
    """Photo paths in listed order (cover first); fall back to sorted glob."""
    entries = os.listdir(folder)
    lower_map = {e.lower(): e for e in entries}
    resolved = []
    if fotky_val:
        for name in _IMG_RE.findall(fotky_val):
            direct = os.path.join(folder, name)
            if os.path.exists(direct):
                resolved.append(direct)
            elif name.lower() in lower_map:  # case-insensitive rescue (Linux)
                resolved.append(os.path.join(folder, lower_map[name.lower()]))
    if not resolved:
        resolved = [os.path.join(folder, n) for n in _list_images(folder)]
    return resolved


def parse_folder(path):
    """Parse ``<path>/inzerat.md`` → partial ad dict (schema field names)."""
    raw = _read(path)
    pairs = _parse_meta(raw)
    ad = {}

    nadpis = _find(pairs, "nadpis")
    if nadpis:
        ad["nadpis"] = nadpis

    cena = _parse_cena(_find(pairs, "cena"))
    if cena is not None:
        ad["cena"] = cena

    lok = _find(pairs, "lokalita")
    if lok:
        ad["lokalita_full"] = lok
        m = _PSC_RE.search(lok)
        ad["lokalita"] = m.group(0) if m else lok

    kat = _find(pairs, "kategorie")
    if kat:
        ad["kategorie_hint"] = kat

    heslo = _find(pairs, "heslobazar")
    if heslo:
        ad["heslobazar"] = heslo

    pub = _find(pairs, "publikováno") or _find(pairs, "publikovano")
    if pub:
        m = _URL_RE.search(pub)
        if m:
            ad["published_url"] = m.group(0)

    ad["popis"] = _extract_body(raw)
    ad["photos"] = _resolve_photos(path, _find(pairs, "fotky"))

    # An "- **Odvozeno:** cena, nadpis" line persists which fields the model
    # derived: wrap them so derived_fields()/submit_blockers see them in a
    # later session. Confirming a field = deleting its name from that line.
    odv = _find(pairs, "odvozeno")
    if odv:
        for name in (n.strip().lower() for n in re.split(r"[,;]", odv)):
            key = _ODVOZENO_ALIASES.get(name, name)
            if key in ad and not ad_schema.is_derived(ad[key]):
                ad[key] = {"value": ad[key], "_derived": True}

    return ad


def _append_meta_line(md_path, key, value):
    """Insert ``- **key:** value`` into the top metadata block (after the last
    existing ``- **…:**`` line), so meta stays grouped above the body."""
    with open(md_path, encoding="utf-8") as f:
        lines = f.readlines()
    last_meta = -1
    for i, line in enumerate(lines):
        if _KEY_RE.match(line):
            last_meta = i
        elif _HEADING_RE.match(line):  # reached the body heading
            break
    new_line = f"- **{key}:** {value}\n"
    if last_meta >= 0:
        lines.insert(last_meta + 1, new_line)
    else:
        lines.append("\n" + new_line)
    with open(md_path, "w", encoding="utf-8") as f:
        f.writelines(lines)


def _gen_password(n=10):
    alphabet = "abcdefghijkmnpqrstuvwxyz23456789"  # no ambiguous chars
    return "".join(secrets.choice(alphabet) for _ in range(n))


def ensure_heslobazar(ad, folder):
    """Return the ad-management password, generating + persisting it if absent."""
    if ad.get("heslobazar"):
        return ad["heslobazar"]
    pw = _gen_password()
    ad["heslobazar"] = pw
    _append_meta_line(_md_path(folder), "Heslobazar", pw)
    return pw


def save_published(folder, url, ad_id=None, date=None):
    """Record a successful publish so later runs dedupe/renew instead of re-posting."""
    date = date or datetime.date.today().isoformat()
    _append_meta_line(_md_path(folder), "Publikováno", f"{url} ({date})")


_META_DATE_RE = re.compile(r"\((\d{4}-\d{2}-\d{2})")


def _dny(n):
    """Czech plural for days: 1 den, 2–4 dny, 0/5+ dní."""
    if n == 1:
        return "den"
    if 2 <= n <= 4:
        return "dny"
    return "dní"


def published_date(folder):
    """The date from the Publikováno meta line, or None."""
    pairs = _parse_meta(_read(folder))
    val = _find(pairs, "publikováno") or _find(pairs, "publikovano")
    if not val:
        return None
    m = _META_DATE_RE.search(val)
    return datetime.date.fromisoformat(m.group(1)) if m else None


def save_prodano(folder, cena, datum=None):
    """Record a sold outcome: '- **Prodáno:** <cena> Kč (<datum>[, za N dní])'.

    days-to-sell is computed from the Publikováno line when present. Refuses a
    second record — an ad sells once; a re-run is a mistake, not an update.
    """
    if int(cena) <= 0:
        raise ValueError(f"cena musí být kladné číslo, ne {cena}")
    pairs = _parse_meta(_read(folder))
    if _find(pairs, "prodáno") or _find(pairs, "prodano"):
        raise ValueError("Prodáno už je v inzerat.md zaznamenáno")
    if isinstance(datum, str):
        datum = datetime.date.fromisoformat(datum)
    datum = datum or datetime.date.today()
    pub = published_date(folder)
    if pub and datum < pub:
        raise ValueError(f"datum prodeje {datum} předchází datu publikace {pub}")
    days = (datum - pub).days if pub else None
    val = f"{int(cena)} Kč ({datum.isoformat()}"
    if days is not None:
        val += f", za {days} {_dny(days)}"
    val += ")"
    _append_meta_line(_md_path(folder), "Prodáno", val)
    return {"cena": int(cena), "datum": datum.isoformat(), "days_to_sell": days}
