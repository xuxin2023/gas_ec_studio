from __future__ import annotations

import subprocess
from collections import Counter
from pathlib import Path

from core.comparison import eddypro_source_inventory as source_inventory_module
from core.comparison.eddypro_source_inventory import (
    ENGINE_URL,
    EXPECTED_FEATURES,
    GUI_URL,
    build_eddypro_source_inventory,
)


def test_eddypro_source_inventory_passes_with_feature_complete_source_tree(tmp_path: Path) -> None:
    engine_root = tmp_path / "engine"
    gui_root = tmp_path / "gui"
    _materialize_reference_repo(engine_root, "engine", f"{ENGINE_URL}.git")
    _materialize_reference_repo(gui_root, "gui", f"{GUI_URL}.git")

    inventory = build_eddypro_source_inventory(engine_root=engine_root, gui_root=gui_root)

    assert inventory["artifact_type"] == "eddypro_official_source_inventory"
    assert inventory["status"] == "pass"
    assert inventory["feature_count"] == len(EXPECTED_FEATURES)
    assert inventory["present_feature_count"] == len(EXPECTED_FEATURES)
    assert inventory["missing_features"] == []
    assert len(inventory["source_repositories"]["engine"]["commit"]) == 40
    assert inventory["source_repositories"]["engine"]["remote_url_matches_official"] is True
    assert inventory["source_repositories"]["gui"]["remote_url_matches_official"] is True


def test_eddypro_source_inventory_warns_when_official_modules_are_missing(tmp_path: Path) -> None:
    engine_root = tmp_path / "engine-missing"
    gui_root = tmp_path / "gui-missing"
    _init_repo(engine_root, f"{ENGINE_URL}.git")
    _init_repo(gui_root, f"{GUI_URL}.git")

    inventory = build_eddypro_source_inventory(engine_root=engine_root, gui_root=gui_root)

    assert inventory["status"] == "warning"
    assert inventory["missing_feature_count"] == len(EXPECTED_FEATURES)
    assert "spectral_massman_horst_ibrom_fratini" in inventory["missing_features"]
    assert "Presence of a source module is not numerical parity" in inventory["known_limitations"][0]


def test_eddypro_source_inventory_cache_reuses_until_source_signature_changes(monkeypatch, tmp_path: Path) -> None:
    calls: Counter[str] = Counter()
    engine_root = tmp_path / "engine-cache"
    gui_root = tmp_path / "gui-cache"
    _materialize_reference_repo(engine_root, "engine", f"{ENGINE_URL}.git")
    _materialize_reference_repo(gui_root, "gui", f"{GUI_URL}.git")

    original_git_value = source_inventory_module._git_value

    def counted_git_value(*args, **kwargs) -> str:
        calls["git"] += 1
        return original_git_value(*args, **kwargs)

    monkeypatch.setattr(source_inventory_module, "_git_value", counted_git_value)

    first = source_inventory_module.build_eddypro_source_inventory(
        engine_root=engine_root,
        gui_root=gui_root,
        use_cache=False,
    )
    first["missing_features"].append("mutated")
    first_git_calls = calls["git"]
    second = source_inventory_module.build_eddypro_source_inventory(engine_root=engine_root, gui_root=gui_root)

    assert first_git_calls > 0
    assert calls["git"] == first_git_calls
    assert "mutated" not in second["missing_features"]

    changed_path = engine_root / str(EXPECTED_FEATURES[0]["paths"][0])
    changed_path.write_text(changed_path.read_text(encoding="utf-8") + "\n! changed\n", encoding="utf-8")
    source_inventory_module.build_eddypro_source_inventory(engine_root=engine_root, gui_root=gui_root)

    assert calls["git"] > first_git_calls


def _materialize_reference_repo(root: Path, repository: str, remote_url: str) -> None:
    for feature in EXPECTED_FEATURES:
        if feature["repository"] != repository:
            continue
        paths = [str(item) for item in feature["paths"]]
        tokens = [str(item) for item in feature["tokens"]]
        for index, relative_path in enumerate(paths):
            path = root / relative_path
            path.parent.mkdir(parents=True, exist_ok=True)
            body = f"! {relative_path}\n"
            if index == 0:
                body += "\n".join(tokens) + "\n"
            path.write_text(body, encoding="utf-8")
    _init_repo(root, remote_url)


def _init_repo(root: Path, remote_url: str) -> None:
    root.mkdir(parents=True, exist_ok=True)
    if not any(root.iterdir()):
        (root / "README.md").write_text("fixture repo\n", encoding="utf-8")
    _run_git(root, "init")
    _run_git(root, "remote", "add", "origin", remote_url)
    _run_git(root, "add", ".")
    _run_git(root, "-c", "user.email=tests@example.invalid", "-c", "user.name=tests", "commit", "-m", "fixture")


def _run_git(root: Path, *args: str) -> None:
    completed = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    assert completed.returncode == 0, completed.stderr
