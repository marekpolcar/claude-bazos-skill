"""Template ↔ parser round-trip: the canonical example inside
references/inzerat-sablona.md must parse into a folder the offline check
accepts. Pins the doc to the parser — editing one without the other fails."""

import os
import re

from PIL import Image

import ad_schema
import bazos
import parse_inzerat

REF = os.path.join(os.path.dirname(__file__), "..", "references",
                   "inzerat-sablona.md")


def _canonical_example():
    with open(REF, encoding="utf-8") as f:
        raw = f.read()
    m = re.search(r"```markdown\n(.*?)```", raw, re.S)
    assert m, "no fenced canonical example in inzerat-sablona.md"
    return m.group(1)


def test_template_roundtrip(tmp_path):
    example = _canonical_example()
    (tmp_path / "inzerat.md").write_text(example, encoding="utf-8")
    photo_names = re.findall(r"[\w-]+\.jpe?g", example)
    assert photo_names, "canonical example must list photo files"
    for name in photo_names:
        Image.new("RGB", (10, 10)).save(str(tmp_path / name), "JPEG")

    ad = parse_inzerat.parse_folder(str(tmp_path))
    assert ad_schema._value(ad["cena"]) == 90
    assert ad_schema._value(ad["nadpis"]).startswith("Albi")
    assert ad_schema.derived_fields(ad) == ["cena"]   # the example's Odvozeno line
    assert [os.path.basename(p) for p in ad["photos"]] == photo_names

    rep = bazos.zkontrolovat_report(str(tmp_path))
    assert rep["valid"] is True
    assert rep["derived"] == ["cena"]
    assert rep["missing_photos"] is False


def test_roundtrip_after_confirming_derived(tmp_path):
    example = _canonical_example().replace("- **Odvozeno:** cena\n", "")
    (tmp_path / "inzerat.md").write_text(example, encoding="utf-8")
    Image.new("RGB", (10, 10)).save(str(tmp_path / "foto-1.jpg"), "JPEG")
    Image.new("RGB", (10, 10)).save(str(tmp_path / "foto-2.jpg"), "JPEG")
    rep = bazos.zkontrolovat_report(str(tmp_path))
    assert rep == {"valid": True, "problems": [], "derived": [],
                   "missing_photos": False}
