"""Unit tests for parse_inzerat — pure parsing over folder fixtures.

Mutation helpers (ensure_heslobazar / save_published) are exercised against a
tmp copy so the committed fixtures stay pristine.
"""

import os
import shutil

import pytest

import parse_inzerat
import ad_schema

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
KNIHA = os.path.join(FIX, "kniha")
KNIHA_ISBN = os.path.join(FIX, "kniha-isbn")


def test_parse_kniha_core_fields():
    ad = parse_inzerat.parse_folder(KNIHA)
    assert ad["nadpis"].startswith("Albi Kouzelné čtení")
    assert ad["cena"] == 90
    assert "interaktivní mluvicí kniha" in ad["popis"]
    assert ad["kategorie_hint"]  # present, non-empty
    assert ad["lokalita"] == "110 00"
    assert "Praha" in ad["lokalita_full"]


def test_parse_kniha_photos_include_uppercase_ext():
    ad = parse_inzerat.parse_folder(KNIHA)
    bases = [os.path.basename(p) for p in ad["photos"]]
    assert bases == ["IMG_a.jpg", "IMG_b.JPG"]  # order = Fotky line, cover first
    assert all(os.path.exists(p) for p in ad["photos"])


def test_body_stops_before_next_heading():
    ad = parse_inzerat.parse_folder(KNIHA)
    # body must not swallow the metadata block or a following heading
    assert "Nadpis (Bazoš)" not in ad["popis"]
    assert ad["popis"].startswith("Albi Kouzelné čtení")


def test_isbn_fixture_parses_and_ignores_unknown_key():
    ad = parse_inzerat.parse_folder(KNIHA_ISBN)
    assert ad["cena"] == 130
    assert ad["nadpis"].startswith("Albi Kouzelné čtení")
    assert "isbn" not in ad  # unknown key dropped
    assert len(ad["photos"]) == 1


def test_heslobazar_roundtrip(tmp_path):
    dst = tmp_path / "kniha"
    shutil.copytree(KNIHA, dst)
    ad = parse_inzerat.parse_folder(str(dst))
    assert "heslobazar" not in ad
    pw = parse_inzerat.ensure_heslobazar(ad, str(dst))
    assert pw and ad["heslobazar"] == pw
    # persisted + parsed back on a fresh read
    ad2 = parse_inzerat.parse_folder(str(dst))
    assert ad2["heslobazar"] == pw
    # idempotent: a second call returns the same, no duplicate line
    ad3 = parse_inzerat.parse_folder(str(dst))
    assert parse_inzerat.ensure_heslobazar(ad3, str(dst)) == pw


def test_save_published_roundtrip(tmp_path):
    dst = tmp_path / "kniha"
    shutil.copytree(KNIHA, dst)
    url = "https://knihy.bazos.cz/inzerat/311222333/albi-zpivanky-1.php"
    parse_inzerat.save_published(str(dst), url, ad_id="311222333", date="2026-07-03")
    ad = parse_inzerat.parse_folder(str(dst))
    assert ad["published_url"] == url


def test_meta_line_stays_above_body(tmp_path):
    dst = tmp_path / "kniha"
    shutil.copytree(KNIHA, dst)
    parse_inzerat.ensure_heslobazar(parse_inzerat.parse_folder(str(dst)), str(dst))
    raw = (dst / "inzerat.md").read_text(encoding="utf-8")
    assert raw.index("Heslobazar") < raw.index("## Text inzerátu")


def _with_odvozeno(tmp_path, names_line):
    dst = tmp_path / "kniha"
    shutil.copytree(KNIHA, dst)
    md = dst / "inzerat.md"
    raw = md.read_text(encoding="utf-8")
    raw = raw.replace("- **Fotky:**",
                      f"- **Odvozeno:** {names_line}\n- **Fotky:**")
    md.write_text(raw, encoding="utf-8")
    return str(dst)


def test_odvozeno_line_wraps_named_fields(tmp_path):
    folder = _with_odvozeno(tmp_path, "cena, nadpis")
    ad = parse_inzerat.parse_folder(folder)
    assert sorted(ad_schema.derived_fields(ad)) == ["cena", "nadpis"]
    assert ad_schema._value(ad["cena"]) == 90          # value survives the wrap
    assert ad_schema._value(ad["nadpis"]).startswith("Albi")
    assert not ad_schema.is_derived(ad["popis"])        # unnamed fields untouched


def test_odvozeno_kategorie_alias_and_unknown_ignored(tmp_path):
    folder = _with_odvozeno(tmp_path, "kategorie, neexistujici_pole")
    ad = parse_inzerat.parse_folder(folder)
    assert ad_schema.derived_fields(ad) == ["kategorie_hint"]


