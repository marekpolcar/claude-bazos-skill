"""Unit tests for moje-inzeraty listing — parser over the authed fixture."""

import os

import moje

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def _ads():
    return moje.parse_moje_inzeraty(_read("moje_inzeraty_authed.html"))


def test_parses_ids_titles_sekce():
    ads = _ads()
    assert len(ads) == 3
    by_id = {a["id"]: a for a in ads}
    assert set(by_id) == {"311222333", "311999888", "408123777"}
    assert by_id["311222333"]["sekce"] == "knihy"
    assert by_id["408123777"]["sekce"] == "deti"
    assert by_id["311222333"]["title"].startswith("Albi Kouzelné čtení")
    assert by_id["311222333"]["url"] == \
        "https://knihy.bazos.cz/inzerat/311222333/albi-kouzelne-cteni-zpivanky-1.php"


def test_find_by_title_fuzzy():
    ads = _ads()
    m = moje.find_by_title(ads, "Zpívánky 1")
    assert m is not None and m["id"] == "311222333"
    # case + diacritics insensitive
    assert moje.find_by_title(ads, "zpivanky 3")["id"] == "311999888"
    # full title matches
    assert moje.find_by_title(ads, "Dřevěná hračka – vlak")["id"] == "408123777"


def test_find_by_title_no_match():
    assert moje.find_by_title(_ads(), "Neexistující kniha") is None


def test_find_by_title_prefers_specific():
    ads = [
        {"id": "1", "title": "Kniha", "sekce": "knihy", "url": "u1"},
        {"id": "2", "title": "Kniha o vlacích velká", "sekce": "knihy", "url": "u2"},
    ]
    # query contained in both; the more specific (longer) title wins
    assert moje.find_by_title(ads, "Kniha")["id"] == "1"  # exact norm equality wins
    assert moje.find_by_title(ads, "vlacích")["id"] == "2"
