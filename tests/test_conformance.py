"""Unit tests for the conformance canary — pure check_html over fixtures."""

import os

import conformance

FIX = os.path.join(os.path.dirname(__file__), "fixtures")


def _read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def test_fixtures_conform():
    pages = {
        "insert_form": _read("insert_form.html"),
        "delete_page": _read("smazat_probe.html"),
    }
    assert conformance.check_html(pages) == []


def test_renamed_field_is_flagged():
    form = _read("insert_form.html").replace('name="nadpis"', 'name="nadpisX"')
    violations = conformance.check_html({"insert_form": form})
    assert any("nadpis" in v for v in violations)


def test_rotated_honeypot_value_is_flagged():
    form = _read("insert_form.html").replace('value="afdggfd"', 'value="rotated99"')
    violations = conformance.check_html({"insert_form": form})
    assert any("honeypot" in v.lower() for v in violations)


def test_changed_vkm_is_flagged():
    form = _read("insert_form.html").replace('name="vkm" value="m"',
                                              'name="vkm" value="x"')
    violations = conformance.check_html({"insert_form": form})
    assert any("vkm" in v for v in violations)


def test_missing_category_select_is_flagged():
    form = _read("insert_form.html").replace('name="category"', 'name="rubrika"')
    violations = conformance.check_html({"insert_form": form})
    assert any("category" in v for v in violations)


def test_gate_is_detected():
    violations = conformance.check_html({"insert_form": _read("sms_gate.html")})
    assert any("gate" in v.lower() for v in violations)


def test_missing_insert_form():
    assert conformance.check_html({}) == ["no insert_form page supplied"]
