from __future__ import annotations

from pathlib import Path

import app.main as app_main
from app.studio import INTERNAL_VALIDATION_REPORT_KEYS, StudioController
from core.exports.public_text import find_public_text_violations, public_safe_text


def test_frozen_app_uses_local_app_data(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(app_main.sys, "frozen", True, raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("GAS_EC_WORKSPACE_ROOT", raising=False)

    assert app_main._default_workspace_root() == tmp_path / "GasECStudio"


def test_workspace_root_override_wins(monkeypatch, tmp_path: Path) -> None:
    configured = tmp_path / "configured"
    env_root = tmp_path / "environment"
    monkeypatch.setenv("GAS_EC_WORKSPACE_ROOT", str(env_root))

    assert app_main._default_workspace_root(configured) == configured
    assert app_main._default_workspace_root() == env_root


def test_public_text_validation_matches_sanitizer() -> None:
    source = "EddyPro 行业参考 raw-to-final eddypro_compare"
    safe = public_safe_text(source)

    assert find_public_text_violations(source)
    assert find_public_text_violations(safe) == []


def test_rc_runtime_modules_are_available() -> None:
    probes = app_main._probe_runtime_modules()

    assert set(probes) == set(app_main.RC_RUNTIME_MODULES)
    assert all(probe["status"] == "pass" for probe in probes.values())


def test_release_controller_excludes_internal_validation_reports(tmp_path: Path) -> None:
    controller = StudioController(workspace_root=tmp_path, expose_internal_validation=False)
    try:
        reports = set(controller.report_center_workspace["reports"])
        assert reports.isdisjoint(INTERNAL_VALIDATION_REPORT_KEYS)

        for report_key in INTERNAL_VALIDATION_REPORT_KEYS:
            controller.set_report_nav_section(report_key)
            assert controller.report_center_workspace["selected_report"] == "method_provenance"

        public_report = controller.report_center_report()
        assert "eddypro_compare" not in public_report
        assert "eddypro_attribution" not in public_report
    finally:
        controller.shutdown()
