"""Offline tests for the driver's pure helpers (photo prep, field mapping).
The live Playwright flow is in test_bazos_live.py (marked live)."""

import base64
import os

import pytest

import bazos

# A valid 1x1 PNG (so sips/Pillow can actually convert it).
_PNG_1x1 = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+M9QDwADhgGAWjR9"
    "awAAAABJRU5ErkJggg==")


def test_form_field_values_mapping():
    ad = {
        "nadpis": "Kniha", "popis": "text", "cena": 90, "lokalita": "110 00",
        "jmeno": "Jan Novák", "telefon": "777123456",
        "email": "jan.novak@example.com", "heslobazar": "abc123",
        "sekce": "knihy", "category": "34",
        "photos": ["/x.jpg"], "cenavyber": "Dohodou",
    }
    vals = bazos.form_field_values(ad)
    assert vals["telefoni"] == "777123456"   # telefon → telefoni
    assert vals["maili"] == "jan.novak@example.com"  # email → maili
    assert vals["cena"] == "90"              # int → str
    assert vals["jmeno"] == "Jan Novák"
    # not form text fields:
    for k in ("photos", "sekce", "category", "cenavyber", "telefon", "email"):
        assert k not in vals


def test_form_field_values_unwraps_derived():
    ad = {"popis": {"value": "odhad", "_derived": True}, "nadpis": "N"}
    assert bazos.form_field_values(ad)["popis"] == "odhad"


def test_prepare_photos_passthrough_jpeg(tmp_path):
    jpg = tmp_path / "a.jpg"
    jpg.write_bytes(b"\xff\xd8\xff\xe0stub")
    out = bazos.prepare_photos([str(jpg)], str(tmp_path / "work"))
    assert out == [str(jpg)]  # unchanged, not copied


def test_prepare_photos_converts_png(tmp_path):
    png = tmp_path / "cover.png"
    png.write_bytes(_PNG_1x1)
    out = bazos.prepare_photos([str(png)], str(tmp_path / "work"))
    assert len(out) == 1
    assert out[0].endswith(".jpg")
    assert os.path.exists(out[0])
    with open(out[0], "rb") as f:
        assert f.read(2) == b"\xff\xd8"  # real JPEG magic


def test_prepare_photos_caps_at_20(tmp_path):
    photos = []
    for i in range(25):
        p = tmp_path / f"p{i}.jpg"
        p.write_bytes(b"\xff\xd8\xff\xe0stub")
        photos.append(str(p))
    out = bazos.prepare_photos(photos, str(tmp_path / "work"))
    assert len(out) == 20


def test_prepare_photos_unsupported_raises(tmp_path):
    bad = tmp_path / "doc.txt"
    bad.write_text("nope")
    with pytest.raises(ValueError):
        bazos.prepare_photos([str(bad)], str(tmp_path / "work"))


# --- CLI (offline) ---

def test_parse_set_casts_ints():
    assert bazos.parse_set(["cena=111", "cenavyber=Dohodou"]) == \
        {"cena": 111, "cenavyber": "Dohodou"}
    assert bazos.parse_set(None) == {}


def test_cli_parser_accepts_each_command():
    p = bazos._build_parser()
    assert p.parse_args(["vlozit", "f", "--sekce", "knihy", "--category", "34"]).cmd \
        == "vlozit"
    assert p.parse_args(["smazat", "1", "--sekce", "knihy"]).cmd == "smazat"
    assert p.parse_args(["upravit", "1", "--sekce", "knihy", "--set", "cena=1"]).set \
        == ["cena=1"]
    assert p.parse_args(["fotky", "f"]).max_edge == 1200
    assert p.parse_args(["prodano", "f", "--cena", "250"]).cena == 250
    assert p.parse_args(["zkontrolovat", "f"]).cmd == "zkontrolovat"


def test_cli_preflight_prints_json(capsys, monkeypatch):
    import preflight
    monkeypatch.setattr(preflight, "check", lambda: [])
    assert bazos.main(["preflight"]) == 0
    assert '"ok": true' in capsys.readouterr().out


# --- submit safety gate ---

def test_submit_blockers_flags_already_published():
    ad = {"nadpis": "X", "published_url": "https://knihy.bazos.cz/inzerat/1/x.php"}
    assert any("published" in r for r in bazos.submit_blockers(ad, []))


def test_submit_blockers_flags_unconfirmed_derived():
    ad = {"nadpis": "X", "popis": {"value": "odhad", "_derived": True}}
    assert any("derived" in r for r in bazos.submit_blockers(ad, []))


def test_submit_blockers_flags_duplicate_live_ad():
    ad = {"nadpis": "Albi Kouzelné čtení – Zpívánky 1"}
    existing = [{"id": "9", "title": "Albi Kouzelné čtení – Zpívánky 1",
                 "sekce": "knihy", "url": "u"}]
    assert any("duplicate" in r for r in bazos.submit_blockers(ad, existing))


def test_submit_blockers_clean_ad_passes():
    assert bazos.submit_blockers({"nadpis": "Zcela unikátní titul"}, []) == []


class _StubPage:
    """Records fill/select calls; ``has_type`` toggles the Reality <select name=type>."""

    def __init__(self, has_type):
        self.has_type = has_type
        self.calls = []

    def query_selector(self, sel):
        return object() if (self.has_type and sel == 'select[name="type"]') else None

    def fill(self, sel, val):
        self.calls.append(("fill", sel, val))

    def select_option(self, sel, value=None, label=None):
        self.calls.append(("select", sel, value, label))


def test_fill_insert_form_refuses_missing_typ_when_form_has_it():
    page = _StubPage(has_type=True)
    with pytest.raises(ValueError, match="Typ"):
        bazos._fill_insert_form(page, {"nadpis": "x"}, "65")
    assert page.calls == []  # refused before touching the form


def test_fill_insert_form_selects_typ_first_by_label():
    page = _StubPage(has_type=True)
    bazos._fill_insert_form(page, {"nadpis": "x"}, "65", typ_label="Pronájem")
    assert page.calls[0] == ("select", 'select[name="type"]', None, "Pronájem")
    assert ("select", 'select[name="category"]', "65", None) in page.calls


def test_fill_insert_form_ignores_typ_when_form_lacks_it():
    page = _StubPage(has_type=False)
    bazos._fill_insert_form(page, {"nadpis": "x"}, "12")
    assert not any(c[1] == 'select[name="type"]' for c in page.calls)
