from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
import re
import subprocess
import tempfile
from copy import deepcopy
from pathlib import Path
from typing import Any


ENGINE_URL = "https://github.com/LI-COR-Environmental/eddypro-engine"
GUI_URL = "https://github.com/LI-COR-Environmental/eddypro-gui"
DEFAULT_SOURCE_INVENTORY_SNAPSHOT_PATH = (
    Path(__file__).resolve().parents[2] / "references" / "eddypro" / "source_inventory_snapshot_v1.json"
)
_SOURCE_INVENTORY_CACHE_MAX_ENTRIES = 8
_SOURCE_INVENTORY_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_SOURCE_INVENTORY_PERSISTENT_CACHE_SCHEMA = "eddypro_source_inventory_cache_v3"
_SOURCE_INVENTORY_SNAPSHOT_SCHEMA = "eddypro_official_source_inventory_snapshot_v1"


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
    snapshot_path: str | Path | None = None,
    use_cache: bool = True,
) -> dict[str, Any]:
    """Inventory official EddyPro source anchors without copying upstream code.

    The artifact is intentionally limited to repository metadata, file hashes,
    and token-level feature presence. It lets benchmark reports say exactly
    which public EddyPro source revision guided parity work.
    """
    use_retained_snapshot = engine_root in (None, "") and gui_root in (None, "")
    retained_snapshot_path = (
        Path(snapshot_path) if snapshot_path not in (None, "") else DEFAULT_SOURCE_INVENTORY_SNAPSHOT_PATH
    )
    roots = {
        "engine": _default_root(engine_root, "eddypro-engine-reference"),
        "gui": _default_root(gui_root, "eddypro-gui-reference"),
    }
    cache_key = _source_inventory_cache_key(
        roots,
        snapshot_path=retained_snapshot_path if use_retained_snapshot else None,
    )
    if use_cache and cache_key in _SOURCE_INVENTORY_CACHE:
        return deepcopy(_SOURCE_INVENTORY_CACHE[cache_key])
    if use_cache:
        cached_inventory = _read_source_inventory_persistent_cache(cache_key)
        if cached_inventory is not None:
            _cache_source_inventory(cache_key, cached_inventory)
            return cached_inventory
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
    missing_repositories = [key for key, repo in repositories.items() if repo["status"] != "present"]
    if use_retained_snapshot and len(missing_repositories) == len(repositories):
        snapshot_inventory = _inventory_from_retained_snapshot(retained_snapshot_path)
        if snapshot_inventory is not None:
            _cache_source_inventory(cache_key, snapshot_inventory)
            _write_source_inventory_persistent_cache(cache_key, snapshot_inventory)
            return snapshot_inventory
    feature_checks = [
        _feature_check(feature, roots.get(str(feature.get("repository", "")), Path()))
        for feature in EXPECTED_FEATURES
    ]
    missing_features = [item["feature_id"] for item in feature_checks if item["status"] != "present"]
    inventory = {
        "artifact_type": "eddypro_official_source_inventory",
        "inventory_id": "eddypro_official_source_inventory_v1",
        "status": "pass" if not missing_features and not missing_repositories else "warning",
        "inventory_mode": "live_checkout",
        "live_source_checkout_available": not missing_repositories,
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
    _write_source_inventory_persistent_cache(cache_key, inventory)
    return inventory


def _source_inventory_cache_key(
    roots: dict[str, Path],
    *,
    snapshot_path: Path | None = None,
) -> tuple[Any, ...]:
    signatures: list[tuple[Any, ...]] = [("code", *_file_signature(Path(__file__)))]
    if snapshot_path is not None:
        signatures.append(("retained_snapshot", *_file_signature(snapshot_path)))
    for label in ("engine", "gui"):
        root = roots[label]
        signatures.append((label, "root", _resolved_path_text(root), root.exists()))
        signatures.extend((label, "git", *item) for item in _repo_signature(root))
    for feature in EXPECTED_FEATURES:
        repository = str(feature.get("repository", ""))
        root = roots.get(repository, Path())
        for relative_path in [str(item) for item in feature.get("paths", [])]:
            signatures.append((repository, relative_path, *_file_signature(root / relative_path)))
    return ("eddypro_source_inventory_v2", tuple(signatures))


def _inventory_from_retained_snapshot(path: Path) -> dict[str, Any] | None:
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not _valid_retained_snapshot(snapshot):
        return None

    repositories = {}
    snapshot_repositories = dict(snapshot.get("source_repositories", {}) or {})
    for key, label, url in (
        ("engine", "EddyPro Engine", ENGINE_URL),
        ("gui", "EddyPro GUI", GUI_URL),
    ):
        repository = dict(snapshot_repositories[key])
        clone_url = f"{url}.git"
        commit = str(repository["commit"])
        repositories[key] = {
            "label": label,
            "url": url,
            "clone_url": clone_url,
            "local_path": "",
            "status": "retained_snapshot",
            "branch": "",
            "commit": commit,
            "origin_master_commit": commit,
            "remote_url": clone_url,
            "remote_url_matches_official": True,
        }

    feature_checks = []
    snapshot_features = {
        str(item.get("feature_id", "")): dict(item)
        for item in list(snapshot.get("feature_checks", []) or [])
    }
    for expected in EXPECTED_FEATURES:
        item = snapshot_features[str(expected["feature_id"])]
        feature_checks.append(
            {
                "feature_id": str(expected["feature_id"]),
                "repository": str(expected["repository"]),
                "family": str(expected["family"]),
                "status": "present",
                "files": [
                    {
                        "relative_path": str(file_item["relative_path"]),
                        "exists": True,
                        "sha256": str(file_item["sha256"]).upper(),
                        "size_bytes": int(file_item["size_bytes"]),
                    }
                    for file_item in list(item.get("files", []) or [])
                ],
                "tokens": {str(token): True for token in list(item.get("tokens", []) or [])},
                "missing_paths": [],
                "missing_tokens": [],
            }
        )

    return {
        "artifact_type": "eddypro_official_source_inventory",
        "inventory_id": "eddypro_official_source_inventory_v1",
        "status": "pass",
        "inventory_mode": "retained_snapshot",
        "live_source_checkout_available": False,
        "retained_snapshot": {
            "snapshot_id": str(snapshot.get("snapshot_id", "")),
            "captured_at": str(snapshot.get("captured_at", "")),
            "artifact_path": str(snapshot.get("artifact_path", "")),
            "sha256": _sha256(path),
        },
        "source_repositories": repositories,
        "feature_count": len(feature_checks),
        "present_feature_count": len(feature_checks),
        "missing_feature_count": 0,
        "missing_features": [],
        "feature_checks": feature_checks,
        "truthfulness_note": (
            "This inventory uses a repository-retained snapshot of public source-code anchors when "
            "live reference checkouts are unavailable. It does not import, copy, execute, or claim "
            "bit-for-bit numerical parity with the reference software."
        ),
        "known_limitations": [
            "The retained snapshot records pinned revisions and hashes; it does not rescan upstream source in this run.",
            "Presence of a source module is not numerical parity.",
            "Real raw fixtures with official outputs are still required for final parity claims.",
        ],
    }


def _valid_retained_snapshot(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict) or snapshot.get("artifact_type") != _SOURCE_INVENTORY_SNAPSHOT_SCHEMA:
        return False
    if not str(snapshot.get("snapshot_id", "")).strip():
        return False
    repositories = dict(snapshot.get("source_repositories", {}) or {})
    for key, url in (("engine", ENGINE_URL), ("gui", GUI_URL)):
        repository = dict(repositories.get(key, {}) or {})
        if str(repository.get("url", "")).rstrip("/") != url.rstrip("/"):
            return False
        if re.fullmatch(r"[0-9a-fA-F]{40}", str(repository.get("commit", ""))) is None:
            return False

    expected_by_id = {str(item["feature_id"]): item for item in EXPECTED_FEATURES}
    feature_items = [dict(item or {}) for item in list(snapshot.get("feature_checks", []) or [])]
    feature_by_id = {str(item.get("feature_id", "")): item for item in feature_items}
    if len(feature_by_id) != len(feature_items) or set(feature_by_id) != set(expected_by_id):
        return False
    for feature_id, expected in expected_by_id.items():
        item = feature_by_id[feature_id]
        if str(item.get("repository", "")) != str(expected["repository"]):
            return False
        if str(item.get("family", "")) != str(expected["family"]):
            return False
        files = [dict(file_item or {}) for file_item in list(item.get("files", []) or [])]
        files_by_path = {str(file_item.get("relative_path", "")): file_item for file_item in files}
        if len(files_by_path) != len(files) or set(files_by_path) != set(expected["paths"]):
            return False
        for file_item in files_by_path.values():
            if re.fullmatch(r"[0-9a-fA-F]{64}", str(file_item.get("sha256", ""))) is None:
                return False
            try:
                size_bytes = int(file_item.get("size_bytes", 0) or 0)
            except (TypeError, ValueError):
                return False
            if size_bytes <= 0:
                return False
        if set(str(token) for token in list(item.get("tokens", []) or [])) != set(expected["tokens"]):
            return False
    return True


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


def _source_inventory_persistent_cache_dir() -> Path | None:
    disabled = str(os.environ.get("GAS_EC_DISABLE_EDDYPRO_SOURCE_INVENTORY_CACHE", "")).strip().lower()
    if disabled in {"1", "true", "yes", "on"}:
        return None
    configured = str(os.environ.get("GAS_EC_EDDYPRO_SOURCE_INVENTORY_CACHE_DIR", "") or "").strip()
    if configured:
        return Path(configured)
    return Path(tempfile.gettempdir()) / "gas_ec_studio" / "eddypro_source_inventory_cache"


def _source_inventory_persistent_cache_hash(cache_key: tuple[Any, ...]) -> str:
    encoded = json.dumps(cache_key, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest().upper()


def _source_inventory_persistent_cache_path(cache_key: tuple[Any, ...]) -> tuple[Path | None, str]:
    cache_hash = _source_inventory_persistent_cache_hash(cache_key)
    cache_dir = _source_inventory_persistent_cache_dir()
    if cache_dir is None:
        return None, cache_hash
    return cache_dir / f"{cache_hash}.json", cache_hash


def _read_source_inventory_persistent_cache(cache_key: tuple[Any, ...]) -> dict[str, Any] | None:
    path, cache_hash = _source_inventory_persistent_cache_path(cache_key)
    if path is None or not path.exists():
        return None
    try:
        wrapper = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if wrapper.get("artifact_type") != _SOURCE_INVENTORY_PERSISTENT_CACHE_SCHEMA:
        return None
    if str(wrapper.get("cache_hash", "")) != cache_hash:
        return None
    payload = wrapper.get("inventory", {})
    return deepcopy(payload) if isinstance(payload, dict) else None


def _write_source_inventory_persistent_cache(cache_key: tuple[Any, ...], inventory: dict[str, Any]) -> None:
    path, cache_hash = _source_inventory_persistent_cache_path(cache_key)
    if path is None:
        return
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = path.with_name(f"{path.name}.{os.getpid()}.tmp")
        tmp_path.write_text(
            json.dumps(
                {
                    "artifact_type": _SOURCE_INVENTORY_PERSISTENT_CACHE_SCHEMA,
                    "cache_hash": cache_hash,
                    "created_at": datetime.now().isoformat(),
                    "inventory": inventory,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        tmp_path.replace(path)
    except OSError:
        return


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