def test_no_odvozeno_line_yields_no_derived():
    ad = parse_inzerat.parse_folder(KNIHA)
    assert ad_schema.derived_fields(ad) == []


def test_odvozeno_duplicate_alias_does_not_double_wrap(tmp_path):
    # "kategorie" and "kategorie_hint" both resolve to the same schema key —
    # the second name must not re-wrap the already-wrapped value.
    folder = _with_odvozeno(tmp_path, "kategorie, kategorie_hint")
    ad = parse_inzerat.parse_folder(folder)
    assert ad_schema.derived_fields(ad) == ["kategorie_hint"]
    assert ad_schema._value(ad["kategorie_hint"]) == "Knihy (dětské) / Děti"


def _kniha_copy(tmp_path):
    dst = tmp_path / "kniha"
    shutil.copytree(KNIHA, dst)
    return dst


def test_save_prodano_computes_days_to_sell(tmp_path):
    dst = _kniha_copy(tmp_path)
    parse_inzerat.save_published(str(dst),
                                 "https://knihy.bazos.cz/inzerat/1/x.php",
                                 date="2026-07-03")
    rec = parse_inzerat.save_prodano(str(dst), 250, "2026-07-10")
    assert rec == {"cena": 250, "datum": "2026-07-10", "days_to_sell": 7}
    raw = (dst / "inzerat.md").read_text(encoding="utf-8")
    assert "- **Prodáno:** 250 Kč (2026-07-10, za 7 dní)" in raw
    assert raw.index("Prodáno") < raw.index("## Text inzerátu")  # stays in meta


def test_save_prodano_czech_singular_day(tmp_path):
    dst = _kniha_copy(tmp_path)
    parse_inzerat.save_published(str(dst), "https://x.bazos.cz/inzerat/1/x.php",
                                 date="2026-07-03")
    parse_inzerat.save_prodano(str(dst), 90, "2026-07-04")
    raw = (dst / "inzerat.md").read_text(encoding="utf-8")
    assert "za 1 den)" in raw


def test_save_prodano_without_published_line(tmp_path):
    dst = _kniha_copy(tmp_path)
    rec = parse_inzerat.save_prodano(str(dst), 90, "2026-07-10")
    assert rec["days_to_sell"] is None
    raw = (dst / "inzerat.md").read_text(encoding="utf-8")
    assert "- **Prodáno:** 90 Kč (2026-07-10)" in raw


def test_save_prodano_refuses_zero_or_negative_cena(tmp_path):
    dst = _kniha_copy(tmp_path)
    raw_before = (dst / "inzerat.md").read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        parse_inzerat.save_prodano(str(dst), 0, "2026-07-10")
    with pytest.raises(ValueError):
        parse_inzerat.save_prodano(str(dst), -5, "2026-07-10")
    raw_after = (dst / "inzerat.md").read_text(encoding="utf-8")
    assert raw_after == raw_before  # neither call wrote anything
    assert "Prodáno" not in raw_after


def test_save_prodano_refuses_second_record(tmp_path):
    dst = _kniha_copy(tmp_path)
    parse_inzerat.save_prodano(str(dst), 90, "2026-07-10")
    with pytest.raises(ValueError):
        parse_inzerat.save_prodano(str(dst), 80, "2026-07-11")


def test_save_prodano_refuses_date_before_published(tmp_path):
    dst = _kniha_copy(tmp_path)
    parse_inzerat.save_published(str(dst), "https://x.bazos.cz/inzerat/1/x.php",
                                 date="2026-07-10")
    with pytest.raises(ValueError):
        parse_inzerat.save_prodano(str(dst), 90, "2026-07-03")
    raw = (dst / "inzerat.md").read_text(encoding="utf-8")
    assert "Prodáno" not in raw


def test_parse_folder_unaffected_by_prodano_line(tmp_path):
    dst = _kniha_copy(tmp_path)
    parse_inzerat.save_prodano(str(dst), 250, "2026-07-10")
    ad = parse_inzerat.parse_folder(str(dst))
    assert ad["cena"] == 90  # Cena line wins; Prodáno is not parsed as a field


def test_parse_typ_line(tmp_path):
    (tmp_path / "inzerat.md").write_text(
        "# Inzerát: byt\n\n"
        "- **Nadpis (Bazoš):** 2+kk\n"
        "- **Typ:** Pronájem\n"
        "- **Cena:** 23000 Kč\n\n"
        "## Text inzerátu (k vložení)\n\ntext\n", encoding="utf-8")
    ad = parse_inzerat.parse_folder(str(tmp_path))
    assert ad["typ"] == "Pronájem"
    assert ad["cena"] == 23000


def test_parse_without_typ_has_no_key():
    assert "typ" not in parse_inzerat.parse_folder(KNIHA)
