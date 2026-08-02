"""Offline tests for preflight — the venv has the deps, so imports are satisfied;
missing-session reporting is checkable without network."""

import preflight


def test_no_missing_imports_in_venv():
    # deps are installed in the venv the suite runs under
    assert preflight.missing_imports() == []


def test_pil_is_a_required_module():
    # fotky.py needs Pillow; a missing install must be caught here as an
    # environment problem, not surface later as fotky treating
    # ModuleNotFoundError as a per-photo defect (mass .vyrazeno renames).
    assert "PIL" in preflight.REQUIRED_MODULES


def test_check_reports_missing_session(tmp_path, monkeypatch):
    monkeypatch.setattr(preflight.auth, "STATE_FILE", str(tmp_path / "state.json"))
    monkeypatch.setattr(preflight, "chromium_ok", lambda: True)
    problems = preflight.check()
    assert any("no cached bazos session" in p for p in problems)


def test_check_clean_when_state_present(tmp_path, monkeypatch):
    state = tmp_path / "state.json"
    state.write_text("{}")
    monkeypatch.setattr(preflight.auth, "STATE_FILE", str(state))
    monkeypatch.setattr(preflight, "chromium_ok", lambda: True)
    assert preflight.check() == []
