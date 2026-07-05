from __future__ import annotations

import hashlib
import os
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any


ENGINE_URL = "https://github.com/LI-COR-Environmental/eddypro-engine"
GUI_URL = "https://github.com/LI-COR-Environmental/eddypro-gui"
_SOURCE_INVENTORY_CACHE_MAX_ENTRIES = 8
_SOURCE_INVENTORY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}


EXPECTED_FEATURES: tuple[dict[str, Any], ...] = (
    {
        "feature_id": "raw_import_licor_ghg",
        "repository": "engine",
        "family": "raw_ingestion",
        "paths": ["src/src_rp/read_licor_ghg_archive.f90", "src/src_rp/import_current_period.f90"],
        "tokens": ["licor_ghg"],
    },
    {
        "feature_id": "raw_import_tob1_fp2",
        "repository": "engine",
        "family": "raw_ingestion",
        "paths": ["src/src_common/import_tob1.f90", "src/src_common/m_fp2_to_float.f90"],
        "tokens": ["IEEE4", "FP2"],
    },
    {
        "feature_id": "raw_import_slt_binary_ascii",
        "repository": "engine",
        "family": "raw_ingestion",
        "paths": [
            "src/src_common/import_ascii.f90",
            "src/src_common/import_binary.f90",
            "src/src_common/import_slt_edisol.f90",
            "src/src_common/import_slt_eddysoft.f90",
        ],
        "tokens": ["generic ASCII", "generic binary", "ImportSLTEdiSol", "ImportSLTEddySoft"],
    },
    {
        "feature_id": "axis_rotation_planar_fit",
        "repository": "engine",
        "family": "preprocessing",
        "paths": [
            "src/src_rp/tilt_correction.f90",
            "src/src_common/planarfit_rotation_matrix.f90",
            "src/src_rp/read_planar_fit_file.f90",
        ],
        "tokens": ["double_rotation", "triple_rotation", "planar_fit"],
    },
    {
        "feature_id": "angle_of_attack_and_crosswind",
        "repository": "engine",
        "family": "preprocessing",
        "paths": [
            "src/src_rp/aoa_calibration.f90",
            "src/src_rp/aoa_cal_nakai_2012.f90",
            "src/src_common/cross_wind_corr.f90",
        ],
        "tokens": ["angle-of-attack", "cross-wind"],
    },
    {
        "feature_id": "spectral_massman_horst_ibrom_fratini",
        "repository": "engine",
        "family": "spectral_correction",
        "paths": [
            "src/src_common/bpcf_massman_00.f90",
            "src/src_common/bpcf_Horst_97.f90",
            "src/src_common/bpcf_Ibrom_07.f90",
            "src/src_common/bpcf_fratini_12.f90",
            "src/src_common/bpcf_read_full_cos_wt.f90",
        ],
        "tokens": ["massman_00", "horst_97", "ibrom_07", "fratini_12"],
    },
    {
        "feature_id": "footprint_engine_output",
        "repository": "engine",
        "family": "footprint",
        "paths": ["src/src_common/footprint_handle.f90", "src/src_rp/write_out_full.f90"],
        "tokens": ["footprint", "Foot%peak", "Foot%x90"],
    },
    {
        "feature_id": "gui_processing_controls",
        "repository": "gui",
        "family": "gui",
        "paths": ["src/advprocessingoptions.cpp", "src/advprocessingoptions.h"],
        "tokens": ["Double rotation", "Footprint estimation", "Compensate density fluctuations"],
    },
    {
        "feature_id": "gui_spectral_controls",
        "repository": "gui",
        "family": "gui",
        "paths": ["src/advspectraloptions.cpp", "src/advspectraloptions.h"],
        "tokens": ["Binned (co)spectra", "spectral attenuations"],
    },
    {
        "feature_id": "gui_statistical_screening_controls",
        "repository": "gui",
        "family": "gui",
        "paths": ["src/advstatisticaloptions.cpp", "src/advstatisticaloptions.h"],
        "tokens": ["Statistical tests for raw data screening", "Vickers and Mahrt"],
    },
)


