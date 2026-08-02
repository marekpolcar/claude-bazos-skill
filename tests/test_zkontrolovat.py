"""Offline tests for bazos.zkontrolovat_report + the zkontrolovat CLI."""

import json
import os
import shutil

import ad_schema
import bazos

FIX = os.path.join(os.path.dirname(__file__), "fixtures")
KNIHA = os.path.join(FIX, "kniha")
BEZ_FOTEK = os.path.join(FIX, "kniha-bez-fotek")


def test_valid_folder_reports_valid():
    rep = bazos.zkontrolovat_report(KNIHA)
    assert rep == {"valid": True, "problems": [], "derived": [],
                   "missing_photos": False}


def test_missing_photo_msg_pinned_to_ad_schema():
    # zkontrolovat filters this exact message — fail loudly if ad_schema rewords it
    assert bazos._MISSING_PHOTO_MSG in ad_schema.validate({"photos": []})


def test_photoless_draft_reports_missing_photos_not_problems():
    rep = bazos.zkontrolovat_report(BEZ_FOTEK)
    assert rep["missing_photos"] is True
    assert rep["problems"] == []          # nothing confusing to "fix" in the text
    assert rep["valid"] is False          # but not publishable yet
    assert rep["derived"] == ["cena"]     # the fixture's Odvozeno line


def test_invalid_folder_reports_problems(tmp_path):
    dst = tmp_path / "kniha"
    shutil.copytree(KNIHA, dst)
    md = dst / "inzerat.md"
    raw = md.read_text(encoding="utf-8")
    md.write_text(raw.replace("- **Cena:** 90 Kč\n", ""), encoding="utf-8")
    rep = bazos.zkontrolovat_report(str(dst))
    assert rep["valid"] is False
    assert any("cena" in p for p in rep["problems"])


def test_session_and_resolver_fields_never_reported():
    rep = bazos.zkontrolovat_report(KNIHA)
    for f in bazos.SESSION_OR_RESOLVER_FIELDS:
        assert not any(f"'{f}'" in p for p in rep["problems"])


def test_cli_zkontrolovat_emits_json(capsys):
    assert bazos.main(["zkontrolovat", KNIHA]) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True


def test_nonexistent_folder_reports_instead_of_crashing():
    rep = bazos.zkontrolovat_report("/no/such/folder/xyz")
    assert rep["valid"] is False
    assert len(rep["problems"]) > 0
    assert rep["missing_photos"] is False


def test_cli_zkontrolovat_nonexistent_folder_exits_zero(capsys):
    assert bazos.main(["zkontrolovat", "/no/such/folder/xyz"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["valid"] is False
