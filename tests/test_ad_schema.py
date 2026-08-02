"""Unit tests for ad_schema — pure, no network."""

import ad_schema


def _jpg(tmp_path, name="a.jpg"):
    p = tmp_path / name
    p.write_bytes(b"\xff\xd8\xff\xe0stub-jpeg")
    return str(p)


def _valid_ad(tmp_path, **over):
    ad = {
        "nadpis": "Albi Kouzelné čtení – Zpívánky 1",
        "popis": "interaktivní mluvicí kniha, jako nová",
        "cena": 90,
        "sekce": "knihy",
        "category": "34",
        "lokalita": "641 00",
        "jmeno": "Jan Novák",
        "telefon": "777123456",
        "email": "jan.novak@example.com",
        "photos": [_jpg(tmp_path)],
    }
    ad.update(over)
    return ad


def test_valid_ad_is_empty(tmp_path):
    assert ad_schema.validate(_valid_ad(tmp_path)) == []


def test_missing_cena_names_cena(tmp_path):
    ad = _valid_ad(tmp_path)
    del ad["cena"]
    msgs = ad_schema.validate(ad)
    assert any("cena" in m for m in msgs)


def test_cena_absent_ok_when_dohodou(tmp_path):
    ad = _valid_ad(tmp_path, cenavyber="Dohodou")
    del ad["cena"]
    assert ad_schema.validate(ad) == []


def test_cena_absent_ok_when_v_textu(tmp_path):
    ad = _valid_ad(tmp_path, cenavyber="V textu")
    del ad["cena"]
    assert ad_schema.validate(ad) == []


def test_cena_absent_ok_when_nabidnete(tmp_path):
    ad = _valid_ad(tmp_path, cenavyber="Nabídněte")
    del ad["cena"]
    assert ad_schema.validate(ad) == []


def test_non_numeric_cena_rejected(tmp_path):
    ad = _valid_ad(tmp_path, cena="devadesát")
    assert any("cena" in m for m in ad_schema.validate(ad))


def test_empty_photos_wants_one(tmp_path):
    ad = _valid_ad(tmp_path, photos=[])
    msgs = ad_schema.validate(ad)
    assert any("fotka" in m for m in msgs)


def test_too_many_photos(tmp_path):
    photos = [_jpg(tmp_path, f"p{i}.jpg") for i in range(21)]
    ad = _valid_ad(tmp_path, photos=photos)
    assert any("20" in m for m in ad_schema.validate(ad))


def test_unsupported_photo_format_rejected(tmp_path):
    bad = tmp_path / "doc.txt"
    bad.write_text("not an image")
    ad = _valid_ad(tmp_path, photos=[str(bad)])
    assert any("formát" in m for m in ad_schema.validate(ad))


def test_missing_photo_file_rejected(tmp_path):
    ad = _valid_ad(tmp_path, photos=[str(tmp_path / "nope.jpg")])
    assert any("neexistuje" in m for m in ad_schema.validate(ad))


def test_convertible_png_is_not_an_error(tmp_path):
    png = tmp_path / "cover.png"
    png.write_bytes(b"\x89PNG\r\n\x1a\nstub")
    ad = _valid_ad(tmp_path, photos=[str(png)])
    assert ad_schema.validate(ad) == []
    assert ad_schema.photos_needing_conversion(ad) == [str(png)]


def test_derived_fields_listed(tmp_path):
    ad = _valid_ad(tmp_path, popis={"value": "odhad ze snímků", "_derived": True})
    assert "popis" in ad_schema.derived_fields(ad)
    # derived value still validates (unwrapped)
    assert ad_schema.validate(ad) == []


def test_missing_contact_field_flagged(tmp_path):
    ad = _valid_ad(tmp_path, telefon="")
    assert any("telefon" in m for m in ad_schema.validate(ad))