def build_eddypro_source_inventory(
    *,
    engine_root: str | Path | None = None,
    gui_root: str | Path | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Inventory official EddyPro source anchors without copying upstream code.

    The artifact is intentionally limited to repository metadata, file hashes,
    and token-level feature presence. It lets benchmark reports say exactly
    which public EddyPro source revision guided parity work.
    """
    roots = {
        "engine": _default_root(engine_root, "eddypro-engine-reference"),
        "gui": _default_root(gui_root, "eddypro-gui-reference"),
    }
    cache_key = _source_inventory_cache_key(roots)
    if use_cache and cache_key in _SOURCE_INVENTORY_CACHE:
        return deepcopy(_SOURCE_INVENTORY_CACHE[cache_key])
    repositories = {
        "engine": _repository_summary(
            label="EddyPro Engine",
            url=ENGINE_URL,
            clone_url=f"{ENGINE_URL}.git",
            root=roots["engine"],
        ),
        "gui": _repository_summary(
            label="EddyPro GUI",
            url=GUI_URL,
            clone_url=f"{GUI_URL}.git",
            root=roots["gui"],
        ),
    }
    feature_checks = [
        _feature_check(feature, roots.get(str(feature.get("repository", "")), Path()))
        for feature in EXPECTED_FEATURES
    ]
    missing_features = [item["feature_id"] for item in feature_checks if item["status"] != "present"]
    missing_repositories = [key for key, repo in repositories.items() if repo["status"] != "present"]
    inventory = {
        "artifact_type": "eddypro_official_source_inventory",
        "inventory_id": "eddypro_official_source_inventory_v1",
        "status": "pass" if not missing_features and not missing_repositories else "warning",
        "source_repositories": repositories,
        "feature_count": len(feature_checks),
        "present_feature_count": len(feature_checks) - len(missing_features),
        "missing_feature_count": len(missing_features),
        "missing_features": missing_features,
        "feature_checks": feature_checks,
        "truthfulness_note": (
            "This inventory records public EddyPro source-code anchors and feature-module presence. "
            "It does not import, copy, execute, or claim bit-for-bit parity with EddyPro."
        ),
        "known_limitations": [
            "Presence of a source module is not numerical parity.",
            "Real raw fixtures with official EddyPro outputs are still required for final parity claims.",
            "Local repository clones may lag upstream unless refreshed by the operator.",
        ],
    }
    _cache_source_inventory(cache_key, inventory)
    return inventory


def _source_inventory_cache_key(roots: dict[str, Path]) -> tuple[Any, ...]:
    signatures: list[tuple[Any, ...]] = []
    for label in ("engine", "gui"):
        root = roots[label]
        signatures.append((label, "root", _resolved_path_text(root), root.exists()))
        signatures.extend((label, "git", *item) for item in _repo_signature(root))
    for feature in EXPECTED_FEATURES:
        repository = str(feature.get("repository", ""))
        root = roots.get(repository, Path())
        for relative_path in [str(item) for item in feature.get("paths", [])]:
            signatures.append((repository, relative_path, *_file_signature(root / relative_path)))
    return ("eddypro_source_inventory_v1", tuple(signatures))


def _repo_signature(root: Path) -> tuple[tuple[str, int, int], ...]:
    git_dir = root / ".git"
    signatures = [_file_signature(git_dir / "HEAD"), _file_signature(git_dir / "config")]
    try:
        head = (git_dir / "HEAD").read_text(encoding="utf-8", errors="ignore").strip()
    except OSError:
        head = ""
    if head.startswith("ref:"):
        ref_path = head.removeprefix("ref:").strip()
        if ref_path:
            signatures.append(_file_signature(git_dir / ref_path))
    return tuple(signatures)


def _resolved_path_text(path: Path) -> str:
    try:
        return str(path.resolve())
    except OSError:
        return str(path.absolute())


def _file_signature(path: Path) -> tuple[str, int, int]:
    try:
        resolved = path.resolve()
    except OSError:
        resolved = path.absolute()
    try:
        stat = resolved.stat()
        return (str(resolved), int(stat.st_mtime_ns), int(stat.st_size))
    except OSError:
        return (str(resolved), 0, -1)


def _cache_source_inventory(cache_key: tuple[Any, ...], inventory: dict[str, Any]) -> None:
    if cache_key not in _SOURCE_INVENTORY_CACHE and len(_SOURCE_INVENTORY_CACHE) >= _SOURCE_INVENTORY_CACHE_MAX_ENTRIES:
        _SOURCE_INVENTORY_CACHE.pop(next(iter(_SOURCE_INVENTORY_CACHE)))
    _SOURCE_INVENTORY_CACHE[cache_key] = deepcopy(inventory)


def _default_root(value: str | Path | None, dirname: str) -> Path:
    if value not in (None, ""):
        return Path(value)
    return Path(os.environ.get("TEMP", "")) / dirname


def _repository_summary(*, label: str, url: str, clone_url: str, root: Path) -> dict[str, Any]:
    exists = root.exists()
    commit = _git_value(root, ["rev-parse", "HEAD"]) if exists else ""
    branch = _git_value(root, ["branch", "--show-current"]) if exists else ""
    configured_remote = _git_value(root, ["remote", "get-url", "origin"]) if exists else ""
    remote_head = _git_value(root, ["rev-parse", "origin/master"]) if exists else ""
    return {
        "label": label,
        "url": url,
        "clone_url": clone_url,
        "local_path": str(root),
        "status": "present" if exists and bool(commit) else "missing_local_reference",
        "branch": branch,
        "commit": commit,
        "origin_master_commit": remote_head,
        "remote_url": configured_remote,
        "remote_url_matches_official": configured_remote.rstrip("/") == clone_url.rstrip("/"),
    }


def _feature_check(feature: dict[str, Any], root: Path) -> dict[str, Any]:
    paths = [str(item) for item in feature.get("paths", [])]
    tokens = [str(item) for item in feature.get("tokens", [])]
    file_results = [_file_check(root, relative_path) for relative_path in paths]
    token_results = _token_checks(root, paths, tokens)
    missing_paths = [item["relative_path"] for item in file_results if not item["exists"]]
    missing_tokens = [token for token, present in token_results.items() if not present]
    return {
        "feature_id": str(feature.get("feature_id", "")),
        "repository": str(feature.get("repository", "")),
        "family": str(feature.get("family", "")),
        "status": "present" if not missing_paths and not missing_tokens else "missing",
        "files": file_results,
        "tokens": token_results,
        "missing_paths": missing_paths,
        "missing_tokens": missing_tokens,
    }


def _file_check(root: Path, relative_path: str) -> dict[str, Any]:
    path = root / relative_path
    exists = path.exists()
    return {
        "relative_path": relative_path,
        "exists": exists,
        "sha256": _sha256(path) if exists else "",
        "size_bytes": path.stat().st_size if exists else 0,
    }


def _token_checks(root: Path, paths: list[str], tokens: list[str]) -> dict[str, bool]:
    combined = []
    for relative_path in paths:
        path = root / relative_path
        if not path.exists():
            continue
        try:
            combined.append(path.read_text(encoding="utf-8", errors="ignore"))
        except OSError:
            continue
    haystack = "\n".join(combined)
    lowered = haystack.lower()
    return {token: token.lower() in lowered for token in tokens}


def _git_value(root: Path, args: list[str]) -> str:
    try:
        completed = subprocess.run(
            ["git", *args],
            cwd=str(root),
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().upper()
