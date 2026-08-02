"""Ad schema + validation for bazos-inzerce.

The contract is a *schema*, not a file (DESIGN §5). An ad is a plain dict whose
keys are the field names below. Any field the model *derived* (rather than read
or was told) is represented as a wrapper dict ``{"value": X, "_derived": True}``
so the preview can flag it "odvozeno — potvrď". Everything here is pure (no I/O
except ``os.path.exists`` on photo paths) so it unit-tests without a network.

Never fabricate ``cena`` or condition — see references/ad-schema.md §resolution.
"""

import os

# Fields that must be present (non-empty) before an ad may be previewed/published.
# ``cena`` is conditionally waived (see is_price_optional); ``photos`` has its own
# count/format rules. Contact fields come from the session (auth.get_identity),
# never from an ad folder — but they are still required to be present.
REQUIRED = [
    "nadpis",
    "popis",
    "cena",
    "sekce",
    "category",
    "lokalita",
    "jmeno",
    "telefon",
    "email",
    "photos",
]

OPTIONAL = ["cenavyber", "heslobazar", "kategorie_hint"]

# Photo formats bazos accepts as-is (napoveda.php: .jpeg only).
JPEG_EXTS = {".jpg", ".jpeg"}
# Formats we convert to JPEG before upload (sips/Pillow) — never passed through.
CONVERTIBLE_EXTS = {".png", ".heic", ".heif", ".webp"}

MAX_PHOTOS = 20

# cenavyber values under which an explicit numeric cena is not required.
# Normalized (lowercased, stripped). "dohodou"/"v textu" per DESIGN §5; "zdarma"
# (free) and "nabídněte" (make an offer) legitimately carry no fixed price.
PRICE_OPTIONAL_CENAVYBER = {"dohodou", "v textu", "zdarma", "nabídněte"}


def _value(v):
    """Unwrap a derived-field wrapper ``{"value": X, "_derived": ...}`` → X.

    Plain (non-derived) values pass through untouched. Only dicts that carry a
    ``_derived`` key are treated as wrappers, so ordinary dict-valued data (none
    in this schema today) would not be misread.
    """
    if isinstance(v, dict) and "_derived" in v:
        return v.get("value")
    return v


def is_derived(v):
    return isinstance(v, dict) and bool(v.get("_derived"))


def derived_fields(ad):
    """Names of fields the model derived (flagged ``_derived=True``).

    Feeds the preview's "odvozeno — potvrď" markers and the ``--yes`` refusal.
    """
    return [k for k, v in ad.items() if is_derived(v)]


def _norm(s):
    return s.strip().lower() if isinstance(s, str) else s


def is_price_optional(cenavyber):
    """True when cenavyber makes an explicit numeric cena unnecessary."""
    return _norm(cenavyber) in PRICE_OPTIONAL_CENAVYBER


def _ext(path):
    return os.path.splitext(path)[1].lower()


def photos_needing_conversion(ad):
    """Photo paths whose format must be converted to JPEG before upload."""
    photos = _value(ad.get("photos")) or []
    return [p for p in photos if _ext(p) in CONVERTIBLE_EXTS]


def _is_blank(v):
    return v is None or (isinstance(v, str) and not v.strip())


def validate(ad):
    """Return human-readable problem messages; empty list == valid.

    Hard gate before preview/publish. A convertible-but-non-JPEG photo is *not*
    an error (the driver converts it — see photos_needing_conversion); only an
    unsupported/unconvertible format is.
    """
    msgs = []

    for f in REQUIRED:
        if f in ("cena", "photos"):
            continue  # handled with their own rules below
        if _is_blank(_value(ad.get(f))):
            msgs.append(f"chybí povinné pole '{f}'")

    # cena — required unless cenavyber waives it
    cena = _value(ad.get("cena"))
    if not is_price_optional(_value(ad.get("cenavyber"))):
        if _is_blank(cena):
            msgs.append("chybí 'cena' (a 'cenavyber' není dohodou/v textu)")
        else:
            try:
                if int(cena) <= 0:
                    msgs.append("'cena' musí být kladné číslo")
            except (ValueError, TypeError):
                msgs.append(f"'cena' musí být číslo, ne {cena!r}")

    # photos — 1..20, each exists, each JPEG or convertible
    photos = _value(ad.get("photos")) or []
    if len(photos) < 1:
        msgs.append("je potřeba alespoň 1 fotka")
    if len(photos) > MAX_PHOTOS:
        msgs.append(f"max {MAX_PHOTOS} fotek (zadáno {len(photos)})")
    for p in photos:
        if not os.path.exists(p):
            msgs.append(f"fotka neexistuje: {p}")
            continue
        ext = _ext(p)
        if ext not in JPEG_EXTS and ext not in CONVERTIBLE_EXTS:
            msgs.append(f"nepodporovaný formát fotky: {p}")

    return msgs
