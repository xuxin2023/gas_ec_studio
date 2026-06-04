from __future__ import annotations

from collections import Counter
from copy import deepcopy
from datetime import datetime
import glob
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import sys
import time
from typing import Any

from core.comparison.eddypro_full_output_normalizer import write_eddypro_full_output_reference
from core.storage.ghg_bundle import inspect_ghg_bundle, load_ghg_normalized_frames
from core.storage.raw_importer import (
    _inspect_tob1_header,
    can_load_raw_native,
    can_load_raw_text,
    load_raw_native_frames,
    load_raw_text_frames,
)
from models.station_models import MetadataBundle


BUNDLE_MANIFEST_NAMES = (
    "official_raw_fixture_bundle.json",
    "fixture_bundle.json",
    "manifest.json",
)
OFFICIAL_EDDYPRO_RUN_MANIFEST_NAMES = (
    "official_eddypro_run.json",
    "eddypro_run.json",
    "eddypro_executable_run.json",
    "run_provenance.json",
)
OFFICIAL_EDDYPRO_PROJECT_PREPARE_NAMES = (
    "official_eddypro_project_prepare.json",
    "eddypro_project_prepare.json",
)

RAW_ROLE_CHOICES = ("raw_file", "raw_ghg_file", "tob1_file", "slt_file", "native_binary_file")
PROJECT_ROLE_CHOICES = ("eddypro_project_file", "project_file", "settings_file")
OUTPUT_ROLE_CHOICES = ("official_full_output", "full_output_csv", "source_csv")
REFERENCE_ROLE_CHOICES = ("reference_json",)
PROVENANCE_ROLE_CHOICES = ("provenance_json",)

CANONICAL_FILE_ROLES = (
    *RAW_ROLE_CHOICES,
    "metadata_json",
    *PROJECT_ROLE_CHOICES,
    *OUTPUT_ROLE_CHOICES,
    *REFERENCE_ROLE_CHOICES,
    *PROVENANCE_ROLE_CHOICES,
)
ACQUISITION_ACCEPTANCE_COMMANDS = [
    "python -m pytest tests/test_official_raw_fixture_bundle.py tests/test_eddypro_fixture_pack.py tests/test_raw_to_final_parity.py -q",
    "python -m pytest tests/test_eddypro_coverage_audit.py tests/test_result_exports.py -q",
]
ACCEPTANCE_STDIO_TAIL_CHARS = 4000


def official_raw_fixture_bundle_schema() -> dict[str, Any]:
    return {
        "artifact_type": "official_raw_fixture_bundle_schema_v1",
        "manifest_filename": "official_raw_fixture_bundle.json",
        "required_file_groups": {
            "high_frequency_raw_input": list(RAW_ROLE_CHOICES),
            "eddypro_project_or_settings_file": list(PROJECT_ROLE_CHOICES),
            "official_eddypro_full_output": list(OUTPUT_ROLE_CHOICES),
            "normalized_reference_json": list(REFERENCE_ROLE_CHOICES),
            "normalization_provenance": list(PROVENANCE_ROLE_CHOICES),
        },
        "recommended_manifest_keys": [
            "fixture_id",
            "site_class",
            "software",
            "software_version",
            "official_eddypro_run",
            "files",
            "import_plan",
            "rp_config",
            "thresholds",
            "known_limitations",
        ],
        "required_provenance": {
            "official_eddypro_executable_run": [
                "software_version",
                "command",
                "run_completed_at",
                "exit_code=0",
                "official output file hash",
            ],
        },
        "truthfulness_note": (
            "A bundle can close the release gate only when it contains raw high-frequency input, "
            "EddyPro project/settings, official EddyPro output, normalized reference JSON, provenance, "
            "and official EddyPro executable run provenance."
        ),
    }


def inspect_official_raw_fixture_bundle(
    bundle_dir: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    root = Path(workspace_root) if workspace_root is not None else Path.cwd()
    bundle_root = Path(bundle_dir)
    manifest_path = _find_bundle_manifest(bundle_root)
    errors: list[str] = []
    declared: dict[str, Any] = {}
    if manifest_path is not None:
        try:
            declared = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            errors.append(f"bundle manifest invalid: {exc}")
    elif not bundle_root.exists():
        errors.append(f"bundle directory missing: {bundle_root}")

    role_values = _declared_file_roles(declared)
    inferred_roles = _infer_file_roles(bundle_root)
    for role, value in inferred_roles.items():
        role_values.setdefault(role, value)

    files = {
        role: _file_claim(bundle_root, role, value, root=root)
        for role, value in sorted(role_values.items())
        if role in CANONICAL_FILE_ROLES
    }
    import_plan = _build_import_plan(files=files, declared=declared, root=root)
    missing_required = _missing_required_groups(files)
    fixture_id = str(declared.get("fixture_id") or _safe_fixture_id(bundle_root.name))
    status = "ready_for_registration"
    if errors:
        status = "invalid_manifest"
    elif missing_required:
        status = "incomplete"
    declared_with_sidecar = _declared_manifest_with_discovered_run(bundle_root, declared, files)
    asset_preview = (
        _asset_from_claims(fixture_id=fixture_id, declared=declared_with_sidecar, files=files, root=root)
        if status == "ready_for_registration"
        else {}
    )
    official_run = _official_eddypro_run_summary(declared_with_sidecar, files)
    payload = {
        "artifact_type": "official_raw_fixture_bundle_inspection_v1",
        "bundle_root": str(bundle_root),
        "manifest_path": str(manifest_path or ""),
        "generated_at": datetime.now().isoformat(),
        "fixture_id": fixture_id,
        "status": status,
        "schema": official_raw_fixture_bundle_schema(),
        "declared_manifest": _public_declared_manifest(declared_with_sidecar),
        "files": files,
        "import_plan": import_plan,
        "normalization_result": dict(declared_with_sidecar.get("normalization_result", {}) or {}),
        "official_run_normalization_result": dict(declared_with_sidecar.get("official_run_normalization_result", {}) or {}),
        "official_eddypro_run": official_run,
        "official_eddypro_run_checklist": _official_eddypro_run_checklist(official_run),
        "inferred_file_roles": sorted(role for role in inferred_roles if role not in _declared_file_roles(declared)),
        "missing_required_files": missing_required,
        "asset_preview": asset_preview,
        "truthfulness_note": (
            "This inspection verifies package completeness and hashes. It does not claim numeric EddyPro parity "
            "until the generated asset is registered and its raw-to-final harness passes against the official output."
        ),
        "errors": errors,
    }
    payload["acquisition_validation"] = _acquisition_validation_from_inspection(payload)
    return payload


def validate_official_raw_fixture_acquisition(
    bundle_dir: str | Path,
    *,
    workspace_root: str | Path | None = None,
    parity_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate whether a real EddyPro raw bundle can close the P0 fixture gate.

    This is stricter than inspection: inspection says a bundle can be registered;
    acquisition validation says which closure evidence exists now and whether the
    remaining blocker is registration/parity execution.
    """

    inspection = inspect_official_raw_fixture_bundle(bundle_dir, workspace_root=workspace_root)
    return _acquisition_validation_from_inspection(inspection, parity_payload=parity_payload)


def capture_official_eddypro_run_evidence(
    bundle_dir: str | Path,
    *,
    command: str,
    software_version: str = "",
    software: str = "EddyPro",
    executable_path: str = "",
    project_file: str = "",
    output_files: list[str] | None = None,
    working_directory: str | Path | None = None,
    timeout_s: float = 900.0,
    workspace_root: str | Path | None = None,
    sidecar_name: str = "official_eddypro_run.json",
    write_sidecar: bool = True,
) -> dict[str, Any]:
    """Run an operator-supplied EddyPro command and write auditable run evidence.

    The command is intentionally supplied by the operator because EddyPro is an
    external program. This function records the actual process result and hashes
    the declared official output files; it never turns a failed or incomplete run
    into a passing release-gate artifact.
    """

    root = Path(workspace_root) if workspace_root is not None else Path.cwd()
    bundle_root = Path(bundle_dir)
    sidecar_path = bundle_root / sidecar_name
    started_at = datetime.now()
    timer = time.perf_counter()
    cwd = _official_run_working_directory(bundle_root, working_directory)
    command_text = command.strip()
    output_file_values = _official_run_output_file_values(bundle_root, output_files)
    base_run = {
        "artifact_type": "official_eddypro_executable_run_v1",
        "software": software.strip() or "EddyPro",
        "software_version": software_version.strip(),
        "executable_path": executable_path.strip(),
        "command": command_text,
        "working_directory": str(cwd),
        "project_file": str(project_file or ""),
        "run_started_at": started_at.isoformat(),
        "run_completed_at": "",
        "duration_s": 0.0,
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
        "output_files": [str(value).replace("\\", "/") for value in output_file_values],
        "output_file_hashes": [],
        "capture_tool": "gas_ec_studio_official_eddypro_run_capture_v1",
        "truthfulness_note": (
            "This sidecar records an operator-supplied EddyPro executable run. "
            "A pass requires exit_code=0 plus a hashable official output file."
        ),
    }
    if not command_text:
        base_run.update(
            {
                "run_completed_at": datetime.now().isoformat(),
                "capture_status": "missing_command",
                "capture_error": "command is required",
            }
        )
    else:
        try:
            completed = subprocess.run(
                command_text,
                cwd=cwd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=float(timeout_s),
                check=False,
            )
            base_run.update(
                {
                    "exit_code": int(completed.returncode),
                    "stdout_tail": _stdio_tail(completed.stdout),
                    "stderr_tail": _stdio_tail(completed.stderr),
                    "capture_status": "command_pass" if completed.returncode == 0 else "command_fail",
                }
            )
        except subprocess.TimeoutExpired as exc:
            base_run.update(
                {
                    "capture_status": "timeout",
                    "capture_error": f"command exceeded timeout_s={timeout_s}",
                    "stdout_tail": _stdio_tail(exc.stdout),
                    "stderr_tail": _stdio_tail(exc.stderr),
                }
            )
        except OSError as exc:
            base_run.update({"capture_status": "error", "capture_error": str(exc)})
        finally:
            base_run["run_completed_at"] = datetime.now().isoformat()
            base_run["duration_s"] = round(time.perf_counter() - timer, 3)

    output_file_values = _official_run_output_file_values(bundle_root, output_files, expand_patterns=True)
    base_run["output_files"] = [str(value).replace("\\", "/") for value in output_file_values]
    base_run["output_file_hashes"] = _official_run_output_hashes(bundle_root, output_file_values, root=root)
    files = _official_run_summary_file_claims(bundle_root, output_file_values, root=root)
    declared = {
        "software": base_run["software"],
        "software_version": base_run["software_version"],
        "official_eddypro_run": base_run,
    }
    summary = _official_eddypro_run_summary(declared, files)
    base_run["validation"] = summary
    capture_status = "pass" if summary.get("gate_status") == "pass" else str(base_run.get("capture_status", "incomplete"))
    base_run["capture_status"] = capture_status
    if write_sidecar:
        sidecar_path.parent.mkdir(parents=True, exist_ok=True)
        sidecar_path.write_text(json.dumps(base_run, ensure_ascii=False, indent=2), encoding="utf-8")
        _sync_official_eddypro_run_into_manifest(
            bundle_root=bundle_root,
            run_payload=base_run,
            sidecar_name=sidecar_name,
            files=files,
        )
    return {
        "artifact_type": "official_eddypro_run_capture_v1",
        "status": capture_status,
        "gate_status": "pass" if summary.get("gate_status") == "pass" else "blocked",
        "bundle_root": str(bundle_root),
        "sidecar_path": str(sidecar_path) if write_sidecar else "",
        "official_eddypro_run": summary,
        "sidecar": base_run,
        "output_file_hashes": list(base_run.get("output_file_hashes", []) or []),
        "truthfulness_note": (
            "This capture executes the supplied command and preserves the process result. "
            "It does not prove numeric parity by itself; registration, raw-to-final parity, and evidence-pack acceptance remain required."
        ),
    }


def prepare_official_eddypro_project_for_capture(
    bundle_dir: str | Path,
    *,
    run_home: str | Path | None = None,
    mode: str = "embedded",
    raw_files: list[str] | None = None,
    overwrite: bool = False,
    workspace_root: str | Path | None = None,
    sidecar_name: str = "official_eddypro_project_prepare.json",
) -> dict[str, Any]:
    """Create a reproducible EddyPro run home without modifying source assets."""

    root = Path(workspace_root) if workspace_root is not None else Path.cwd()
    bundle_root = Path(bundle_dir)
    sidecar_path = bundle_root / sidecar_name
    generated_at = datetime.now().isoformat()
    if not bundle_root.exists() or not bundle_root.is_dir():
        return {
            "artifact_type": "official_eddypro_project_prepare_v1",
            "status": "missing_bundle_dir",
            "generated_at": generated_at,
            "bundle_root": str(bundle_root),
            "sidecar_path": str(sidecar_path),
            "errors": [f"bundle directory missing: {bundle_root}"],
        }

    mode_value = (mode or "embedded").strip().lower()
    if mode_value not in {"embedded", "desktop"}:
        return {
            "artifact_type": "official_eddypro_project_prepare_v1",
            "status": "unsupported_mode",
            "generated_at": generated_at,
            "bundle_root": str(bundle_root),
            "sidecar_path": str(sidecar_path),
            "mode": mode_value,
            "errors": [f"unsupported EddyPro capture mode: {mode}"],
        }

    inspection = inspect_official_raw_fixture_bundle(bundle_root, workspace_root=root)
    files = dict(inspection.get("files", {}) or {})
    project_claim = next(
        (dict(files.get(role, {}) or {}) for role in PROJECT_ROLE_CHOICES if dict(files.get(role, {}) or {}).get("exists")),
        {},
    )
    project_path = Path(str(project_claim.get("path", ""))) if project_claim else None
    if project_path is None or not project_path.exists():
        return {
            "artifact_type": "official_eddypro_project_prepare_v1",
            "status": "missing_project_file",
            "generated_at": generated_at,
            "bundle_root": str(bundle_root),
            "sidecar_path": str(sidecar_path),
            "errors": ["EddyPro project/settings file is required before official executable capture."],
        }

    selected_raw_values, raw_strategy = _official_eddypro_prepare_raw_values(
        bundle_root=bundle_root,
        files=files,
        raw_files=raw_files,
    )
    selected_raw_paths = [_resolve_bundle_path(value, bundle_root) for value in selected_raw_values]
    missing_raw = [
        str(value)
        for value, path in zip(selected_raw_values, selected_raw_paths)
        if path is None or not path.exists() or not path.is_file()
    ]
    if missing_raw:
        return {
            "artifact_type": "official_eddypro_project_prepare_v1",
            "status": "missing_raw_files",
            "generated_at": generated_at,
            "bundle_root": str(bundle_root),
            "sidecar_path": str(sidecar_path),
            "raw_selection_strategy": raw_strategy,
            "selected_raw_files": selected_raw_values,
            "errors": [f"raw file missing: {value}" for value in missing_raw],
        }

    run_home_path = _official_eddypro_run_home(bundle_root, run_home)
    if run_home_path.exists():
        if not overwrite:
            return {
                "artifact_type": "official_eddypro_project_prepare_v1",
                "status": "run_home_exists",
                "generated_at": generated_at,
                "bundle_root": str(bundle_root),
                "run_home": str(run_home_path),
                "sidecar_path": str(sidecar_path),
                "errors": ["run home already exists; pass overwrite=True to rebuild the prepared capture workspace."],
            }
        if not _is_relative_to(run_home_path, bundle_root):
            return {
                "artifact_type": "official_eddypro_project_prepare_v1",
                "status": "unsafe_run_home",
                "generated_at": generated_at,
                "bundle_root": str(bundle_root),
                "run_home": str(run_home_path),
                "sidecar_path": str(sidecar_path),
                "errors": ["refusing to overwrite an EddyPro run home outside the fixture bundle."],
            }
        shutil.rmtree(run_home_path)

    ini_dir = run_home_path / "ini"
    raw_dir = run_home_path / "raw_files"
    output_dir = run_home_path / "output"
    tmp_dir = run_home_path / "tmp"
    for folder in (ini_dir, raw_dir, output_dir, tmp_dir):
        folder.mkdir(parents=True, exist_ok=True)

    source_text = project_path.read_text(encoding="utf-8", errors="replace")
    patched_text, project_changes = _patch_eddypro_project_capture_paths(
        source_text,
        data_path=raw_dir,
        out_path=output_dir,
    )
    project_copy = ini_dir / "processing.eddypro"
    project_copy.write_text(patched_text, encoding="utf-8")

    copied_raw_files: list[dict[str, Any]] = []
    for raw_path in selected_raw_paths:
        if raw_path is None:
            continue
        destination = raw_dir / raw_path.name
        shutil.copy2(raw_path, destination)
        copied_raw_files.append(
            {
                "source": str(raw_path),
                "source_relative_to_bundle": str(raw_path.relative_to(bundle_root)).replace("\\", "/")
                if _is_relative_to(raw_path, bundle_root)
                else str(raw_path),
                "prepared": str(destination),
                "prepared_relative_to_bundle": str(destination.relative_to(bundle_root)).replace("\\", "/")
                if _is_relative_to(destination, bundle_root)
                else str(destination),
                "size_bytes": destination.stat().st_size,
                "sha256": _sha256(destination),
            }
        )

    run_home_relative = (
        str(run_home_path.relative_to(bundle_root)).replace("\\", "/")
        if _is_relative_to(run_home_path, bundle_root)
        else str(run_home_path)
    )
    output_pattern = str((output_dir / "*full_output*.csv").relative_to(bundle_root)).replace("\\", "/") if _is_relative_to(output_dir, bundle_root) else str(output_dir / "*full_output*.csv")
    project_relative = str(project_copy.relative_to(bundle_root)).replace("\\", "/") if _is_relative_to(project_copy, bundle_root) else str(project_copy)
    payload = {
        "artifact_type": "official_eddypro_project_prepare_v1",
        "status": "prepared",
        "generated_at": generated_at,
        "bundle_root": str(bundle_root),
        "mode": mode_value,
        "run_home": str(run_home_path),
        "run_home_relative_to_bundle": run_home_relative,
        "sidecar_path": str(sidecar_path),
        "source_project_file": str(project_path),
        "source_project_relative_to_bundle": str(project_path.relative_to(bundle_root)).replace("\\", "/")
        if _is_relative_to(project_path, bundle_root)
        else str(project_path),
        "prepared_project_file": str(project_copy),
        "prepared_project_relative_to_bundle": project_relative,
        "source_project_sha256": _sha256(project_path),
        "prepared_project_sha256": _sha256(project_copy),
        "raw_selection_strategy": raw_strategy,
        "copied_raw_files": copied_raw_files,
        "project_changes": project_changes,
        "directory_layout": {
            "ini": str(ini_dir),
            "raw_files": str(raw_dir),
            "output": str(output_dir),
            "tmp": str(tmp_dir),
        },
        "recommended_capture": {
            "mode": mode_value,
            "command_suffix": f'-m {mode_value} -e "{run_home_path.resolve()}"'
            if mode_value == "embedded"
            else f'"{project_relative}"',
            "working_directory": ".",
            "project_file": project_relative,
            "output_files": [output_pattern],
            "run_home": run_home_relative,
        },
        "truthfulness_note": (
            "The original EddyPro project and raw files are preserved. This artifact records the prepared "
            "run home and path rewrites used only to execute the official EddyPro engine reproducibly."
        ),
        "errors": [],
    }
    sidecar_path.parent.mkdir(parents=True, exist_ok=True)
    sidecar_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return payload


def build_official_eddypro_executable_readiness(
    bundle_dir: str | Path,
    *,
    source_dir: str | Path | None = None,
    executable_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Report whether the current host can produce an official EddyPro run sidecar.

    This deliberately does not mark anything as passed. It inventories the exact
    bundle, upstream source checkout, executable/toolchain availability, and the
    next commands required to create a truthful `official_eddypro_run.json`.
    """

    root = Path(workspace_root) if workspace_root is not None else Path.cwd()
    bundle_root = Path(bundle_dir)
    inspection = inspect_official_raw_fixture_bundle(bundle_root, workspace_root=root)
    explicit_executable = Path(executable_path) if executable_path not in (None, "") else None
    executable_candidates = _official_eddypro_executable_candidates(explicit_executable)
    present_executables = [item for item in executable_candidates if item.get("exists")]
    source_summary = _official_eddypro_source_checkout_summary(Path(source_dir)) if source_dir not in (None, "") else {}
    toolchain = _official_eddypro_toolchain_summary()
    project_preparation = _discover_official_eddypro_project_prepare(bundle_root)
    missing_requirements = _official_eddypro_readiness_missing_requirements(
        inspection=inspection,
        present_executables=present_executables,
        source_summary=source_summary,
        toolchain=toolchain,
    )
    status = "ready_to_capture" if not missing_requirements else "blocked"
    if inspection.get("status") != "ready_for_registration":
        status = "bundle_incomplete"
    elif not present_executables and source_summary.get("status") == "source_ready" and not toolchain.get("can_build_engine"):
        status = "source_ready_toolchain_missing"
    elif not present_executables and source_summary.get("status") == "source_ready":
        status = "source_ready_build_needed"
    elif not present_executables:
        status = "executable_missing"
    return {
        "artifact_type": "official_eddypro_executable_readiness_v1",
        "generated_at": datetime.now().isoformat(),
        "status": status,
        "gate_status": "ready_to_capture" if status == "ready_to_capture" else "blocked",
        "bundle_root": str(bundle_root),
        "bundle_status": str(inspection.get("status", "")),
        "fixture_id": str(inspection.get("fixture_id", "")),
        "official_eddypro_run_gate_status": str(dict(inspection.get("official_eddypro_run", {}) or {}).get("gate_status", "")),
        "official_eddypro_run_missing_requirements": list(
            dict(inspection.get("official_eddypro_run", {}) or {}).get("missing_requirements", []) or []
        ),
        "executable_candidates": executable_candidates,
        "present_executable_count": len(present_executables),
        "selected_executable": present_executables[0] if present_executables else {},
        "source_checkout": source_summary,
        "toolchain": toolchain,
        "project_preparation": project_preparation,
        "missing_requirements": missing_requirements,
        "build_commands": _official_eddypro_build_commands(source_summary),
        "capture_command": _official_eddypro_capture_command(
            bundle_root=bundle_root,
            inspection=inspection,
            executable=present_executables[0] if present_executables else {},
            project_preparation=project_preparation,
        ),
        "truthfulness_note": (
            "This artifact only reports readiness to capture an official EddyPro executable run. "
            "Full parity remains blocked until the command is executed, exit_code=0 is recorded, "
            "official output hashes are present, raw-to-final parity passes, and evidence-pack acceptance passes."
        ),
    }


def build_official_raw_fixture_evidence_pack(
    bundle_dir: str | Path,
    *,
    workspace_root: str | Path | None = None,
    parity_payload: dict[str, Any] | None = None,
    acquisition_validation: dict[str, Any] | None = None,
    fixture_detail: dict[str, Any] | None = None,
    closure_gate: dict[str, Any] | None = None,
    acceptance_results: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build the auditable evidence pack for one official raw fixture bundle."""

    inspection = inspect_official_raw_fixture_bundle(bundle_dir, workspace_root=workspace_root)
    acquisition = (
        dict(acquisition_validation)
        if acquisition_validation is not None
        else _acquisition_validation_from_inspection(inspection, parity_payload=parity_payload)
    )
    files = dict(inspection.get("files", {}) or {})
    file_manifest = [
        {
            "role": role,
            "path": str(dict(claim or {}).get("path", "")),
            "relative_to_bundle": str(dict(claim or {}).get("relative_to_bundle", "")),
            "relative_to_workspace": str(dict(claim or {}).get("relative_to_workspace", "")),
            "exists": bool(dict(claim or {}).get("exists", False)),
            "size_bytes": int(dict(claim or {}).get("size_bytes", 0) or 0),
            "sha256": str(dict(claim or {}).get("sha256", "")),
        }
        for role, claim in sorted(files.items())
    ]
    parity = dict(parity_payload or {})
    detail = dict(fixture_detail or {})
    provenance = _normalization_provenance_summary(files)
    acceptance_payload = _acceptance_payload_from_results(list(acceptance_results or []))
    return {
        "artifact_type": "official_raw_fixture_evidence_pack_v1",
        "evidence_pack_id": f"{inspection.get('fixture_id', Path(str(bundle_dir)).name)}_evidence_pack_v1",
        "generated_at": datetime.now().isoformat(),
        "status": "complete" if acquisition.get("gate_status") == "pass" else "pending_closure",
        "fixture_id": str(inspection.get("fixture_id", "")),
        "bundle_root": str(inspection.get("bundle_root", "")),
        "manifest_path": str(inspection.get("manifest_path", "")),
        "inspection_status": str(inspection.get("status", "")),
        "source_files": file_manifest,
        "source_file_count": len(file_manifest),
        "present_source_file_count": sum(1 for item in file_manifest if item.get("exists")),
        "hash_manifest": {
            str(item.get("role", "")): {
                "sha256": str(item.get("sha256", "")),
                "size_bytes": int(item.get("size_bytes", 0) or 0),
                "path": str(item.get("path", "")),
            }
            for item in file_manifest
            if item.get("role")
        },
        "official_eddypro_run": dict(inspection.get("official_eddypro_run", {}) or {}),
        "official_eddypro_run_checklist": dict(inspection.get("official_eddypro_run_checklist", {}) or {}),
        "normalization_provenance": provenance,
        "official_run_normalization": dict(inspection.get("official_run_normalization_result", {}) or {}),
        "acquisition_validation": acquisition,
        "closure_gate_snapshot": dict(closure_gate or {}),
        "parity_artifact": str(parity.get("artifact", "") or detail.get("parity_artifact", "")),
        "parity_summary": {
            "status": str(parity.get("status", detail.get("status", ""))),
            "pass_rate": float(parity.get("pass_rate", detail.get("pass_rate", 0.0)) or 0.0),
            "failed_fields": list(parity.get("failed_fields", detail.get("failed_fields", [])) or []),
            "trace_gas_status": str(parity.get("trace_gas_parity_status", detail.get("trace_gas_parity_status", ""))),
        },
        "fixture_detail_summary": {
            "fixture_id": str(detail.get("fixture_id", inspection.get("fixture_id", ""))),
            "readiness_level": str(detail.get("readiness_level", "")),
            "site_class": str(detail.get("site_class", "")),
            "software": str(detail.get("software", "")),
            "software_version": str(detail.get("software_version", "")),
        },
        "acceptance_commands": list(acquisition.get("acceptance_commands", ACQUISITION_ACCEPTANCE_COMMANDS) or []),
        "acceptance_status": acceptance_payload["status"],
        "acceptance_gate_status": acceptance_payload["gate_status"],
        "acceptance_run": acceptance_payload["run"],
        "acceptance_results": acceptance_payload["results"],
        "blocked_claims": list(acquisition.get("blocked_claims", []) or []),
        "truthfulness_note": (
            "This pack preserves evidence references and hashes. It supports full-parity claims only when acquisition_validation.gate_status is pass "
            "and the referenced parity artifact was produced from the same raw bundle."
        ),
        "known_limitations": [
            "The pack records file paths and hashes; it does not embed large raw source files.",
            "Acceptance command results must be refreshed after any source, configuration, or reference change.",
        ],
    }


def run_official_raw_evidence_pack_acceptance(
    evidence_pack: str | Path | dict[str, Any],
    *,
    workspace_root: str | Path | None = None,
    commands: list[str] | None = None,
    timeout_s: float = 300.0,
    write_back: bool = True,
) -> dict[str, Any]:
    """Run safe evidence-pack acceptance commands and return the updated pack.

    The runner intentionally supports only the pytest commands generated by the
    acquisition gate. Other command strings are recorded as skipped evidence
    instead of being executed.
    """

    evidence_path: Path | None = None
    if isinstance(evidence_pack, (str, Path)):
        evidence_path = Path(evidence_pack)
        payload = _read_json(evidence_path)
    else:
        payload = deepcopy(dict(evidence_pack or {}))
    if not payload:
        payload = {
            "artifact_type": "official_raw_fixture_evidence_pack_v1",
            "status": "error",
            "errors": ["evidence pack missing or invalid"],
        }

    selected_commands = list(commands if commands is not None else payload.get("acceptance_commands", []) or [])
    started_at = datetime.now()
    results: list[dict[str, Any]] = []
    root = _acceptance_workspace_root(workspace_root)
    for command in selected_commands:
        results.append(_run_acceptance_command(str(command), workspace_root=root, timeout_s=timeout_s))
    completed_at = datetime.now()
    run = _acceptance_run_payload(
        results=results,
        workspace_root=root,
        started_at=started_at,
        completed_at=completed_at,
        timeout_s=timeout_s,
    )
    updated = deepcopy(payload)
    updated.setdefault("artifact_type", "official_raw_fixture_evidence_pack_v1")
    updated["acceptance_commands"] = selected_commands
    updated["acceptance_results"] = results
    updated["acceptance_run"] = run
    updated["acceptance_status"] = run["status"]
    updated["acceptance_gate_status"] = run["gate_status"]
    updated["acceptance_completed_at"] = run["completed_at"]
    updated["status"] = _evidence_pack_status_with_acceptance(updated, run["status"])
    updated.setdefault("known_limitations", [])
    limitation = "Acceptance commands are restricted to safe pytest invocations and must be rerun after source/reference changes."
    if limitation not in updated["known_limitations"]:
        updated["known_limitations"].append(limitation)
    if evidence_path is not None and write_back:
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        updated["artifact"] = str(evidence_path)
        evidence_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    return updated


def _acceptance_payload_from_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    if not results:
        return {"status": "not_run", "gate_status": "not_run", "results": [], "run": {}}
    now = datetime.now()
    run = _acceptance_run_payload(
        results=results,
        workspace_root=_acceptance_workspace_root(None),
        started_at=now,
        completed_at=now,
        timeout_s=0.0,
    )
    return {"status": run["status"], "gate_status": run["gate_status"], "results": results, "run": run}


def _acceptance_workspace_root(workspace_root: str | Path | None) -> Path:
    root = Path(workspace_root) if workspace_root is not None else Path.cwd()
    cwd = Path.cwd()
    if not (root / "tests").exists() and (cwd / "tests").exists():
        return cwd
    return root


def _run_acceptance_command(command: str, *, workspace_root: Path, timeout_s: float) -> dict[str, Any]:
    started_at = datetime.now()
    timer = time.perf_counter()
    argv, rejection_reason = _safe_acceptance_argv(command)
    base = {
        "command": command,
        "started_at": started_at.isoformat(),
        "workspace_root": str(workspace_root),
        "duration_s": 0.0,
        "exit_code": None,
        "stdout_tail": "",
        "stderr_tail": "",
    }
    if rejection_reason:
        base.update(
            {
                "status": "skipped_unsafe",
                "rejection_reason": rejection_reason,
                "completed_at": datetime.now().isoformat(),
            }
        )
        return base
    try:
        completed = subprocess.run(
            argv,
            cwd=workspace_root,
            capture_output=True,
            text=True,
            timeout=float(timeout_s),
            check=False,
        )
        status = "pass" if completed.returncode == 0 else "fail"
        base.update(
            {
                "status": status,
                "exit_code": int(completed.returncode),
                "stdout_tail": _stdio_tail(completed.stdout),
                "stderr_tail": _stdio_tail(completed.stderr),
            }
        )
    except subprocess.TimeoutExpired as exc:
        base.update(
            {
                "status": "timeout",
                "rejection_reason": f"command exceeded timeout_s={timeout_s}",
                "stdout_tail": _stdio_tail(exc.stdout),
                "stderr_tail": _stdio_tail(exc.stderr),
            }
        )
    except OSError as exc:
        base.update({"status": "error", "rejection_reason": str(exc)})
    base["completed_at"] = datetime.now().isoformat()
    base["duration_s"] = round(time.perf_counter() - timer, 3)
    return base


def _safe_acceptance_argv(command: str) -> tuple[list[str], str]:
    try:
        parts = shlex.split(command)
    except ValueError as exc:
        return [], f"could not parse command: {exc}"
    if len(parts) < 3:
        return [], "acceptance commands must use: python -m pytest ..."
    executable = Path(parts[0]).name.lower()
    if executable in {"python", "python.exe", "python3", "python3.exe", "py", "py.exe"} and parts[1:3] == ["-m", "pytest"]:
        return [sys.executable, *parts[1:]], ""
    return [], "only python -m pytest commands from the evidence pack are allowed"


def _acceptance_run_payload(
    *,
    results: list[dict[str, Any]],
    workspace_root: Path,
    started_at: datetime,
    completed_at: datetime,
    timeout_s: float,
) -> dict[str, Any]:
    status_counts = Counter(str(item.get("status", "unknown")) for item in results)
    command_count = len(results)
    failed_count = int(status_counts.get("fail", 0) + status_counts.get("timeout", 0) + status_counts.get("error", 0))
    skipped_count = int(status_counts.get("skipped_unsafe", 0))
    passed_count = int(status_counts.get("pass", 0))
    if command_count == 0:
        status = "blocked_no_commands"
    elif failed_count > 0:
        status = "fail"
    elif skipped_count > 0:
        status = "blocked_unsafe_commands"
    elif passed_count == command_count:
        status = "pass"
    else:
        status = "warning"
    return {
        "artifact_type": "official_raw_evidence_pack_acceptance_run_v1",
        "status": status,
        "gate_status": "pass" if status == "pass" else "blocked",
        "started_at": started_at.isoformat(),
        "completed_at": completed_at.isoformat(),
        "workspace_root": str(workspace_root),
        "timeout_s": float(timeout_s),
        "command_count": command_count,
        "passed_count": passed_count,
        "failed_count": failed_count,
        "skipped_count": skipped_count,
        "status_counts": dict(status_counts),
        "results": results,
    }


def _evidence_pack_status_with_acceptance(evidence_pack: dict[str, Any], acceptance_status: str) -> str:
    acquisition = dict(evidence_pack.get("acquisition_validation", {}) or {})
    if acquisition.get("gate_status") != "pass":
        return "pending_closure"
    if acceptance_status == "pass":
        return "complete"
    return "needs_acceptance"


def _stdio_tail(value: Any) -> str:
    if isinstance(value, bytes):
        text = value.decode("utf-8", errors="replace")
    else:
        text = str(value or "")
    return text[-ACCEPTANCE_STDIO_TAIL_CHARS:]


def _acquisition_validation_from_inspection(
    inspection: dict[str, Any],
    *,
    parity_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    files = dict(inspection.get("files", {}) or {})
    parity = dict(parity_payload or {})
    official_run = dict(inspection.get("official_eddypro_run", {}) or {})
    requirements = [
        _requirement_item(
            requirement_id="official_raw_bundle_manifest",
            label="Official raw bundle manifest",
            claims=[{"exists": bool(inspection.get("manifest_path")), "path": str(inspection.get("manifest_path", ""))}],
            missing=[] if inspection.get("manifest_path") else ["official_raw_fixture_bundle.json"],
        ),
        _requirement_item(
            requirement_id="raw_high_frequency_input",
            label="Raw high-frequency input",
            claims=_claims_for_roles(files, RAW_ROLE_CHOICES),
            missing=["one of: " + ", ".join(RAW_ROLE_CHOICES)],
        ),
        _requirement_item(
            requirement_id="eddypro_project_settings",
            label="EddyPro project/settings",
            claims=_claims_for_roles(files, PROJECT_ROLE_CHOICES),
            missing=["one of: " + ", ".join(PROJECT_ROLE_CHOICES)],
        ),
        _requirement_item(
            requirement_id="official_eddypro_full_output",
            label="Official EddyPro Full Output",
            claims=_claims_for_roles(files, OUTPUT_ROLE_CHOICES),
            missing=["one of: " + ", ".join(OUTPUT_ROLE_CHOICES)],
        ),
        _requirement_item(
            requirement_id="normalized_reference_with_provenance",
            label="Normalized reference plus provenance",
            claims=[
                *_claims_for_roles(files, REFERENCE_ROLE_CHOICES),
                *_claims_for_roles(files, PROVENANCE_ROLE_CHOICES),
            ],
            missing=["reference_json", "provenance_json"],
            require_all=True,
            required_count_override=2,
        ),
        {
            "requirement_id": "official_eddypro_executable_run",
            "label": "Official EddyPro executable run provenance",
            "status": "pass" if official_run.get("gate_status") == "pass" else "fail",
            "required_for_closure": True,
            "present_count": 1 if official_run.get("gate_status") == "pass" else 0,
            "required_count": 1,
            "evidence_paths": [
                str(item.get("path", ""))
                for item in list(official_run.get("output_files", []) or [])
                if str(item.get("path", ""))
            ],
            "missing": list(official_run.get("missing_requirements", []) or ["official_eddypro_run"]),
            "detail": official_run,
        },
    ]
    parity_status = str(parity.get("status", "") or "")
    parity_artifact = str(parity.get("artifact", "") or "")
    requirements.append(
        {
            "requirement_id": "raw_to_final_parity_pass",
            "label": "Raw-to-final parity pass",
            "status": "pass" if parity_status == "pass" else ("fail" if parity_status == "fail" else "pending"),
            "required_for_closure": True,
            "present_count": 1 if parity_status == "pass" else 0,
            "required_count": 1,
            "evidence_paths": [parity_artifact] if parity_artifact else [],
            "missing": [] if parity_status == "pass" else ["registered raw-to-final parity artifact with status=pass"],
            "detail": {
                "parity_status": parity_status or "not_run",
                "pass_rate": float(parity.get("pass_rate", 0.0) or 0.0),
                "failed_fields": list(parity.get("failed_fields", []) or []),
            },
        }
    )
    missing_required = [
        str(requirement.get("requirement_id", ""))
        for requirement in requirements
        if str(requirement.get("status", "")) != "pass"
    ]
    inspection_status = str(inspection.get("status", "") or "")
    if any(str(requirement.get("status", "")) == "fail" for requirement in requirements):
        status = "blocked"
    elif parity_status == "pass" and inspection_status == "ready_for_registration":
        status = "closure_ready"
    elif inspection_status == "ready_for_registration":
        status = "ready_for_registration_pending_parity"
    else:
        status = "blocked"
    provenance_summary = _normalization_provenance_summary(files)
    return {
        "artifact_type": "official_raw_fixture_acquisition_validation_v1",
        "closure_id": "fixture_pack:official_raw_to_final_ready_count",
        "priority": "P0",
        "status": status,
        "gate_status": "pass" if status == "closure_ready" else "blocked",
        "fixture_id": str(inspection.get("fixture_id", "")),
        "bundle_root": str(inspection.get("bundle_root", "")),
        "inspection_status": inspection_status,
        "missing_requirements": missing_required,
        "requirements": requirements,
        "official_eddypro_run": official_run,
        "official_eddypro_run_checklist": _official_eddypro_run_checklist(official_run),
        "provenance_summary": provenance_summary,
        "acceptance_commands": list(ACQUISITION_ACCEPTANCE_COMMANDS),
        "blocked_claims": [] if status == "closure_ready" else ["official_raw_to_final_numeric_parity", "full_eddypro_parity"],
        "truthfulness_note": (
            "P0 acquisition validation closes only after required source files are present and a registered raw-to-final parity artifact passes."
        ),
    }


def _claims_for_roles(files: dict[str, Any], roles: tuple[str, ...]) -> list[dict[str, Any]]:
    return [dict(files.get(role, {}) or {}) for role in roles if role in files]


def _requirement_item(
    *,
    requirement_id: str,
    label: str,
    claims: list[dict[str, Any]],
    missing: list[str],
    require_all: bool = False,
    required_count_override: int | None = None,
) -> dict[str, Any]:
    present = [claim for claim in claims if bool(dict(claim or {}).get("exists", False))]
    required_count = int(required_count_override) if required_count_override is not None else (len(claims) if require_all else 1)
    passed = len(present) >= required_count if require_all else bool(present)
    return {
        "requirement_id": requirement_id,
        "label": label,
        "status": "pass" if passed else "fail",
        "required_for_closure": True,
        "present_count": len(present),
        "required_count": required_count,
        "evidence_paths": [
            str(dict(claim or {}).get("path", ""))
            for claim in present
            if str(dict(claim or {}).get("path", ""))
        ],
        "missing": [] if passed else missing,
    }


def _normalization_provenance_summary(files: dict[str, Any]) -> dict[str, Any]:
    provenance_claim = next((dict(files.get(role, {}) or {}) for role in PROVENANCE_ROLE_CHOICES if role in files), {})
    path = Path(str(provenance_claim.get("path", "")))
    payload: dict[str, Any] = {}
    if provenance_claim.get("exists"):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            payload = {}
    return {
        "provenance_file": str(path) if provenance_claim.get("exists") else "",
        "normalization_command": str(payload.get("normalization_command", "")),
        "normalization_time": str(payload.get("normalization_time", "")),
        "qc_mapping_strategy": str(payload.get("qc_mapping_strategy", "")),
        "known_limitations": list(payload.get("known_limitations", []) or []),
    }


def _official_eddypro_run_summary(declared: dict[str, Any], files: dict[str, Any]) -> dict[str, Any]:
    run = dict(declared.get("official_eddypro_run", {}) or declared.get("eddypro_run", {}) or {})
    output_files = [
        {
            "role": role,
            "path": str(dict(files.get(role, {}) or {}).get("path", "")),
            "sha256": str(dict(files.get(role, {}) or {}).get("sha256", "")),
            "size_bytes": int(dict(files.get(role, {}) or {}).get("size_bytes", 0) or 0),
        }
        for role in OUTPUT_ROLE_CHOICES
        if role in files and bool(dict(files.get(role, {}) or {}).get("exists", False))
    ]
    declared_output_hashes = _declared_official_output_hashes(run)
    output_hash_seen = any(item.get("sha256") for item in output_files) or any(item.get("sha256") for item in declared_output_hashes)
    software_version = str(run.get("software_version") or declared.get("software_version", "") or "").strip()
    command = str(run.get("command", "") or "").strip()
    executable_path = str(run.get("executable_path") or run.get("executable") or "").strip()
    run_completed_at = str(run.get("run_completed_at") or run.get("completed_at") or run.get("generated_at") or "").strip()
    exit_code = _parse_exit_code(run.get("exit_code"))
    missing: list[str] = []
    if not run:
        missing.append("official_eddypro_run manifest section")
    if not software_version:
        missing.append("software_version")
    if not command:
        missing.append("command")
    if not run_completed_at:
        missing.append("run_completed_at")
    if exit_code != 0:
        missing.append("exit_code=0")
    if not output_hash_seen:
        missing.append("official output file hash")
    status = "pass" if not missing else ("not_declared" if not run else "incomplete")
    return {
        "artifact_type": "official_eddypro_executable_run_v1",
        "status": status,
        "gate_status": "pass" if status == "pass" else "blocked",
        "software": str(declared.get("software", "EddyPro") or "EddyPro"),
        "software_version": software_version,
        "executable_path": executable_path,
        "command": command,
        "run_completed_at": run_completed_at,
        "exit_code": exit_code,
        "working_directory": str(run.get("working_directory", "") or ""),
        "project_file": str(run.get("project_file", "") or ""),
        "source_file": str(run.get("source_file", "") or ""),
        "output_files": output_files,
        "declared_output_hashes": declared_output_hashes,
        "declared_output_files": list(run.get("output_files", []) or []),
        "missing_requirements": missing,
        "source": "official_raw_fixture_bundle_manifest",
        "truthfulness_note": (
            "This records provenance that the official output was generated by EddyPro. "
            "It is a release-gate input; Gas EC Studio does not synthesize or infer this run as passed."
        ),
    }


def _declared_manifest_with_discovered_run(
    bundle_root: Path,
    declared: dict[str, Any],
    files: dict[str, Any],
) -> dict[str, Any]:
    current = dict(declared.get("official_eddypro_run", {}) or declared.get("eddypro_run", {}) or {})
    discovered = _discover_official_eddypro_run_payload(
        bundle_root,
        files,
        software=str(declared.get("software", "EddyPro") or "EddyPro"),
        software_version=str(declared.get("software_version", "") or ""),
    )
    if current and not discovered:
        return declared
    if current and discovered:
        current_summary = _official_eddypro_run_summary(
            {
                "software": str(declared.get("software", "EddyPro") or "EddyPro"),
                "software_version": str(declared.get("software_version", "") or ""),
                "official_eddypro_run": current,
            },
            files,
        )
        discovered_summary = _official_eddypro_run_summary(
            {
                "software": str(declared.get("software", "EddyPro") or "EddyPro"),
                "software_version": str(declared.get("software_version", "") or ""),
                "official_eddypro_run": discovered,
            },
            files,
        )
        if current_summary.get("gate_status") == "pass" or discovered_summary.get("gate_status") != "pass":
            return declared
    if not current and not discovered:
        return declared
    updated = deepcopy(declared)
    updated["official_eddypro_run"] = discovered
    return updated


def _official_run_working_directory(bundle_root: Path, working_directory: str | Path | None) -> Path:
    if working_directory in (None, ""):
        return bundle_root
    path = Path(str(working_directory))
    return path if path.is_absolute() else bundle_root / path


def _official_run_output_file_values(
    bundle_root: Path,
    output_files: list[str] | None,
    *,
    expand_patterns: bool = False,
) -> list[str]:
    if output_files:
        values = [str(item) for item in output_files if str(item).strip()]
        return _expand_official_run_output_values(bundle_root, values) if expand_patterns else values
    inferred = _infer_file_roles(bundle_root)
    values = [
        str(inferred[role]).replace("\\", "/")
        for role in OUTPUT_ROLE_CHOICES
        if role in inferred and str(inferred.get(role, "")).strip()
    ]
    return _expand_official_run_output_values(bundle_root, values) if expand_patterns else values


def _expand_official_run_output_values(bundle_root: Path, values: list[str]) -> list[str]:
    expanded: list[str] = []
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        path = Path(raw)
        has_pattern = any(token in raw for token in ("*", "?", "["))
        if has_pattern:
            matches = [Path(item) for item in glob.glob(str(path if path.is_absolute() else bundle_root / raw))]
            file_matches = [item for item in matches if item.exists() and item.is_file()]
            if file_matches:
                expanded.extend(_bundle_relative_or_absolute(bundle_root, item) for item in sorted(file_matches))
            else:
                expanded.append(raw)
            continue
        candidate = path if path.is_absolute() else bundle_root / path
        if candidate.exists() and candidate.is_dir():
            files = [
                item
                for item in candidate.rglob("*.csv")
                if item.is_file() and "full_output" in item.name.lower()
            ]
            expanded.extend(_bundle_relative_or_absolute(bundle_root, item) for item in sorted(files))
            if not files:
                expanded.append(raw)
            continue
        expanded.append(raw)
    return _dedupe(expanded)


def _bundle_relative_or_absolute(bundle_root: Path, path: Path) -> str:
    return (
        str(path.relative_to(bundle_root)).replace("\\", "/")
        if _is_relative_to(path, bundle_root)
        else str(path)
    )


def _official_run_output_hashes(bundle_root: Path, output_files: list[str], *, root: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for value in output_files:
        claim = _file_claim(bundle_root, "official_output", value, root=root)
        records.append(
            {
                "path": str(claim.get("path", "")),
                "relative_to_bundle": str(claim.get("relative_to_bundle", "")),
                "relative_to_workspace": str(claim.get("relative_to_workspace", "")),
                "exists": bool(claim.get("exists", False)),
                "size_bytes": int(claim.get("size_bytes", 0) or 0),
                "sha256": str(claim.get("sha256", "")),
            }
        )
    return records


def _official_run_summary_file_claims(bundle_root: Path, output_files: list[str], *, root: Path) -> dict[str, Any]:
    role_values = _infer_file_roles(bundle_root)
    if output_files and not any(role_values.get(role) for role in OUTPUT_ROLE_CHOICES):
        role_values["official_full_output"] = output_files[0]
    return {
        role: _file_claim(bundle_root, role, value, root=root)
        for role, value in sorted(role_values.items())
        if role in CANONICAL_FILE_ROLES
    }


def _sync_official_eddypro_run_into_manifest(
    *,
    bundle_root: Path,
    run_payload: dict[str, Any],
    sidecar_name: str,
    files: dict[str, Any],
) -> None:
    manifest_path = _find_bundle_manifest(bundle_root)
    if manifest_path is None:
        return
    manifest = _read_json(manifest_path)
    if not manifest:
        return
    synced_run = deepcopy(run_payload)
    synced_run["source_file"] = sidecar_name
    manifest["official_eddypro_run"] = synced_run
    manifest["official_eddypro_run_checklist"] = _official_eddypro_run_checklist(
        _official_eddypro_run_summary(
            {
                "software": str(manifest.get("software", "EddyPro") or "EddyPro"),
                "software_version": str(manifest.get("software_version", "") or ""),
                "official_eddypro_run": synced_run,
            },
            files,
        )
    )
    manifest["official_eddypro_run_synced_at"] = datetime.now().isoformat()
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def _official_eddypro_prepare_raw_values(
    *,
    bundle_root: Path,
    files: dict[str, Any],
    raw_files: list[str] | None,
) -> tuple[list[str], str]:
    explicit = [str(item).replace("\\", "/") for item in list(raw_files or []) if str(item).strip()]
    if explicit:
        return explicit, "explicit_raw_files"
    manifest_path = _find_bundle_manifest(bundle_root)
    manifest = _read_json(manifest_path) if manifest_path is not None else {}
    declared_raw_files = [
        str(item).replace("\\", "/")
        for item in list(manifest.get("raw_files", []) or [])
        if str(item).strip()
    ]
    if declared_raw_files:
        return declared_raw_files[:1], "first_declared_raw_file"
    for role in RAW_ROLE_CHOICES:
        claim = dict(files.get(role, {}) or {})
        if claim.get("exists") and claim.get("relative_to_bundle"):
            return [str(claim.get("relative_to_bundle", "")).replace("\\", "/")], f"first_{role}"
    inferred = _infer_file_roles(bundle_root)
    for role in RAW_ROLE_CHOICES:
        if inferred.get(role):
            return [str(inferred[role]).replace("\\", "/")], f"inferred_{role}"
    return [], "none"


def _official_eddypro_run_home(bundle_root: Path, run_home: str | Path | None) -> Path:
    if run_home in (None, ""):
        return bundle_root / "official_eddypro_run_home"
    path = Path(str(run_home))
    return path if path.is_absolute() else bundle_root / path


def _patch_eddypro_project_capture_paths(
    text: str,
    *,
    data_path: Path,
    out_path: Path,
) -> tuple[str, list[dict[str, str]]]:
    replacements = {
        "data_path": _eddypro_directory_value(data_path),
        "out_path": _eddypro_directory_value(out_path),
    }
    changes: list[dict[str, str]] = []
    lines = text.splitlines(keepends=True)
    patched: list[str] = []
    seen: set[str] = set()
    for line in lines:
        body = line.rstrip("\r\n")
        newline = line[len(body):]
        if "=" not in body or body.lstrip().startswith(";"):
            patched.append(line)
            continue
        key, old_value = body.split("=", 1)
        normalized_key = key.strip().lower()
        if normalized_key in replacements and normalized_key not in seen:
            new_value = replacements[normalized_key]
            patched.append(f"{key}={new_value}{newline}")
            seen.add(normalized_key)
            if old_value != new_value:
                changes.append({"key": normalized_key, "old_value": old_value, "new_value": new_value})
        else:
            patched.append(line)
    if seen != set(replacements):
        if patched and not patched[-1].endswith(("\n", "\r")):
            patched.append("\n")
        for key, new_value in replacements.items():
            if key in seen:
                continue
            patched.append(f"{key}={new_value}\n")
            changes.append({"key": key, "old_value": "", "new_value": new_value})
    return "".join(patched), changes


def _eddypro_directory_value(path: Path) -> str:
    value = str(path.resolve())
    if not value.endswith(("\\", "/")):
        value += "\\"
    return value


def _declared_official_output_hashes(run: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for item in list(run.get("output_file_hashes", []) or []):
        if not isinstance(item, dict):
            continue
        records.append(
            {
                "path": str(item.get("path", "")),
                "relative_to_bundle": str(item.get("relative_to_bundle", "")),
                "relative_to_workspace": str(item.get("relative_to_workspace", "")),
                "exists": bool(item.get("exists", False)),
                "size_bytes": int(item.get("size_bytes", 0) or 0),
                "sha256": str(item.get("sha256", "")),
            }
        )
    for item in list(run.get("output_files", []) or []):
        if isinstance(item, dict):
            sha256 = str(item.get("sha256", ""))
            if sha256:
                records.append(
                    {
                        "path": str(item.get("path", "")),
                        "relative_to_bundle": str(item.get("relative_to_bundle", "")),
                        "relative_to_workspace": str(item.get("relative_to_workspace", "")),
                        "exists": bool(item.get("exists", False)),
                        "size_bytes": int(item.get("size_bytes", 0) or 0),
                        "sha256": sha256,
                    }
                )
    return records


def _discover_official_eddypro_run_payload(
    bundle_root: Path,
    files: dict[str, dict[str, Any]],
    *,
    software: str,
    software_version: str,
) -> dict[str, Any]:
    for candidate in _official_eddypro_run_candidates(bundle_root):
        try:
            payload = json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        run = dict(payload.get("official_eddypro_run", payload))
        run.setdefault("software", software or "EddyPro")
        if software_version:
            run.setdefault("software_version", software_version)
        project_role = _first_existing_role(files, PROJECT_ROLE_CHOICES)
        if project_role and not run.get("project_file"):
            run["project_file"] = str(dict(files.get(project_role, {}) or {}).get("relative_to_bundle", ""))
        if not run.get("output_files"):
            run["output_files"] = [
                str(dict(files.get(role, {}) or {}).get("relative_to_bundle", ""))
                for role in OUTPUT_ROLE_CHOICES
                if role in files and bool(dict(files.get(role, {}) or {}).get("exists", False))
            ]
        run["source_file"] = str(candidate.relative_to(bundle_root)).replace("\\", "/")
        return run
    return {}


def _official_eddypro_run_candidates(bundle_root: Path) -> list[Path]:
    if not bundle_root.exists() or not bundle_root.is_dir():
        return []
    names = set(OFFICIAL_EDDYPRO_RUN_MANIFEST_NAMES)
    direct = [
        bundle_root / name
        for name in OFFICIAL_EDDYPRO_RUN_MANIFEST_NAMES
    ]
    nested = [
        path
        for path in bundle_root.rglob("*.json")
        if path.name.lower() in names
    ]
    return list(dict.fromkeys(path for path in [*direct, *nested] if path.exists() and path.is_file()))


def _discover_official_eddypro_project_prepare(bundle_root: Path) -> dict[str, Any]:
    for candidate in _official_eddypro_project_prepare_candidates(bundle_root):
        payload = _read_json(candidate)
        if not payload:
            continue
        payload = dict(payload)
        payload["source_file"] = str(candidate.relative_to(bundle_root)).replace("\\", "/") if _is_relative_to(candidate, bundle_root) else str(candidate)
        return payload
    return {}


def _official_eddypro_project_prepare_candidates(bundle_root: Path) -> list[Path]:
    if not bundle_root.exists() or not bundle_root.is_dir():
        return []
    names = set(OFFICIAL_EDDYPRO_PROJECT_PREPARE_NAMES)
    direct = [bundle_root / name for name in OFFICIAL_EDDYPRO_PROJECT_PREPARE_NAMES]
    nested = [
        path
        for path in bundle_root.rglob("*.json")
        if path.name.lower() in names
    ]
    return list(dict.fromkeys(path for path in [*direct, *nested] if path.exists() and path.is_file()))


def _official_eddypro_run_checklist(run_summary: dict[str, Any]) -> dict[str, Any]:
    missing = list(run_summary.get("missing_requirements", []) or [])
    status = "pass" if str(run_summary.get("gate_status", "")) == "pass" else "needs_operator_evidence"
    return {
        "artifact_type": "official_eddypro_run_checklist_v1",
        "status": status,
        "missing_requirements": missing,
        "accepted_sidecar_filenames": list(OFFICIAL_EDDYPRO_RUN_MANIFEST_NAMES),
        "required_fields": [
            "software_version",
            "command",
            "run_completed_at",
            "exit_code=0",
            "official output file hash",
        ],
        "template": {
            "software_version": str(run_summary.get("software_version", "")) or "7.x",
            "executable_path": "C:/Program Files/LI-COR/EddyPro/eddypro.exe",
            "command": "eddypro.exe --run path/to/project.eddypro",
            "run_completed_at": "YYYY-MM-DDTHH:MM:SS",
            "exit_code": 0,
            "project_file": "eddypro/project.eddypro",
            "output_files": ["eddypro/eddypro_full_output.csv"],
        },
        "truthfulness_note": (
            "The import wizard can read this evidence from official_eddypro_run.json or eddypro_run.json. "
            "It will not mark the executable-run gate as passed until the required fields and output hash are present."
        ),
    }


def _official_eddypro_executable_candidates(explicit_executable: Path | None = None) -> list[dict[str, Any]]:
    raw_candidates: list[Path] = []
    if explicit_executable is not None:
        raw_candidates.append(explicit_executable)
    for name in ("eddypro_rp.exe", "eddypro-rp.exe", "eddypro.exe", "eddypro_fcc.exe", "eddypro-rp", "eddypro"):
        found = shutil.which(name)
        if found:
            raw_candidates.append(Path(found))
    for base in (Path("C:/Program Files"), Path("C:/Program Files (x86)")):
        raw_candidates.extend(
            [
                base / "LI-COR" / "EddyPro" / "eddypro_rp.exe",
                base / "LI-COR" / "EddyPro" / "eddypro.exe",
                base / "LI-COR" / "EddyPro" / "bin" / "eddypro_rp.exe",
            ]
        )
    candidates: list[dict[str, Any]] = []
    seen: set[str] = set()
    for path in raw_candidates:
        key = str(path).lower()
        if key in seen:
            continue
        seen.add(key)
        exists = path.exists() and path.is_file()
        candidates.append(
            {
                "path": str(path),
                "exists": exists,
                "size_bytes": path.stat().st_size if exists else 0,
                "sha256": _sha256(path) if exists else "",
                "source": "explicit" if explicit_executable is not None and path == explicit_executable else "auto_discovery",
            }
        )
    return candidates


def _official_eddypro_source_checkout_summary(source_dir: Path) -> dict[str, Any]:
    exists = source_dir.exists() and source_dir.is_dir()
    readme = source_dir / "README.md"
    makefile = source_dir / "prj" / "Makefile"
    commit = _git_value(source_dir, "rev-parse", "HEAD") if exists else ""
    remote = _git_value(source_dir, "config", "--get", "remote.origin.url") if exists else ""
    status = "source_ready" if exists and readme.exists() and makefile.exists() else "missing"
    if exists and not commit:
        status = "source_present_unverified"
    return {
        "path": str(source_dir),
        "exists": exists,
        "status": status,
        "remote_url": remote,
        "commit": commit,
        "readme_path": str(readme),
        "readme_exists": readme.exists(),
        "makefile_path": str(makefile),
        "makefile_exists": makefile.exists(),
        "rp_target": "make rp",
        "fcc_target": "make fcc",
        "source_note": "Official eddypro-engine checkout used only as build/run provenance; it is not copied into the project tree.",
    }


def _git_value(cwd: Path, *args: str) -> str:
    try:
        completed = subprocess.run(
            ["git", "-C", str(cwd), *args],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if completed.returncode != 0:
        return ""
    return completed.stdout.strip()


def _official_eddypro_toolchain_summary() -> dict[str, Any]:
    tools = {
        name: _tool_record(name)
        for name in ("gfortran", "gfortran.exe", "make", "mingw32-make", "git", "cmake")
    }
    has_fortran = any(tools[name]["available"] for name in ("gfortran", "gfortran.exe"))
    has_make = any(tools[name]["available"] for name in ("make", "mingw32-make"))
    return {
        "tools": tools,
        "has_fortran_compiler": has_fortran,
        "has_make": has_make,
        "has_git": tools["git"]["available"],
        "can_build_engine": bool(has_fortran and has_make),
        "install_attempt_notes": [
            "On Windows, MSYS2 with mingw-w64-x86_64-gcc-fortran and make is the expected minimal toolchain.",
            "A failed package-manager download should be recorded here or in the generated artifact before retrying.",
        ],
    }


def _tool_record(name: str) -> dict[str, Any]:
    path = shutil.which(name)
    if not path:
        for candidate in _common_windows_tool_paths(name):
            if candidate.exists() and candidate.is_file():
                path = str(candidate)
                break
    return {
        "name": name,
        "available": bool(path),
        "path": str(path or ""),
    }


def _common_windows_tool_paths(name: str) -> list[Path]:
    msys_roots = [Path("D:/tools/msys64"), Path("C:/msys64")]
    names = [name]
    if not name.lower().endswith(".exe"):
        names.append(f"{name}.exe")
    candidates: list[Path] = []
    for root in msys_roots:
        for candidate_name in names:
            candidates.extend(
                [
                    root / "mingw64" / "bin" / candidate_name,
                    root / "usr" / "bin" / candidate_name,
                ]
            )
    return candidates


def _official_eddypro_readiness_missing_requirements(
    *,
    inspection: dict[str, Any],
    present_executables: list[dict[str, Any]],
    source_summary: dict[str, Any],
    toolchain: dict[str, Any],
) -> list[str]:
    missing: list[str] = []
    if inspection.get("status") != "ready_for_registration":
        missing.append("official raw bundle must be ready_for_registration")
    if not present_executables:
        missing.append("EddyPro RP executable not found")
        if source_summary.get("status") != "source_ready":
            missing.append("official eddypro-engine source checkout not ready")
        if source_summary.get("status") == "source_ready" and not toolchain.get("can_build_engine"):
            if not toolchain.get("has_fortran_compiler"):
                missing.append("gfortran compiler missing")
            if not toolchain.get("has_make"):
                missing.append("make/mingw32-make missing")
    return _dedupe(missing)


def _official_eddypro_build_commands(source_summary: dict[str, Any]) -> list[str]:
    source_path = str(source_summary.get("path", "") or "D:/external_sources/eddypro-engine")
    return [
        "winget install --id MSYS2.MSYS2 --exact --accept-package-agreements --accept-source-agreements",
        "C:\\msys64\\usr\\bin\\bash.exe -lc \"pacman -Syu --noconfirm\"",
        "C:\\msys64\\usr\\bin\\bash.exe -lc \"pacman -S --needed --noconfirm base-devel mingw-w64-x86_64-gcc-fortran mingw-w64-x86_64-make make\"",
        f"set PATH=D:\\tools\\msys64\\mingw64\\bin;D:\\tools\\msys64\\usr\\bin;%PATH% && mingw32-make.exe -C \"{source_path}\"\\prj SHELL=cmd.exe rp",
    ]


def _official_eddypro_capture_command(
    *,
    bundle_root: Path,
    inspection: dict[str, Any],
    executable: dict[str, Any],
    project_preparation: dict[str, Any] | None = None,
) -> str:
    files = dict(inspection.get("files", {}) or {})
    prepared = dict(project_preparation or {})
    recommended = dict(prepared.get("recommended_capture", {}) or {})
    project = next(
        (
            str(dict(files.get(role, {}) or {}).get("relative_to_bundle", ""))
            for role in PROJECT_ROLE_CHOICES
            if role in files and dict(files.get(role, {}) or {}).get("exists")
        ),
        "eddypro/processing_project.eddypro",
    )
    output = next(
        (
            str(dict(files.get(role, {}) or {}).get("relative_to_bundle", ""))
            for role in OUTPUT_ROLE_CHOICES
            if role in files and dict(files.get(role, {}) or {}).get("exists")
        ),
        "eddypro/eddypro_full_output.csv",
    )
    executable_path = str(executable.get("path", "")) if executable else "PATH_TO_EDDYPRO_RP"
    if prepared.get("status") == "prepared" and recommended:
        command_suffix = str(recommended.get("command_suffix", "")).strip()
        prepared_project = str(recommended.get("project_file", "") or project)
        prepared_outputs = list(recommended.get("output_files", []) or [output])
        command_arg = f'"{executable_path}" {command_suffix}'.replace('"', '\\"')
        return (
            "python -m core.headless_batch_runner "
            f"--capture-official-eddypro-run \"{bundle_root}\" "
            f"--official-run-executable \"{executable_path}\" "
            f"--official-run-command \"{command_arg}\" "
            f"--official-run-project-file \"{prepared_project}\" "
            f"--official-run-output-files \"{','.join(str(item) for item in prepared_outputs)}\" "
            "--official-run-software-version \"EddyPro\" "
            "--workspace-root . "
            f"--output \"{bundle_root / 'official_eddypro_run_capture.json'}\""
        )
    return (
        "python -m core.headless_batch_runner "
        f"--capture-official-eddypro-run \"{bundle_root}\" "
        f"--official-run-executable \"{executable_path}\" "
        f"--official-run-command \"{executable_path} {project}\" "
        f"--official-run-project-file \"{project}\" "
        f"--official-run-output-files \"{output}\" "
        "--official-run-software-version \"EddyPro\" "
        "--workspace-root . "
        f"--output \"{bundle_root / 'official_eddypro_run_capture.json'}\""
    )


def _parse_exit_code(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def fixture_asset_from_official_raw_bundle(
    bundle_dir: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    inspection = inspect_official_raw_fixture_bundle(bundle_dir, workspace_root=workspace_root)
    if inspection.get("status") != "ready_for_registration":
        missing = ", ".join(str(item) for item in inspection.get("missing_required_files", []))
        errors = ", ".join(str(item) for item in inspection.get("errors", []))
        detail = "; ".join(item for item in (missing, errors) if item)
        raise ValueError(f"Official raw fixture bundle is not ready for registration: {detail}")
    return dict(inspection.get("asset_preview", {}) or {})


def build_official_raw_fixture_bundle_manifest(
    bundle_dir: str | Path,
    *,
    fixture_id: str = "",
    site_class: str = "",
    software: str = "EddyPro",
    software_version: str = "",
    rp_config: dict[str, Any] | None = None,
    thresholds: dict[str, Any] | None = None,
    known_limitations: list[str] | None = None,
    overwrite: bool = False,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Infer and write an official raw fixture bundle manifest.

    This is the import-wizard bridge for real EddyPro folders: it preserves the
    original raw/project/output/reference files in place and writes only the
    small manifest that makes the folder inspectable and registerable.
    """

    root = Path(workspace_root) if workspace_root is not None else Path.cwd()
    bundle_root = Path(bundle_dir)
    manifest_path = bundle_root / "official_raw_fixture_bundle.json"
    if not bundle_root.exists() or not bundle_root.is_dir():
        return {
            "artifact_type": "official_raw_fixture_bundle_manifest_build_v1",
            "status": "missing_bundle_dir",
            "bundle_root": str(bundle_root),
            "manifest_path": str(manifest_path),
            "generated_at": datetime.now().isoformat(),
            "errors": [f"bundle directory missing: {bundle_root}"],
        }
    existing_manifest = _find_bundle_manifest(bundle_root)
    if existing_manifest is not None and not overwrite:
        refresh = _refresh_existing_manifest_official_run_normalization(
            bundle_root=bundle_root,
            manifest_path=existing_manifest,
            root=root,
        )
        inspection = inspect_official_raw_fixture_bundle(bundle_root, workspace_root=root)
        return {
            "artifact_type": "official_raw_fixture_bundle_manifest_build_v1",
            "status": "manifest_refreshed" if refresh.get("manifest_updated") else "manifest_exists",
            "bundle_root": str(bundle_root),
            "manifest_path": str(existing_manifest),
            "generated_at": datetime.now().isoformat(),
            "official_run_normalization_result": dict(refresh.get("official_run_normalization_result", {}) or {}),
            "manifest_updated": bool(refresh.get("manifest_updated", False)),
            "inspection": inspection,
            "errors": list(refresh.get("errors", []) or []),
            "truthfulness_note": (
                "Existing manifest file roles were preserved. Missing official executable-run normalization "
                "metadata may be appended non-destructively; use overwrite=True only after reviewing the current manifest."
            ),
        }

    inferred_roles = _infer_file_roles(bundle_root)
    _apply_official_prepare_role_hints(bundle_root, inferred_roles)
    pre_normalization_files = {
        role: _file_claim(bundle_root, role, value, root=root)
        for role, value in sorted(inferred_roles.items())
        if role in CANONICAL_FILE_ROLES
    }
    official_eddypro_run = _discover_official_eddypro_run_payload(
        bundle_root,
        pre_normalization_files,
        software=software.strip() or "EddyPro",
        software_version=software_version.strip(),
    )
    normalization_result = _ensure_normalized_reference_from_full_output(
        bundle_root,
        inferred_roles,
        fixture_id=fixture_id.strip() or _safe_fixture_id(bundle_root.name),
        root=root,
    )
    official_run_normalization_result = _ensure_normalized_reference_from_official_run_output(
        bundle_root,
        official_eddypro_run,
        fixture_id=fixture_id.strip() or _safe_fixture_id(bundle_root.name),
        root=root,
    )
    files = {
        role: _file_claim(bundle_root, role, value, root=root)
        for role, value in sorted(inferred_roles.items())
        if role in CANONICAL_FILE_ROLES
    }
    official_eddypro_run_summary = _official_eddypro_run_summary(
        {"software": software.strip() or "EddyPro", "software_version": software_version.strip(), "official_eddypro_run": official_eddypro_run}
        if official_eddypro_run
        else {"software": software.strip() or "EddyPro", "software_version": software_version.strip()},
        files,
    )
    missing_required = _missing_required_groups(files)
    import_plan = _build_import_plan(files=files, declared={}, root=root)
    default_config = _default_rp_config_from_file_claims(files)
    if import_plan.get("rp_config_draft"):
        default_config = _merge_config(default_config, dict(import_plan.get("rp_config_draft", {}) or {}))
    manifest_payload = {
        "fixture_id": fixture_id.strip() or _safe_fixture_id(bundle_root.name),
        "site_class": site_class.strip() or "field_official",
        "software": software.strip() or "EddyPro",
        "software_version": software_version.strip(),
        "files": {
            role: str(dict(claim or {}).get("relative_to_bundle", "")).replace("\\", "/")
            for role, claim in files.items()
            if dict(claim or {}).get("relative_to_bundle")
        },
        **({"official_eddypro_run": official_eddypro_run} if official_eddypro_run else {}),
        "official_eddypro_run_checklist": _official_eddypro_run_checklist(official_eddypro_run_summary),
        "normalization_result": normalization_result,
        "official_run_normalization_result": official_run_normalization_result,
        "import_plan": import_plan,
        "rp_config": deepcopy(rp_config) if rp_config is not None else default_config,
        "thresholds": deepcopy(thresholds)
        if thresholds is not None
        else {
            "flux_rel_threshold": 0.10,
            "lag_abs_threshold_s": 0.5,
            "wpl_rel_threshold": 0.20,
            "qc_grade_must_match": False,
        },
        "known_limitations": list(known_limitations or [])
        or [
            "Auto-generated manifest: review inferred file roles before using this fixture for parity claims.",
            "Raw-to-final parity still depends on the normalized reference and QC/unit mapping provenance.",
        ],
        "generated_by": "gas_ec_studio_official_raw_import_wizard",
        "generated_at": datetime.now().isoformat(),
        "inferred_file_roles": sorted(inferred_roles),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(manifest_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    inspection = inspect_official_raw_fixture_bundle(bundle_root, workspace_root=root)
    status = "manifest_ready" if inspection.get("status") == "ready_for_registration" else "manifest_incomplete"
    return {
        "artifact_type": "official_raw_fixture_bundle_manifest_build_v1",
        "status": status,
        "bundle_root": str(bundle_root),
        "manifest_path": str(manifest_path),
        "generated_at": manifest_payload["generated_at"],
        "fixture_id": manifest_payload["fixture_id"],
        "site_class": manifest_payload["site_class"],
        "software": manifest_payload["software"],
        "software_version": manifest_payload["software_version"],
        "inferred_file_roles": sorted(inferred_roles),
        "normalization_result": normalization_result,
        "official_run_normalization_result": official_run_normalization_result,
        "official_eddypro_run": official_eddypro_run_summary,
        "official_eddypro_run_checklist": _official_eddypro_run_checklist(official_eddypro_run_summary),
        "missing_required_files": missing_required,
        "manifest": manifest_payload,
        "inspection": inspection,
        "errors": list(inspection.get("errors", []) or []),
        "truthfulness_note": (
            "The import wizard writes a manifest only. It does not alter raw files or claim numeric parity "
            "until registration and raw-to-final validation pass."
        ),
    }


def _refresh_existing_manifest_official_run_normalization(
    *,
    bundle_root: Path,
    manifest_path: Path,
    root: Path,
) -> dict[str, Any]:
    declared = _read_json(manifest_path)
    if not declared:
        return {
            "status": "invalid_manifest",
            "manifest_updated": False,
            "official_run_normalization_result": {},
            "errors": ["existing manifest could not be read as JSON"],
        }

    role_values = _declared_file_roles(declared)
    inferred_roles = _infer_file_roles(bundle_root)
    for role, value in inferred_roles.items():
        role_values.setdefault(role, value)
    _apply_official_prepare_role_hints(bundle_root, role_values)
    files = {
        role: _file_claim(bundle_root, role, value, root=root)
        for role, value in sorted(role_values.items())
        if role in CANONICAL_FILE_ROLES
    }
    declared_with_sidecar = _declared_manifest_with_discovered_run(bundle_root, declared, files)
    official_run = dict(declared_with_sidecar.get("official_eddypro_run", {}) or declared_with_sidecar.get("eddypro_run", {}) or {})
    fixture_id = str(declared.get("fixture_id") or _safe_fixture_id(bundle_root.name))
    normalization = _ensure_normalized_reference_from_official_run_output(
        bundle_root,
        official_run,
        fixture_id=fixture_id,
        root=root,
    )
    updated = deepcopy(declared)
    changed = False
    if official_run and not isinstance(updated.get("official_eddypro_run"), dict):
        updated["official_eddypro_run"] = official_run
        changed = True
    if str(normalization.get("status", "")) in {"normalized", "already_present"} and normalization.get("reference_json"):
        if dict(updated.get("official_run_normalization_result", {}) or {}) != normalization:
            updated["official_run_normalization_result"] = normalization
            updated["official_run_normalization_refreshed_at"] = datetime.now().isoformat()
            changed = True
    if changed:
        manifest_path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "status": "refreshed" if changed else str(normalization.get("status", "not_available")),
        "manifest_updated": changed,
        "official_run_normalization_result": normalization,
        "errors": list(normalization.get("errors", []) or []),
    }


def build_official_raw_fixture_bundle_manifest_batch(
    bundle_root: str | Path,
    *,
    site_class: str = "",
    software: str = "EddyPro",
    software_version: str = "",
    overwrite: bool = False,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build manifests for every candidate official raw bundle under a tree."""

    root = Path(workspace_root) if workspace_root is not None else Path.cwd()
    search_root = Path(bundle_root)
    generated_at = datetime.now().isoformat()
    candidates = _bundle_candidate_dirs_from_root(search_root)
    builds: list[dict[str, Any]] = []
    errors: list[str] = []
    for candidate in candidates:
        result = build_official_raw_fixture_bundle_manifest(
            candidate,
            site_class=site_class,
            software=software,
            software_version=software_version,
            overwrite=overwrite,
            workspace_root=root,
        )
        builds.append(result)
        errors.extend(str(item) for item in list(result.get("errors", []) or []))
    status_counts = Counter(str(item.get("status", "unknown")) for item in builds)
    ready_statuses = {"manifest_ready", "manifest_exists"}
    ready_count = sum(1 for item in builds if str(item.get("status", "")) in ready_statuses)
    status = "ready" if builds and ready_count == len(builds) and not errors else "needs_attention"
    if not builds:
        status = "no_candidate_bundles"
    discovery = discover_official_raw_fixture_bundles(search_root, workspace_root=root) if builds else {
        "artifact_type": "official_raw_fixture_bundle_discovery_v1",
        "bundle_root": str(search_root),
        "generated_at": generated_at,
        "bundle_count": 0,
        "ready_count": 0,
        "status": "needs_attention",
        "evidence_matrix": {"artifact_type": "official_raw_fixture_evidence_matrix_v1", "row_count": 0, "rows": []},
        "repair_plan": _official_raw_fixture_repair_plan_from_inspections(
            bundle_root=search_root,
            inspections=[],
            generated_at=generated_at,
        ),
        "inspections": [],
        "errors": [],
    }
    return {
        "artifact_type": "official_raw_fixture_bundle_manifest_batch_build_v1",
        "status": status,
        "bundle_root": str(search_root),
        "generated_at": generated_at,
        "candidate_count": len(candidates),
        "build_count": len(builds),
        "ready_count": ready_count,
        "generated_count": int(status_counts.get("manifest_ready", 0)),
        "existing_count": int(status_counts.get("manifest_exists", 0)),
        "incomplete_count": int(status_counts.get("manifest_incomplete", 0)),
        "status_counts": dict(sorted(status_counts.items())),
        "builds": builds,
        "discovery": discovery,
        "repair_plan": dict(discovery.get("repair_plan", {}) or {}),
        "errors": errors,
        "truthfulness_note": (
            "Batch manifest build creates registration metadata and normalized references where possible. "
            "It does not claim numeric EddyPro parity until registered fixtures pass raw-to-final validation."
        ),
    }


def discover_official_raw_fixture_bundles(
    bundle_root: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect every official raw fixture bundle under a directory tree."""

    root = Path(workspace_root) if workspace_root is not None else Path.cwd()
    search_root = Path(bundle_root)
    bundle_dirs = _bundle_dirs_from_root(search_root)
    inspections = [
        inspect_official_raw_fixture_bundle(bundle_dir, workspace_root=root)
        for bundle_dir in bundle_dirs
    ]
    status_counts = Counter(str(item.get("status", "unknown")) for item in inspections)
    matrix = _inspection_evidence_matrix(inspections)
    repair_plan = _official_raw_fixture_repair_plan_from_inspections(
        bundle_root=search_root,
        inspections=inspections,
        generated_at=datetime.now().isoformat(),
    )
    return {
        "artifact_type": "official_raw_fixture_bundle_discovery_v1",
        "bundle_root": str(search_root),
        "generated_at": datetime.now().isoformat(),
        "bundle_count": len(inspections),
        "ready_count": int(status_counts.get("ready_for_registration", 0)),
        "status_counts": dict(sorted(status_counts.items())),
        "status": "ready" if inspections and len(inspections) == int(status_counts.get("ready_for_registration", 0)) else "needs_attention",
        "evidence_matrix": matrix,
        "repair_plan": repair_plan,
        "inspections": inspections,
        "truthfulness_note": (
            "Discovery proves bundle completeness only. Registered bundles must still pass raw-to-final parity "
            "before they support official EddyPro parity claims."
        ),
    }


def build_official_raw_fixture_repair_plan(
    bundle_root: str | Path,
    *,
    workspace_root: str | Path | None = None,
) -> dict[str, Any]:
    """Build a concrete repair checklist for a tree of official raw bundles."""

    discovery = discover_official_raw_fixture_bundles(bundle_root, workspace_root=workspace_root)
    return dict(discovery.get("repair_plan", {}) or {})


def register_official_raw_fixture_bundle(
    *,
    bundle_dir: str | Path,
    pack_path: str | Path,
    output_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    inspection = inspect_official_raw_fixture_bundle(bundle_dir, workspace_root=workspace_root)
    acquisition_validation = _acquisition_validation_from_inspection(inspection)
    if inspection.get("status") != "ready_for_registration":
        missing = ", ".join(str(item) for item in inspection.get("missing_required_files", []))
        errors = ", ".join(str(item) for item in inspection.get("errors", []))
        detail = "; ".join(item for item in (missing, errors) if item)
        raise ValueError(f"Official raw fixture bundle is not ready for registration: {detail}")
    asset = dict(inspection.get("asset_preview", {}) or {})
    pack_file = Path(pack_path)
    pack = json.loads(pack_file.read_text(encoding="utf-8"))
    assets = list(pack.get("assets", []) or [])
    fixture_id = str(asset.get("fixture_id", ""))
    existing_index = next((index for index, item in enumerate(assets) if str(item.get("fixture_id", "")) == fixture_id), None)
    if existing_index is not None and not replace:
        return {
            "artifact_type": "official_raw_fixture_registration_v1",
            "status": "duplicate_fixture_id",
            "fixture_id": fixture_id,
            "pack_path": str(pack_file),
            "output_path": "",
            "asset": asset,
            "acquisition_validation": acquisition_validation,
            "errors": [f"fixture_id already exists: {fixture_id}"],
        }
    if existing_index is None:
        assets.append(asset)
    else:
        assets[int(existing_index)] = asset
    updated = deepcopy(pack)
    updated["assets"] = assets
    target = Path(output_path) if output_path is not None else pack_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "artifact_type": "official_raw_fixture_registration_v1",
        "status": "registered",
        "fixture_id": fixture_id,
        "pack_path": str(pack_file),
        "output_path": str(target),
        "asset": asset,
        "acquisition_validation": acquisition_validation,
        "asset_count": len(assets),
        "errors": [],
    }


def register_official_raw_fixture_bundle_batch(
    *,
    bundle_root: str | Path,
    pack_path: str | Path,
    output_path: str | Path | None = None,
    workspace_root: str | Path | None = None,
    replace: bool = False,
) -> dict[str, Any]:
    """Register all complete official raw fixture bundles discovered under a root."""

    manifest_build = build_official_raw_fixture_bundle_manifest_batch(
        bundle_root,
        overwrite=False,
        workspace_root=workspace_root,
    )
    discovery = discover_official_raw_fixture_bundles(bundle_root, workspace_root=workspace_root)
    pack_file = Path(pack_path)
    pack = json.loads(pack_file.read_text(encoding="utf-8"))
    assets = list(pack.get("assets", []) or [])
    registrations: list[dict[str, Any]] = []
    errors: list[str] = []

    for inspection in list(discovery.get("inspections", []) or []):
        fixture_id = str(inspection.get("fixture_id", ""))
        if inspection.get("status") != "ready_for_registration":
            missing = ", ".join(str(item) for item in inspection.get("missing_required_files", []) or [])
            result = {
                "status": "skipped_incomplete",
                "fixture_id": fixture_id,
                "bundle_root": inspection.get("bundle_root", ""),
                "missing_required_files": list(inspection.get("missing_required_files", []) or []),
                "errors": list(inspection.get("errors", []) or []),
            }
            registrations.append(result)
            errors.append(f"{fixture_id or inspection.get('bundle_root', '')}: incomplete official bundle ({missing or 'unknown missing files'})")
            continue
        asset = dict(inspection.get("asset_preview", {}) or {})
        existing_index = next((index for index, item in enumerate(assets) if str(item.get("fixture_id", "")) == fixture_id), None)
        if existing_index is not None and not replace:
            registrations.append(
                {
                    "status": "duplicate_fixture_id",
                    "fixture_id": fixture_id,
                    "bundle_root": inspection.get("bundle_root", ""),
                    "errors": [f"fixture_id already exists: {fixture_id}"],
                }
            )
            errors.append(f"fixture_id already exists: {fixture_id}")
            continue
        if existing_index is None:
            assets.append(asset)
        else:
            assets[int(existing_index)] = asset
        registrations.append(
            {
                "status": "registered",
                "fixture_id": fixture_id,
                "bundle_root": inspection.get("bundle_root", ""),
                "asset": asset,
                "errors": [],
            }
        )

    updated = deepcopy(pack)
    updated["assets"] = assets
    target = Path(output_path) if output_path is not None else pack_file
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
    registered_count = sum(1 for item in registrations if item.get("status") == "registered")
    status = "registered" if registered_count and not errors else ("partial" if registered_count else "no_registered_bundles")
    return {
        "artifact_type": "official_raw_fixture_batch_registration_v1",
        "status": status,
        "bundle_root": str(bundle_root),
        "pack_path": str(pack_file),
        "output_path": str(target),
        "registered_count": registered_count,
        "skipped_count": len(registrations) - registered_count,
        "asset_count": len(assets),
        "discovery": discovery,
        "manifest_build": manifest_build,
        "evidence_matrix": discovery.get("evidence_matrix", {}),
        "registrations": registrations,
        "errors": errors,
    }


def _find_bundle_manifest(bundle_root: Path) -> Path | None:
    for name in BUNDLE_MANIFEST_NAMES:
        candidate = bundle_root / name
        if candidate.exists() and candidate.is_file():
            return candidate
    return None


def _bundle_dirs_from_root(search_root: Path) -> list[Path]:
    if search_root.is_file() and search_root.name in BUNDLE_MANIFEST_NAMES:
        return [search_root.parent]
    if _find_bundle_manifest(search_root) is not None:
        return [search_root]
    if not search_root.exists() or not search_root.is_dir():
        return [search_root]
    dirs: list[Path] = []
    for manifest_name in BUNDLE_MANIFEST_NAMES:
        dirs.extend(path.parent for path in search_root.rglob(manifest_name) if path.is_file())
    unique: dict[str, Path] = {}
    for bundle_dir in sorted(dirs):
        unique[str(bundle_dir.resolve())] = bundle_dir
    return list(unique.values())


def _bundle_candidate_dirs_from_root(search_root: Path) -> list[Path]:
    if search_root.is_file() and search_root.name in BUNDLE_MANIFEST_NAMES:
        return [search_root.parent]
    if not search_root.exists() or not search_root.is_dir():
        return []
    candidates: dict[str, Path] = {}
    for bundle_dir in _bundle_dirs_from_root(search_root):
        if bundle_dir.exists() and bundle_dir.is_dir():
            candidates[str(bundle_dir.resolve())] = bundle_dir
    output_files = [
        path
        for path in search_root.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".csv", ".txt"}
        and any(stem in path.name.lower() for stem in ("full_output", "full-output", "eddypro_output", "eddypro-output"))
    ]
    for output_file in sorted(output_files):
        candidate = _candidate_bundle_dir_for_output(output_file, search_root)
        if candidate is not None:
            candidates[str(candidate.resolve())] = candidate
    return sorted(candidates.values(), key=lambda item: str(item))


def _candidate_bundle_dir_for_output(output_file: Path, search_root: Path) -> Path | None:
    current = output_file.parent
    search_resolved = search_root.resolve()
    while True:
        roles = _infer_file_roles(current)
        has_output = any(roles.get(role) for role in OUTPUT_ROLE_CHOICES)
        has_raw = any(roles.get(role) for role in RAW_ROLE_CHOICES)
        has_project = any(roles.get(role) for role in PROJECT_ROLE_CHOICES)
        if has_output and has_raw and has_project:
            return current
        if current.resolve() == search_resolved or current.parent == current:
            return None
        try:
            current.parent.resolve().relative_to(search_resolved)
        except ValueError:
            return None
        current = current.parent


def _inspection_evidence_matrix(inspections: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    raw_format_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    site_class_counts: Counter[str] = Counter()
    software_counts: Counter[str] = Counter()
    missing_counts: Counter[str] = Counter()
    official_run_status_counts: Counter[str] = Counter()
    official_run_gate_counts: Counter[str] = Counter()
    for inspection in inspections:
        declared = dict(inspection.get("declared_manifest", {}) or {})
        files = dict(inspection.get("files", {}) or {})
        import_plan = dict(inspection.get("import_plan", {}) or {})
        raw_import_probe = dict(import_plan.get("raw_import_probe", {}) or {})
        official_run = dict(inspection.get("official_eddypro_run", {}) or {})
        raw_format = _raw_format_from_file_claims(files)
        status = str(inspection.get("status", "unknown"))
        site_class = str(declared.get("site_class", "") or "unknown")
        software = str(declared.get("software", "") or "unknown")
        missing = list(inspection.get("missing_required_files", []) or [])
        row = {
            "fixture_id": str(inspection.get("fixture_id", "")),
            "bundle_root": str(inspection.get("bundle_root", "")),
            "status": status,
            "site_class": site_class,
            "software": software,
            "software_version": str(declared.get("software_version", "")),
            "official_eddypro_run_status": str(official_run.get("status", "")),
            "official_eddypro_run_gate_status": str(official_run.get("gate_status", "")),
            "raw_format": raw_format,
            "raw_import_probe_status": str(raw_import_probe.get("status", "")),
            "raw_import_probe_format": str(raw_import_probe.get("format", "")),
            "raw_import_probe_row_count": int(raw_import_probe.get("row_count", 0) or 0),
            "file_roles": list(declared.get("file_roles", []) or sorted(files)),
            "missing_required_files": missing,
            "has_raw_input": any(files.get(role, {}).get("exists", False) for role in RAW_ROLE_CHOICES),
            "has_eddypro_project": any(files.get(role, {}).get("exists", False) for role in PROJECT_ROLE_CHOICES),
            "has_official_output": any(files.get(role, {}).get("exists", False) for role in OUTPUT_ROLE_CHOICES),
            "has_normalized_reference": any(files.get(role, {}).get("exists", False) for role in REFERENCE_ROLE_CHOICES),
            "has_provenance": any(files.get(role, {}).get("exists", False) for role in PROVENANCE_ROLE_CHOICES),
        }
        rows.append(row)
        raw_format_counts[raw_format] += 1
        status_counts[status] += 1
        site_class_counts[site_class] += 1
        software_counts[software] += 1
        official_run_status_counts[str(official_run.get("status", "not_available") or "not_available")] += 1
        official_run_gate_counts[str(official_run.get("gate_status", "blocked") or "blocked")] += 1
        for item in missing:
            missing_counts[str(item)] += 1
    return {
        "artifact_type": "official_raw_fixture_evidence_matrix_v1",
        "row_count": len(rows),
        "ready_count": int(status_counts.get("ready_for_registration", 0)),
        "raw_format_counts": dict(sorted(raw_format_counts.items())),
        "status_counts": dict(sorted(status_counts.items())),
        "site_class_counts": dict(sorted(site_class_counts.items())),
        "software_counts": dict(sorted(software_counts.items())),
        "official_eddypro_run_status_counts": dict(sorted(official_run_status_counts.items())),
        "official_eddypro_run_gate_counts": dict(sorted(official_run_gate_counts.items())),
        "missing_required_counts": dict(sorted(missing_counts.items())),
        "rows": rows,
    }


def _official_raw_fixture_repair_plan_from_inspections(
    *,
    bundle_root: Path,
    inspections: list[dict[str, Any]],
    generated_at: str,
) -> dict[str, Any]:
    repair_items = [_official_raw_repair_item(inspection) for inspection in inspections]
    open_items = [item for item in repair_items if item.get("repair_status") != "ready_for_registration"]
    missing_counts: Counter[str] = Counter()
    for item in open_items:
        for requirement in list(item.get("missing_requirements", []) or []):
            missing_counts[str(requirement)] += 1
    status_counts = Counter(str(item.get("repair_status", "unknown")) for item in repair_items)
    official_run_gate_counts = Counter(str(item.get("official_eddypro_run_gate_status", "blocked")) for item in repair_items)
    return {
        "artifact_type": "official_raw_fixture_repair_plan_v1",
        "generated_at": generated_at,
        "bundle_root": str(bundle_root),
        "status": "complete" if repair_items and not open_items else ("no_bundles" if not repair_items else "needs_repair"),
        "bundle_count": len(repair_items),
        "ready_for_registration_count": int(status_counts.get("ready_for_registration", 0)),
        "repair_item_count": len(open_items),
        "official_eddypro_run_pass_count": int(official_run_gate_counts.get("pass", 0)),
        "official_eddypro_run_blocked_count": len(repair_items) - int(official_run_gate_counts.get("pass", 0)),
        "missing_requirement_counts": dict(sorted(missing_counts.items())),
        "accepted_sidecar_filenames": list(OFFICIAL_EDDYPRO_RUN_MANIFEST_NAMES),
        "repair_items": open_items,
        "ready_items": [item for item in repair_items if item.get("repair_status") == "ready_for_registration"],
        "truthfulness_note": (
            "This repair plan is an operator checklist. It does not mark EddyPro parity complete; "
            "registered bundles still need raw-to-final parity and evidence-pack acceptance."
        ),
    }


def _official_raw_repair_item(inspection: dict[str, Any]) -> dict[str, Any]:
    acquisition = dict(inspection.get("acquisition_validation", {}) or {})
    checklist = dict(inspection.get("official_eddypro_run_checklist", {}) or {})
    official_run = dict(inspection.get("official_eddypro_run", {}) or {})
    file_missing = list(inspection.get("missing_required_files", []) or [])
    run_missing = list(checklist.get("missing_requirements", official_run.get("missing_requirements", [])) or [])
    missing = _dedupe([*file_missing, *run_missing])
    repair_status = "ready_for_registration" if not missing and inspection.get("status") == "ready_for_registration" else "needs_operator_evidence"
    if file_missing:
        repair_status = "missing_required_files"
    return {
        "artifact_type": "official_raw_fixture_repair_item_v1",
        "fixture_id": str(inspection.get("fixture_id", "")),
        "bundle_root": str(inspection.get("bundle_root", "")),
        "inspection_status": str(inspection.get("status", "")),
        "repair_status": repair_status,
        "priority": "P0" if missing else "closed",
        "missing_required_files": file_missing,
        "official_eddypro_run_status": str(official_run.get("status", "not_available")),
        "official_eddypro_run_gate_status": str(official_run.get("gate_status", "blocked")),
        "official_eddypro_run_missing_requirements": run_missing,
        "missing_requirements": missing,
        "accepted_sidecar_filenames": list(checklist.get("accepted_sidecar_filenames", OFFICIAL_EDDYPRO_RUN_MANIFEST_NAMES) or []),
        "sidecar_template": dict(checklist.get("template", {}) or {}),
        "acquisition_missing_requirements": list(acquisition.get("missing_requirements", []) or []),
        "next_actions": _official_raw_repair_next_actions(file_missing=file_missing, run_missing=run_missing),
        "can_register": repair_status == "ready_for_registration",
        "can_close_release_gate_without_parity": False,
    }


def _official_raw_repair_next_actions(*, file_missing: list[Any], run_missing: list[Any]) -> list[str]:
    actions: list[str] = []
    if file_missing:
        actions.append(f"Add missing required bundle files/groups: {', '.join(str(item) for item in file_missing)}.")
    if run_missing:
        actions.append(
            "Add official EddyPro executable run sidecar "
            f"({', '.join(OFFICIAL_EDDYPRO_RUN_MANIFEST_NAMES[:2])}) with: {', '.join(str(item) for item in run_missing)}."
        )
    if not actions:
        actions.append("Register the fixture, run raw-to-final parity, then run evidence-pack acceptance.")
    return actions


def _dedupe(items: list[Any]) -> list[str]:
    return list(dict.fromkeys(str(item) for item in items if str(item).strip()))


def _raw_format_from_file_claims(files: dict[str, dict[str, Any]]) -> str:
    raw_role = next((role for role in RAW_ROLE_CHOICES if files.get(role, {}).get("exists", False)), "")
    if not raw_role:
        return "missing"
    path = Path(str(files.get(raw_role, {}).get("path", "")))
    suffix = path.suffix.lower().lstrip(".")
    if suffix:
        return suffix
    if raw_role != "raw_file":
        return raw_role.replace("_file", "")
    return "raw"


def _declared_file_roles(declared: dict[str, Any]) -> dict[str, Any]:
    files = declared.get("files", {})
    roles: dict[str, Any] = {}
    if isinstance(files, dict):
        roles.update({str(key): value for key, value in files.items() if value not in (None, "")})
    for role in CANONICAL_FILE_ROLES:
        if declared.get(role) not in (None, ""):
            roles[role] = declared[role]
    return roles


def _infer_file_roles(bundle_root: Path) -> dict[str, str]:
    if not bundle_root.exists() or not bundle_root.is_dir():
        return {}
    roles: dict[str, str] = {}
    candidates = [path for path in bundle_root.rglob("*") if path.is_file()]
    by_suffix = {path.suffix.lower(): path for path in sorted(candidates)}
    if ".ghg" in by_suffix:
        roles["raw_file"] = str(by_suffix[".ghg"].relative_to(bundle_root))
    elif ".tob1" in by_suffix:
        roles["raw_file"] = str(by_suffix[".tob1"].relative_to(bundle_root))
    elif ".slt" in by_suffix:
        roles["raw_file"] = str(by_suffix[".slt"].relative_to(bundle_root))
    else:
        raw = _first_matching(candidates, ("raw", "hf", "high_frequency"), (".csv", ".txt", ".dat", ".bin"), root=bundle_root)
        if raw is not None:
            roles["raw_file"] = str(raw.relative_to(bundle_root))
    metadata = _first_matching(candidates, ("metadata", "meta"), (".json",), root=bundle_root)
    if metadata is not None:
        roles["metadata_json"] = str(metadata.relative_to(bundle_root))
    project = _first_matching(candidates, ("eddypro", "project", "settings"), (".eddypro", ".eddyproj", ".proj", ".metadata", ".txt", ".json"), root=bundle_root)
    if project is not None and project.name not in BUNDLE_MANIFEST_NAMES:
        roles["eddypro_project_file"] = str(project.relative_to(bundle_root))
    output = _first_matching(candidates, ("full_output", "full-output", "eddypro_output", "eddypro-output"), (".csv", ".txt"), root=bundle_root)
    if output is not None:
        roles["official_full_output"] = str(output.relative_to(bundle_root))
    reference = _first_matching(candidates, ("reference",), (".json",), root=bundle_root) or _first_matching(
        [path for path in candidates if "provenance" not in path.name.lower()],
        ("normalized",),
        (".json",),
        root=bundle_root,
    )
    if reference is not None and reference.name not in BUNDLE_MANIFEST_NAMES:
        roles["reference_json"] = str(reference.relative_to(bundle_root))
    provenance = _first_matching(candidates, ("provenance",), (".json",), root=bundle_root)
    if provenance is not None:
        roles["provenance_json"] = str(provenance.relative_to(bundle_root))
    return roles


def _apply_official_prepare_role_hints(bundle_root: Path, roles: dict[str, str]) -> None:
    preparation = _discover_official_eddypro_project_prepare(bundle_root)
    if str(preparation.get("status", "")) != "prepared":
        return
    copied_raw_files = list(preparation.get("copied_raw_files", []) or [])
    for copied in copied_raw_files:
        if not isinstance(copied, dict):
            continue
        raw_rel = str(copied.get("source_relative_to_bundle", "") or "").replace("\\", "/")
        if raw_rel and (bundle_root / raw_rel).is_file():
            roles["raw_file"] = raw_rel
            break
    project_rel = str(preparation.get("source_project_relative_to_bundle", "") or "").replace("\\", "/")
    if project_rel and (bundle_root / project_rel).is_file():
        roles["eddypro_project_file"] = project_rel


def _ensure_normalized_reference_from_full_output(
    bundle_root: Path,
    roles: dict[str, str],
    *,
    fixture_id: str,
    root: Path,
) -> dict[str, Any]:
    """Generate normalized reference/provenance only when an official output is present.

    The original EddyPro Full_Output remains untouched; generated artifacts land
    under normalized/ so the manifest can preserve both source and normalized evidence.
    """

    result: dict[str, Any] = {
        "artifact_type": "official_raw_full_output_normalization_v1",
        "status": "already_present",
        "source_file": "",
        "reference_json": roles.get("reference_json", ""),
        "provenance_json": roles.get("provenance_json", ""),
        "generated_files": [],
        "errors": [],
    }
    reference_path = _role_path(bundle_root, roles.get("reference_json", ""))
    provenance_path = _role_path(bundle_root, roles.get("provenance_json", ""))
    reference_exists = reference_path is not None and reference_path.exists() and reference_path.is_file()
    provenance_exists = provenance_path is not None and provenance_path.exists() and provenance_path.is_file()
    if reference_exists and provenance_exists:
        return result

    output_role = next(
        (
            role
            for role in OUTPUT_ROLE_CHOICES
            if (candidate := _role_path(bundle_root, roles.get(role, ""))) is not None
            and candidate.exists()
            and candidate.is_file()
        ),
        "",
    )
    output_path = _role_path(bundle_root, roles.get(output_role, "")) if output_role else None
    if output_path is None:
        result["status"] = "missing_official_output"
        return result
    result["source_file"] = str(output_path)

    if reference_exists and not provenance_exists:
        result["status"] = "reference_present_provenance_missing"
        result["errors"] = [
            "Existing normalized reference was preserved; provenance must be supplied or regenerated from the original normalization command."
        ]
        return result

    normalized_dir = bundle_root / "normalized"
    target_reference = reference_path if reference_path is not None else normalized_dir / "reference.json"
    target_provenance = provenance_path if provenance_path is not None else normalized_dir / "provenance.json"
    metadata_sources = [
        str(path)
        for role in ("metadata_json", *PROJECT_ROLE_CHOICES)
        if (path := _role_path(bundle_root, roles.get(role, ""))) is not None and path.exists() and path.is_file()
    ]
    command = (
        "gas-ec-headless --build-official-raw-bundle-manifest "
        f'"{_workspace_or_absolute_path(bundle_root, root)}" --bundle-fixture-id "{fixture_id}"'
    )
    try:
        normalization = write_eddypro_full_output_reference(
            output_path,
            reference_path=target_reference,
            provenance_path=target_provenance,
            reference_id=f"{fixture_id}_reference",
            normalization_command=command,
            metadata_source_files=metadata_sources,
        )
    except Exception as exc:
        result["status"] = "normalization_error"
        result["errors"] = [str(exc)]
        return result

    roles["reference_json"] = str(target_reference.relative_to(bundle_root)).replace("\\", "/")
    roles["provenance_json"] = str(target_provenance.relative_to(bundle_root)).replace("\\", "/")
    result.update(
        {
            "status": normalization.get("status", "normalized"),
            "reference_json": roles["reference_json"],
            "provenance_json": roles["provenance_json"],
            "window_count": int(normalization.get("window_count", 0) or 0),
            "generated_files": [roles["reference_json"], roles["provenance_json"]],
            "field_mapping": dict(normalization.get("field_mapping", {}) or {}),
            "unmapped_columns": list(normalization.get("unmapped_columns", []) or []),
        }
    )
    return result


def _ensure_normalized_reference_from_official_run_output(
    bundle_root: Path,
    official_run: dict[str, Any],
    *,
    fixture_id: str,
    root: Path,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "artifact_type": "official_eddypro_run_output_normalization_v1",
        "status": "not_available",
        "source_file": "",
        "reference_json": "normalized/official_eddypro_run_reference.json",
        "provenance_json": "normalized/official_eddypro_run_provenance.json",
        "generated_files": [],
        "errors": [],
        "truthfulness_note": (
            "This normalization is derived from the operator-captured official EddyPro executable-run output. "
            "It is stored separately from the primary reference so embedded/original Full_Output evidence remains preserved."
        ),
    }
    run = dict(official_run or {})
    if not run:
        return result
    output_path = _first_existing_official_run_output_path(bundle_root, run)
    if output_path is None:
        result["status"] = "missing_official_run_output"
        result["errors"] = ["official_eddypro_run output_files did not contain an existing Full_Output file."]
        return result
    result["source_file"] = str(output_path)

    normalized_dir = bundle_root / "normalized"
    target_reference = normalized_dir / "official_eddypro_run_reference.json"
    target_provenance = normalized_dir / "official_eddypro_run_provenance.json"
    if target_reference.exists() and target_reference.is_file() and target_provenance.exists() and target_provenance.is_file():
        result.update(
            {
                "status": "already_present",
                "generated_files": [],
            }
        )
        return result

    metadata_sources = [
        str(path)
        for path in _official_run_metadata_source_paths(bundle_root)
        if path.exists() and path.is_file()
    ]
    command = (
        "gas-ec-headless --build-official-raw-bundle-manifest "
        f'"{_workspace_or_absolute_path(bundle_root, root)}" --bundle-fixture-id "{fixture_id}" '
        "--normalize-official-eddypro-run-output"
    )
    try:
        normalization = write_eddypro_full_output_reference(
            output_path,
            reference_path=target_reference,
            provenance_path=target_provenance,
            reference_id=f"{fixture_id}_official_eddypro_run_reference",
            normalization_command=command,
            metadata_source_files=metadata_sources,
        )
    except Exception as exc:
        result["status"] = "normalization_error"
        result["errors"] = [str(exc)]
        return result

    result.update(
        {
            "status": normalization.get("status", "normalized"),
            "reference_json": str(target_reference.relative_to(bundle_root)).replace("\\", "/"),
            "provenance_json": str(target_provenance.relative_to(bundle_root)).replace("\\", "/"),
            "window_count": int(normalization.get("window_count", 0) or 0),
            "generated_files": [
                str(target_reference.relative_to(bundle_root)).replace("\\", "/"),
                str(target_provenance.relative_to(bundle_root)).replace("\\", "/"),
            ],
            "field_mapping": dict(normalization.get("field_mapping", {}) or {}),
            "unmapped_columns": list(normalization.get("unmapped_columns", []) or []),
            "official_eddypro_run_gate_status": str(dict(run.get("validation", {}) or {}).get("gate_status", "")),
        }
    )
    return result


def _first_existing_official_run_output_path(bundle_root: Path, official_run: dict[str, Any]) -> Path | None:
    values = [str(item).replace("\\", "/") for item in list(official_run.get("output_files", []) or []) if str(item).strip()]
    if not values:
        values = [
            str(item.get("relative_to_bundle", item.get("path", ""))).replace("\\", "/")
            for item in list(official_run.get("output_file_hashes", []) or [])
            if isinstance(item, dict) and str(item.get("relative_to_bundle", item.get("path", ""))).strip()
        ]
    for value in values:
        matches = _official_run_output_file_values(bundle_root, [value], expand_patterns=True)
        for match in matches:
            path = _resolve_bundle_path(str(match), bundle_root)
            if path is not None and path.exists() and path.is_file() and "full_output" in path.name.lower():
                return path
    return None


def _official_run_metadata_source_paths(bundle_root: Path) -> list[Path]:
    roles = _infer_file_roles(bundle_root)
    paths: list[Path] = []
    for role in ("metadata_json", *PROJECT_ROLE_CHOICES):
        path = _role_path(bundle_root, roles.get(role, ""))
        if path is not None:
            paths.append(path)
    return paths


def _role_path(bundle_root: Path, value: Any) -> Path | None:
    if value in (None, ""):
        return None
    path = Path(str(value))
    return path if path.is_absolute() else bundle_root / path


def _workspace_or_absolute_path(path: Path, root: Path) -> str:
    return str(path.relative_to(root)) if _is_relative_to(path, root) else str(path)


def _first_matching(paths: list[Path], stems: tuple[str, ...], suffixes: tuple[str, ...], *, root: Path | None = None) -> Path | None:
    for path in sorted(paths):
        try:
            candidate = path.relative_to(root) if root is not None else path.name
        except ValueError:
            candidate = path.name
        haystack = "/".join(part.lower() for part in Path(candidate).parts)
        if path.suffix.lower() in suffixes and any(stem in haystack for stem in stems):
            return path
    return None


def _file_claim(bundle_root: Path, role: str, value: Any, *, root: Path) -> dict[str, Any]:
    raw_path = Path(str(value))
    path = raw_path if raw_path.is_absolute() else bundle_root / raw_path
    exists = path.exists() and path.is_file()
    return {
        "role": role,
        "path": str(path),
        "relative_to_bundle": str(path.relative_to(bundle_root)) if exists and _is_relative_to(path, bundle_root) else str(value),
        "relative_to_workspace": str(path.relative_to(root)) if exists and _is_relative_to(path, root) else str(path),
        "exists": exists,
        "size_bytes": path.stat().st_size if exists else 0,
        "sha256": _sha256(path) if exists else "",
    }


def _missing_required_groups(files: dict[str, dict[str, Any]]) -> list[str]:
    checks = {
        "high_frequency_raw_input": RAW_ROLE_CHOICES,
        "eddypro_project_or_settings_file": PROJECT_ROLE_CHOICES,
        "official_eddypro_full_output": OUTPUT_ROLE_CHOICES,
        "normalized_reference_json": REFERENCE_ROLE_CHOICES,
        "normalization_provenance": PROVENANCE_ROLE_CHOICES,
    }
    missing: list[str] = []
    for group, choices in checks.items():
        if not any(files.get(role, {}).get("exists", False) for role in choices):
            missing.append(group)
    return missing


def _asset_from_claims(
    *,
    fixture_id: str,
    declared: dict[str, Any],
    files: dict[str, dict[str, Any]],
    root: Path,
) -> dict[str, Any]:
    raw_role = _first_existing_role(files, RAW_ROLE_CHOICES)
    output_role = _first_existing_role(files, OUTPUT_ROLE_CHOICES)
    project_role = _first_existing_role(files, PROJECT_ROLE_CHOICES)
    import_plan = _asset_import_plan_from_claims(declared=declared, files=files, root=root)
    rp_config = _merge_config(
        dict(declared.get("rp_config", {}) or {}),
        dict(import_plan.get("rp_config_draft", {}) or {}),
    )
    asset: dict[str, Any] = {
        "fixture_id": fixture_id,
        "tier": "raw_to_final_parity",
        "site_class": str(declared.get("site_class", "field_official")),
        "software": str(declared.get("software", "EddyPro")),
        "software_version": str(declared.get("software_version", "")),
        "official_eddypro_output": True,
        "raw_file": _workspace_path(files[raw_role], root) if raw_role else "",
        "metadata_json": _workspace_path(files["metadata_json"], root) if "metadata_json" in files else "",
        "reference_json": _workspace_path(files["reference_json"], root) if "reference_json" in files else "",
        "provenance_json": _workspace_path(files["provenance_json"], root) if "provenance_json" in files else "",
        "import_plan": import_plan,
        "rp_config": rp_config,
        "thresholds": dict(declared.get("thresholds", {}) or {}),
        "official_eddypro_run": _official_eddypro_run_summary(declared, files),
        "official_run_normalization_result": dict(declared.get("official_run_normalization_result", {}) or {}),
        "expected_sha256": {},
        "known_limitations": list(declared.get("known_limitations", []) or []),
    }
    if output_role:
        asset["official_full_output"] = _workspace_path(files[output_role], root)
    if project_role:
        asset["eddypro_project_file"] = _workspace_path(files[project_role], root)
    if not asset["known_limitations"]:
        asset["known_limitations"] = [
            "Registered official bundle requires raw-to-final harness validation before parity claims.",
            "Normalization provenance must be reviewed for QC flag and unit mapping assumptions.",
        ]
    for role, claim in files.items():
        if claim.get("sha256"):
            asset["expected_sha256"][role] = claim["sha256"]
    return asset


def _asset_import_plan_from_claims(
    *,
    declared: dict[str, Any],
    files: dict[str, dict[str, Any]],
    root: Path,
) -> dict[str, Any]:
    generated = _build_import_plan(files=files, declared=declared, root=root)
    declared_plan = deepcopy(declared.get("import_plan") or {})
    if not declared_plan:
        return generated
    declared_status = str(declared_plan.get("status", "") or "")
    generated_status = str(generated.get("status", "") or "")
    if generated_status == "draft_ready" and declared_status in {"", "raw_only_candidate", "missing_raw_input", "needs_review"}:
        return generated
    unresolved = " ".join(str(item) for item in list(declared_plan.get("unresolved", []) or [])).lower()
    if "not present" in unresolved and generated_status == "draft_ready":
        return generated
    return declared_plan


def _first_existing_role(files: dict[str, dict[str, Any]], roles: tuple[str, ...]) -> str:
    return next((role for role in roles if files.get(role, {}).get("exists", False)), "")


def _bundle_root_from_file_claims(files: dict[str, dict[str, Any]]) -> Path | None:
    parents: list[str] = []
    for claim in files.values():
        if not dict(claim or {}).get("exists"):
            continue
        path = Path(str(dict(claim or {}).get("path", "")))
        if path.exists():
            parents.append(str(path.resolve().parent))
    if not parents:
        return None
    try:
        return Path(os.path.commonpath(parents))
    except ValueError:
        return None


def _default_rp_config_from_file_claims(files: dict[str, dict[str, Any]]) -> dict[str, Any]:
    metadata_payload: dict[str, Any] = {}
    reference_payload: dict[str, Any] = {}
    metadata_path = Path(str(dict(files.get("metadata_json", {}) or {}).get("path", "")))
    reference_path = Path(str(dict(files.get("reference_json", {}) or {}).get("path", "")))
    if metadata_path.exists() and metadata_path.is_file():
        try:
            metadata_payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            metadata_payload = {}
    if reference_path.exists() and reference_path.is_file():
        try:
            reference_payload = json.loads(reference_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            reference_payload = {}
    raw_settings = dict(metadata_payload.get("raw_file_settings", {}) or {})
    processing_settings = dict(reference_payload.get("processing_settings", {}) or {})
    sample_hz = float(raw_settings.get("sample_hz", 10.0) or 10.0)
    block_minutes = float(
        processing_settings.get("averaging_period_min")
        or processing_settings.get("averaging_period_minutes")
        or _reference_window_minutes(reference_payload)
        or 30.0
    )
    rotation_mode = str(processing_settings.get("rotation_mode", "double") or "double")
    density_correction = str(
        processing_settings.get("density_correction")
        or processing_settings.get("density_correction_mode")
        or "wpl"
    )
    lag_strategy = str(processing_settings.get("lag_determination") or processing_settings.get("lag_strategy") or "covariance_max")
    detrend_mode = str(processing_settings.get("detrend_method") or processing_settings.get("detrend_mode") or "block_mean")
    return {
        "sample_hz": sample_hz,
        "block_minutes": block_minutes,
        "steps": {"window_sampling": {"sample_hz": sample_hz, "window_minutes": block_minutes}},
        "rotation_mode": rotation_mode,
        "detrend_mode": detrend_mode,
        "density_correction_mode": density_correction,
        "lag_phase": {
            "strategy": lag_strategy,
            "expected_lag_s": float(processing_settings.get("expected_lag_s", 0.0) or 0.0),
            "search_window_s": float(processing_settings.get("search_window_s", 4.0) or 4.0),
        },
    }


def _build_import_plan(*, files: dict[str, dict[str, Any]], declared: dict[str, Any], root: Path) -> dict[str, Any]:
    raw_role = _first_existing_role(files, RAW_ROLE_CHOICES)
    project_role = _first_existing_role(files, PROJECT_ROLE_CHOICES)
    reference_role = _first_existing_role(files, REFERENCE_ROLE_CHOICES)
    output_role = _first_existing_role(files, OUTPUT_ROLE_CHOICES)
    raw_claim = dict(files.get(raw_role, {}) or {}) if raw_role else {}
    raw_path = Path(str(raw_claim.get("path", "")))
    project_claim = dict(files.get(project_role, {}) or {}) if project_role else {}
    project_path = Path(str(project_claim.get("path", "")))
    settings = _parse_eddypro_settings(project_path) if project_path.exists() else {}
    reference_path = Path(str(files.get(reference_role, {}).get("path", ""))) if reference_role else Path("")
    output_path = Path(str(files.get(output_role, {}).get("path", ""))) if output_role else Path("")
    raw_format = _raw_format_from_file_claims(files)
    base_rp_config = _default_rp_config_from_file_claims(files)
    raw_inference = _infer_raw_import_settings(raw_path=raw_path, raw_format=raw_format, settings=settings)
    start_time = (
        _first_setting(settings, ("start_time", "start_datetime", "file_start_time", "raw_start_time"))
        or _infer_reference_start_time(reference_path)
        or _infer_full_output_start_time(output_path)
    )
    if start_time:
        raw_inference.setdefault("extra", {})["start_time"] = start_time
    bundle_root = _bundle_root_from_file_claims(files)
    processing_config = _processing_config_from_settings(settings, bundle_root=bundle_root)
    sample_hz = _optional_float(
        _first_setting(settings, ("sample_hz", "sampling_rate", "sample_frequency", "acquisition_frequency", "frequency"))
    )
    if sample_hz is None:
        sample_hz = _optional_float(base_rp_config.get("sample_hz"))
    if sample_hz is None:
        sample_hz = 10.0
    block_minutes = _optional_float(
        _first_setting(settings, ("block_minutes", "averaging_period", "averaging_period_min", "averaging_interval", "flux_averaging_interval"))
    )
    if block_minutes is None:
        block_minutes = _optional_float(base_rp_config.get("block_minutes"))
    if block_minutes is None:
        block_minutes = _reference_window_minutes(_read_json(reference_path)) if reference_path.exists() else None
    if block_minutes is None:
        block_minutes = 30.0
    metadata_draft = _merge_config(
        {
            "project": {"code": str(declared.get("fixture_id", "") or raw_path.stem or "official_raw_fixture")},
            "site": {"station_code": str(declared.get("site_class", "") or "field_official")},
            "raw_file_description": {
                "source_name": raw_path.name if raw_path.name else "",
                "source_type": raw_inference.get("source_type", raw_format),
                "column_mappings": _column_mappings_from_columns(raw_inference.get("columns", [])),
            },
            "raw_file_settings": {
                "sample_hz": float(sample_hz),
                "delimiter": "," if raw_format not in {"tsv"} else "\t",
                "header_rows": int(raw_inference.get("header_rows", 0) or 0),
                "extra": raw_inference.get("extra", {}),
            },
        },
        _metadata_draft_from_settings(settings, bundle_root=bundle_root),
    )
    rp_config_draft = _merge_config(
        _merge_config(
            base_rp_config,
            {
                "sample_hz": float(sample_hz),
                "block_minutes": float(block_minutes),
                "steps": {"window_sampling": {"sample_hz": float(sample_hz), "window_minutes": float(block_minutes)}},
                "metadata_bundle": metadata_draft,
            },
        ),
        processing_config,
    )
    raw_import_probe = _raw_import_probe(raw_path=raw_path, metadata_draft=metadata_draft)
    unresolved = []
    if raw_format in {"tob1", "slt", "bin", "raw", "native_binary_file"} and not raw_inference.get("columns"):
        unresolved.append("raw column mapping requires review; no columns were inferred from raw/project files")
    if not start_time and raw_format in {"tob1", "slt", "bin", "raw"}:
        unresolved.append("native raw start_time was not inferred; provide raw_file_settings.extra.start_time before processing")
    status = "draft_ready" if raw_claim.get("exists") else "missing_raw_input"
    if unresolved:
        status = "needs_review"
    return {
        "artifact_type": "official_raw_import_plan_v1",
        "status": status,
        "raw_input": {
            "role": raw_role,
            "path": _workspace_path(raw_claim, root) if raw_claim else "",
            "format": raw_format,
            "sha256": raw_claim.get("sha256", ""),
        },
        "metadata_draft": metadata_draft,
        "rp_config_draft": rp_config_draft,
        "raw_import_probe": raw_import_probe,
        "inference_sources": _import_plan_sources(
            raw_claim=raw_claim,
            project_claim=project_claim,
            reference_path=reference_path,
            output_path=output_path,
            settings=settings,
            raw_inference=raw_inference,
            processing_config=processing_config,
            raw_import_probe=raw_import_probe,
        ),
        "unresolved": unresolved,
        "truthfulness_note": (
            "This import plan is an auditable draft inferred from bundle files. Operators must review units, "
            "column mappings, and timing before using it for official EddyPro parity claims."
        ),
    }


def _infer_raw_import_settings(*, raw_path: Path, raw_format: str, settings: dict[str, str]) -> dict[str, Any]:
    columns = _columns_from_settings(settings)
    extra: dict[str, Any] = {}
    header_rows = 0
    source_type = raw_format
    if raw_format == "tob1":
        header = _inspect_tob1_header(raw_path) if raw_path.exists() else {}
        header_columns = list(header.get("columns", []) or [])
        if header_columns:
            columns = header_columns
        tob1_format = str(_first_setting(settings, ("tob1_format", "file_tob1_format")) or header.get("tob1_format", "")).strip().lower()
        if tob1_format:
            extra["tob1_format"] = tob1_format.upper()
            extra["native_format"] = "tob1_fp2" if tob1_format == "fp2" else "tob1_ieee4"
        else:
            extra["native_format"] = "tob1"
        header_rows = int(_optional_float(_first_setting(settings, ("header_rows", "file_header_rows"))) or header.get("header_rows", 0) or 0)
        if columns:
            extra["columns"] = columns
        if header_rows:
            extra["header_rows"] = header_rows
        source_type = "tob1"
    elif raw_format == "slt":
        slt_variant = str(_first_setting(settings, ("slt_variant", "slt_format", "file_slt_format")) or "").strip().lower()
        native_format = "slt_eddysoft" if "eddy" in slt_variant else "slt_edisol"
        extra["native_format"] = native_format
        if columns:
            extra["columns"] = columns
        header_rows = int(_optional_float(_first_setting(settings, ("header_rows", "file_header_rows"))) or 0)
        source_type = native_format
    elif raw_format in {"bin", "raw"}:
        extra["native_format"] = str(_first_setting(settings, ("native_format", "binary_format")) or "binary").strip().lower()
        data_type = _first_setting(settings, ("data_type", "binary_data_type", "binary_nbytes"))
        if data_type:
            extra["data_type"] = _data_type_from_setting(data_type)
        if columns:
            extra["columns"] = columns
        header_rows = int(_optional_float(_first_setting(settings, ("header_rows", "binary_hnlines", "binary_header_rows"))) or 0)
        if header_rows:
            extra["header_rows"] = header_rows
        source_type = "binary"
    elif raw_format in {"csv", "txt", "dat", "tsv"}:
        header_rows = int(_optional_float(_first_setting(settings, ("header_rows", "file_header_rows"))) or 1)
        if columns:
            extra["columns"] = columns
    return {"source_type": source_type, "columns": columns, "header_rows": header_rows, "extra": extra}


def _raw_import_probe(*, raw_path: Path, metadata_draft: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact_type": "official_raw_import_probe_v1",
        "status": "missing_raw_input",
        "path": str(raw_path),
        "format": raw_path.suffix.lower().lstrip("."),
        "native": False,
        "row_count": 0,
        "time_start": "",
        "time_end": "",
        "import_summary": {},
        "errors": [],
        "truthfulness_note": (
            "This probe verifies that the inferred metadata can decode the raw input. "
            "It is not an EddyPro numeric parity result."
        ),
    }
    if not raw_path.exists() or not raw_path.is_file():
        return payload
    try:
        metadata = MetadataBundle.from_dict(metadata_draft)
    except Exception as exc:
        payload.update({"status": "metadata_error", "errors": [str(exc)]})
        return payload
    try:
        if raw_path.suffix.lower() == ".ghg":
            ghg_manifest = inspect_ghg_bundle(raw_path)
            rows = load_ghg_normalized_frames(raw_path)
            import_summary = {
                "format": "ghg",
                "native": False,
                "raw_data_member_count": len(ghg_manifest.raw_data_members),
                "status_member_count": len(ghg_manifest.status_members),
                "status_members": list(ghg_manifest.status_members),
                "has_li7700_status": bool(ghg_manifest.has_li7700_status),
            }
        elif can_load_raw_native(raw_path, metadata):
            rows = load_raw_native_frames(raw_path, metadata=metadata)
            import_summary = _row_import_summary(rows)
        elif can_load_raw_text(raw_path):
            rows = load_raw_text_frames(raw_path, metadata=metadata)
            import_summary = _row_import_summary(rows) or {"format": raw_path.suffix.lower().lstrip(".") or "text", "native": False}
        else:
            payload.update({"status": "unsupported_raw_format", "errors": [f"unsupported raw input format: {raw_path.suffix}"]})
            return payload
    except Exception as exc:
        payload.update({"status": "probe_error", "errors": [str(exc)]})
        return payload
    payload.update(
        {
            "status": "decoded" if rows else "empty",
            "native": bool(import_summary.get("native", False)),
            "format": str(import_summary.get("format") or payload["format"]),
            "row_count": len(rows),
            "time_start": rows[0].timestamp.isoformat() if rows else "",
            "time_end": rows[-1].timestamp.isoformat() if rows else "",
            "import_summary": import_summary,
            "sample_fields": _sample_frame_fields(rows[0]) if rows else {},
        }
    )
    return payload


def _row_import_summary(rows: list[Any]) -> dict[str, Any]:
    if not rows:
        return {}
    first_payload = _json_payload(str(getattr(rows[0], "raw_text", "") or ""))
    native = dict(first_payload.get("raw_native_import", {}) or {})
    if native:
        return {
            "native": True,
            "format": native.get("format", ""),
            "record_count": native.get("record_count", 0),
            "decoded_record_count": native.get("decoded_record_count", 0),
            "columns": list(native.get("columns", []) or []),
            "column_source": native.get("column_source", ""),
            "data_type": native.get("data_type", ""),
            "column_types": list(native.get("column_types", []) or []),
            "leading_ulong_columns": list(native.get("leading_ulong_columns", []) or []),
            "header_rows": native.get("header_rows", 0),
            "header_row_source": native.get("header_row_source", ""),
            "header_detection": dict(native.get("header_detection", {}) or {}),
            "source_reference": dict(native.get("source_reference", {}) or {}),
            "limitations": list(native.get("limitations", []) or []),
        }
    ygas = dict(first_payload.get("ygas_protocol_import", {}) or {})
    if ygas:
        return {
            "native": False,
            "format": ygas.get("format", "ygas_protocol"),
            "source_reference": dict(ygas.get("source_reference", {}) or {}),
            "limitations": list(ygas.get("limitations", []) or []),
        }
    return {"native": False, "format": "tabular_or_normalized"}


def _sample_frame_fields(row: Any) -> dict[str, Any]:
    raw_payload = _json_payload(str(getattr(row, "raw_text", "") or ""))
    li7700_fields = {
        key: raw_payload.get(key)
        for key in [
            "li7700_rssi",
            "li7700_signal_strength",
            "li7700_status_word",
            "li7700_reference_rssi",
            "li7700_status_source_member",
            "li7700_status_match_delta_s",
            "li7700_status_match_basis",
        ]
        if raw_payload.get(key) is not None
    }
    return {
        key: value
        for key, value in {
            "co2_ppm": getattr(row, "co2_ppm", None),
            "h2o_mmol": getattr(row, "h2o_mmol", None),
            "ch4_ppb": getattr(row, "ch4_ppb", None),
            "n2o_ppb": getattr(row, "n2o_ppb", None),
            "pressure_kpa": getattr(row, "pressure_kpa", None),
            "chamber_temp_c": getattr(row, "chamber_temp_c", None),
            **li7700_fields,
        }.items()
        if value is not None
    }


def _json_payload(raw_text: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _metadata_draft_from_settings(settings: dict[str, str], *, bundle_root: Path | None = None) -> dict[str, Any]:
    draft: dict[str, Any] = {}

    project: dict[str, Any] = {}
    _set_str_if_present(project, "name", settings, ("project_name", "project_title", "title", "project_project_name"))
    _set_str_if_present(project, "code", settings, ("project_code", "project_id", "project_project_id", "project_project_code"))
    _set_str_if_present(project, "principal", settings, ("principal", "principal_investigator", "pi", "project_principal"))
    _set_str_if_present(project, "archive_root", settings, ("archive_root", "output_dir", "output_directory"))
    if project:
        draft["project"] = project

    site: dict[str, Any] = {}
    _set_str_if_present(site, "station_name", settings, ("station_name", "site_name", "site_station_name", "site_site_name"))
    _set_str_if_present(site, "station_code", settings, ("station_code", "site_id", "site_code", "station_id", "site_site_id"))
    _set_str_if_present(site, "location", settings, ("location", "site_location"))
    _set_str_if_present(site, "timezone", settings, ("timezone", "time_zone", "site_timezone", "site_time_zone"))
    for output_key, setting_keys in [
        ("latitude", ("latitude", "lat", "site_latitude", "tower_latitude")),
        ("longitude", ("longitude", "lon", "long", "site_longitude", "tower_longitude")),
        ("altitude_m", ("altitude_m", "altitude", "elevation_m", "site_altitude", "site_elevation")),
        ("canopy_height_m", ("canopy_height_m", "canopy_height", "site_canopy_height", "dynamic_canopy_height")),
        ("displacement_height", ("displacement_height", "displacement_height_m", "zero_plane_displacement")),
        ("roughness_length", ("roughness_length", "roughness_length_m", "z0")),
    ]:
        _set_float_if_present(site, output_key, settings, setting_keys)
    if site:
        draft["site"] = site

    instruments = _instrument_metadata_from_settings(settings)
    if instruments:
        draft["instruments"] = instruments

    sampling_chain = _sampling_chain_metadata_from_settings(settings)
    if sampling_chain:
        draft["sampling_chain"] = sampling_chain

    biomet = _biomet_metadata_from_settings(settings, bundle_root=bundle_root)
    if biomet:
        draft["biomet"] = biomet

    dynamic_metadata = _dynamic_metadata_from_settings(settings, bundle_root=bundle_root)
    if dynamic_metadata:
        draft["dynamic_metadata"] = dynamic_metadata

    return draft


def _instrument_metadata_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    instruments: dict[str, Any] = {}
    _set_str_if_present(
        instruments,
        "sonic_model",
        settings,
        ("sonic_model", "sonic_anemometer_model", "anemometer_model", "sonic_anemometer_type", "anemometer_type"),
    )
    _set_str_if_present(
        instruments,
        "analyzer_model",
        settings,
        ("analyzer_model", "gas_analyzer_model", "irga_model", "co2_h2o_analyzer_model", "gas_analyzer_type"),
    )
    _set_str_if_present(
        instruments,
        "sonic_manufacturer",
        settings,
        ("sonic_manufacturer", "sonic_anemometer_manufacturer", "anemometer_manufacturer"),
    )
    _set_str_if_present(
        instruments,
        "analyzer_manufacturer",
        settings,
        ("analyzer_manufacturer", "gas_analyzer_manufacturer", "irga_manufacturer", "co2_h2o_analyzer_manufacturer"),
    )
    _set_str_if_present(
        instruments,
        "sonic_serial",
        settings,
        ("sonic_serial", "sonic_serial_number", "sonic_sn", "sonic_anemometer_serial", "anemometer_serial", "anemometer_serial_number"),
    )
    _set_str_if_present(
        instruments,
        "analyzer_serial",
        settings,
        (
            "analyzer_serial",
            "analyzer_serial_number",
            "analyzer_sn",
            "gas_analyzer_serial",
            "gas_analyzer_serial_number",
            "irga_serial",
            "irga_serial_number",
            "co2_h2o_analyzer_serial",
        ),
    )
    _set_str_if_present(instruments, "sonic_firmware", settings, ("sonic_firmware", "sonic_firmware_version", "anemometer_firmware"))
    _set_str_if_present(
        instruments,
        "analyzer_firmware",
        settings,
        ("analyzer_firmware", "analyzer_firmware_version", "gas_analyzer_firmware", "irga_firmware"),
    )
    _set_str_if_present(instruments, "sonic_instrument_id", settings, ("sonic_instrument_id", "sonic_id", "anemometer_id"))
    _set_str_if_present(
        instruments,
        "analyzer_instrument_id",
        settings,
        ("analyzer_instrument_id", "analyzer_id", "gas_analyzer_id", "irga_id"),
    )
    _set_float_if_present(instruments, "sonic_height_m", settings, ("sonic_height_m", "sonic_height", "anemometer_height_m", "anemometer_height"))
    _set_float_if_present(
        instruments,
        "analyzer_height_m",
        settings,
        ("analyzer_height_m", "analyzer_height", "gas_analyzer_height_m", "gas_analyzer_height", "irga_height"),
    )
    _set_float_if_present(
        instruments,
        "sensor_separation_m",
        settings,
        ("sensor_separation_m", "sensor_sep_m", "gas_analyzer_sensor_separation_m", "gas_analyzer_sensor_separation", "irga_sensor_separation_m", "irga_sensor_separation"),
    )
    _set_float_if_present(
        instruments,
        "optical_path_length_m",
        settings,
        ("optical_path_length_m", "path_length_m", "analyzer_path_length_m", "gas_analyzer_path_length_m", "irga_path_length"),
    )
    _set_str_if_present(
        instruments,
        "methane_analyzer_model",
        settings,
        ("methane_analyzer_model", "li7700_model", "li_7700_model", "ch4_analyzer_model", "open_path_ch4_model"),
    )
    _set_str_if_present(
        instruments,
        "methane_analyzer_manufacturer",
        settings,
        ("methane_analyzer_manufacturer", "li7700_manufacturer", "li_7700_manufacturer", "ch4_analyzer_manufacturer"),
    )
    _set_str_if_present(
        instruments,
        "methane_analyzer_serial",
        settings,
        (
            "methane_analyzer_serial",
            "methane_analyzer_serial_number",
            "li7700_serial",
            "li7700_serial_number",
            "li_7700_serial",
            "li_7700_serial_number",
            "ch4_analyzer_serial",
            "ch4_analyzer_serial_number",
        ),
    )
    _set_str_if_present(
        instruments,
        "methane_analyzer_firmware",
        settings,
        ("methane_analyzer_firmware", "methane_analyzer_firmware_version", "li7700_firmware", "li7700_firmware_version", "li_7700_firmware"),
    )
    _set_float_if_present(
        instruments,
        "methane_analyzer_height_m",
        settings,
        ("methane_analyzer_height_m", "methane_analyzer_height", "li7700_height_m", "li7700_height", "li_7700_height_m", "ch4_analyzer_height"),
    )
    _set_str_if_present(instruments, "mount_description", settings, ("mount_description", "instrument_mount", "mounting"))
    _set_str_if_present(instruments, "geometry_detail", settings, ("geometry_detail", "instrument_geometry", "sensor_geometry"))

    extra = _instrument_extra_from_settings(settings)
    if extra:
        instruments["extra"] = extra
    return instruments


def _instrument_extra_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    extra: dict[str, Any] = {}
    _set_str_if_present(extra, "sonic_wind_format", settings, ("sonic_wind_format", "anemometer_wind_format", "wind_format"))
    _set_str_if_present(extra, "sonic_wind_reference", settings, ("sonic_wind_reference", "wind_reference", "w_reference"))
    _set_str_if_present(extra, "gill_wm_w_boost", settings, ("gill_wm_w_boost", "windmaster_w_boost", "w_boost"))
    for output_key, setting_keys in [
        ("sonic_north_offset_deg", ("sonic_north_offset_deg", "north_offset_deg", "anemometer_north_offset_deg")),
        ("sonic_u_offset_ms", ("sonic_u_offset_ms", "u_offset_ms", "u_offset")),
        ("sonic_v_offset_ms", ("sonic_v_offset_ms", "v_offset_ms", "v_offset")),
        ("sonic_w_offset_ms", ("sonic_w_offset_ms", "w_offset_ms", "w_offset")),
        ("crosswind_temperature_divisor", ("crosswind_temperature_divisor", "temperature_divisor")),
    ]:
        _set_float_if_present(extra, output_key, settings, setting_keys)
    crosswind_enabled = _truthy_setting(_first_setting(settings, ("crosswind_enabled", "crosswind_correction", "crosswind_correction_enabled")))
    if crosswind_enabled is not None:
        extra["crosswind_enabled"] = crosswind_enabled
    coefficients = _crosswind_coefficients_from_settings(settings)
    if coefficients:
        extra["crosswind_coefficients"] = coefficients
    _set_str_if_present(
        extra,
        "li7700_coefficient_profile_id",
        settings,
        (
            "li7700_coefficient_profile_id",
            "li_7700_coefficient_profile_id",
            "methane_coefficient_profile_id",
            "methane_analyzer_coefficient_profile_id",
            "ch4_coefficient_profile_id",
        ),
    )
    _set_str_if_present(
        extra,
        "li7700_coefficient_source_file",
        settings,
        (
            "li7700_coefficient_source_file",
            "li7700_coefficient_file",
            "li_7700_coefficient_source_file",
            "methane_coefficient_source_file",
            "methane_analyzer_coefficient_file",
            "ch4_coefficient_source_file",
        ),
    )
    _set_str_if_present(
        extra,
        "li7700_coefficient_normalization_command",
        settings,
        (
            "li7700_coefficient_normalization_command",
            "li7700_normalization_command",
            "li_7700_normalization_command",
            "methane_coefficient_normalization_command",
            "ch4_coefficient_normalization_command",
        ),
    )
    limitations = _list_setting(
        _first_setting(
            settings,
            (
                "li7700_known_limitations",
                "li_7700_known_limitations",
                "methane_known_limitations",
                "methane_analyzer_known_limitations",
                "ch4_known_limitations",
            ),
        )
    )
    if limitations:
        extra["li7700_known_limitations"] = limitations
    return extra


def _sampling_chain_metadata_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    chain: dict[str, Any] = {}
    for output_key, setting_keys in [
        ("tube_length_m", ("tube_length_m", "tube_length", "closed_path_tube_length_m", "closed_path_tube_length")),
        ("tube_diameter_mm", ("tube_diameter_mm", "tube_diameter", "closed_path_tube_diameter_mm")),
        ("flow_lpm", ("flow_lpm", "flow_rate_lpm", "flow_rate", "closed_path_flow_lpm")),
        ("path_length_m", ("path_length_m", "optical_path_length_m", "analyzer_path_length_m", "gas_analyzer_path_length_m")),
    ]:
        _set_float_if_present(chain, output_key, settings, setting_keys)
    _set_str_if_present(chain, "tube_material", settings, ("tube_material", "closed_path_tube_material"))
    _set_str_if_present(chain, "filter_model", settings, ("filter_model", "intake_filter_model"))
    heat_traced = _truthy_setting(_first_setting(settings, ("heat_traced", "tube_heat_traced", "closed_path_heat_traced")))
    if heat_traced is not None:
        chain["heat_traced"] = heat_traced
    insulated = _truthy_setting(_first_setting(settings, ("insulated", "tube_insulated", "closed_path_insulated")))
    if insulated is not None:
        chain["insulated"] = insulated
    extra: dict[str, Any] = {}
    for output_key, setting_keys in [
        ("cell_pressure_kpa", ("cell_pressure_kpa", "cell_pressure", "closed_path_cell_pressure_kpa")),
        ("cell_temperature_c", ("cell_temperature_c", "cell_temperature", "closed_path_cell_temperature_c")),
    ]:
        _set_float_if_present(extra, output_key, settings, setting_keys)
    if extra:
        chain["extra"] = extra
    return chain


def _biomet_metadata_from_settings(settings: dict[str, str], *, bundle_root: Path | None = None) -> dict[str, Any]:
    biomet: dict[str, Any] = {}
    _set_str_if_present(biomet, "source_path", settings, ("biomet_source_path", "biomet_file", "biomet_path", "biomet_directory"))
    discovered = _discover_bundle_file(bundle_root, stems=("biomet", "bio_met", "meteorological", "meteo"), suffixes=(".csv", ".txt", ".dat", ".data"))
    if discovered is not None and not biomet.get("source_path"):
        biomet["source_path"] = _portable_bundle_path(discovered, bundle_root)
        biomet.setdefault("extra", {})["auto_discovered"] = True
    source_mode = _first_setting(settings, ("biomet_source_mode", "biomet_mode"))
    if not source_mode and biomet.get("source_path"):
        source_mode = "external_file"
    if source_mode:
        biomet["source_mode"] = source_mode
    _set_str_if_present(biomet, "time_column", settings, ("biomet_time_column", "biomet_timestamp_column"))
    _set_str_if_present(biomet, "aggregation_method", settings, ("biomet_aggregation_method", "biomet_aggregation"))
    fields = _list_setting(_first_setting(settings, ("biomet_fields", "biomet_variables")))
    if not fields and discovered is not None:
        fields = _data_fields_from_header(discovered)
    if fields:
        biomet["fields"] = fields
    return biomet


def _dynamic_metadata_from_settings(settings: dict[str, str], *, bundle_root: Path | None = None) -> dict[str, Any]:
    source_path = _first_setting(
        settings,
        (
            "dynamic_metadata_source_path",
            "dynamic_metadata_file",
            "dynamic_canopy_height_file",
            "canopy_height_file",
            "site_dynamic_canopy_height_file",
        ),
    )
    dynamic: dict[str, Any] = {}
    discovered = _discover_bundle_file(bundle_root, stems=("dynamic", "canopy", "crop"), suffixes=(".csv", ".txt", ".dat"))
    if not source_path and discovered is not None:
        source_path = _portable_bundle_path(discovered, bundle_root)
        dynamic.setdefault("extra", {})["auto_discovered"] = True
    if source_path:
        dynamic["source_path"] = source_path
    _set_str_if_present(dynamic, "start_column", settings, ("dynamic_metadata_start_column", "dynamic_start_column"))
    _set_str_if_present(dynamic, "end_column", settings, ("dynamic_metadata_end_column", "dynamic_end_column"))
    _set_str_if_present(dynamic, "timezone", settings, ("dynamic_metadata_timezone", "timezone", "time_zone"))
    if _first_setting(settings, ("dynamic_canopy_height", "canopy_height")):
        dynamic["fields"] = ["canopy_height_m"]
    elif discovered is not None:
        discovered_fields = _data_fields_from_header(discovered)
        if any("canopy" in field.lower() for field in discovered_fields):
            dynamic["fields"] = ["canopy_height_m"]
        elif discovered_fields:
            dynamic["fields"] = discovered_fields
    return dynamic


def _processing_config_from_settings(settings: dict[str, str], *, bundle_root: Path | None = None) -> dict[str, Any]:
    config: dict[str, Any] = {}
    steps: dict[str, Any] = {}

    rotation = _normalize_rotation_setting(
        _first_setting(settings, ("rotation_mode", "rotation_method", "axis_rotation", "coordinate_rotation"))
    )
    if rotation:
        config["rotation_mode"] = rotation
        steps["rotation"] = {"rotation_mode": rotation, "method": rotation}

    detrend = _normalize_detrend_setting(
        _first_setting(settings, ("detrend_mode", "detrend_method", "trend_removal", "turbulent_fluctuations"))
    )
    if detrend:
        config["detrend_mode"] = detrend
        steps["detrend"] = {"detrend_mode": detrend, "method": detrend}

    density = _normalize_density_setting(
        _first_setting(settings, ("density_correction_mode", "density_correction", "wpl_correction", "wpl"))
    )
    if density:
        config["density_correction_mode"] = density
        steps["density_correction"] = {"correction_mode": density, "method": density}

    lag_config: dict[str, Any] = {}
    lag_strategy = _normalize_lag_setting(
        _first_setting(settings, ("lag_strategy", "lag_determination", "time_lag_method", "lag_method"))
    )
    if lag_strategy:
        lag_config["strategy"] = lag_strategy
    expected_lag_s = _optional_float(_first_setting(settings, ("expected_lag_s", "nominal_lag_s", "fixed_lag_s", "lag_s")))
    if expected_lag_s is not None:
        lag_config["expected_lag_s"] = expected_lag_s
    search_window_s = _optional_float(
        _first_setting(settings, ("search_window_s", "lag_search_window_s", "max_lag_s", "time_lag_max_lag_s"))
    )
    if search_window_s is not None:
        lag_config["search_window_s"] = search_window_s
    if lag_config:
        config["lag_phase"] = dict(lag_config)
        config["lag"] = dict(lag_config)
        steps["lag"] = dict(lag_config)

    screening = _screening_config_from_settings(settings)
    if screening:
        config["screening"] = dict(screening)
        steps["screening"] = dict(screening)

    footprint = _footprint_config_from_settings(settings)
    if footprint:
        config["footprint"] = dict(footprint)
        steps["footprint"] = dict(footprint)

    uncertainty = _uncertainty_config_from_settings(settings)
    if uncertainty:
        config["uncertainty"] = dict(uncertainty)
        steps["uncertainty"] = dict(uncertainty)

    qc = _qc_config_from_settings(settings)
    if qc:
        config["qc"] = dict(qc)
        steps["qc"] = dict(qc)

    sonic = _sonic_correction_config_from_settings(settings)
    if sonic:
        config["sonic_correction"] = dict(sonic)
        steps["sonic_correction"] = dict(sonic)

    crosswind = _crosswind_correction_config_from_settings(settings)
    if crosswind:
        config["crosswind_correction"] = dict(crosswind)
        steps["crosswind_correction"] = dict(crosswind)

    spectral = _spectral_correction_config_from_settings(settings)
    if spectral:
        config["spectral_correction"] = dict(spectral)
        steps["spectral_correction"] = dict(spectral)

    trace_gas = _trace_gas_config_from_settings(settings, bundle_root=bundle_root)
    if trace_gas:
        config["trace_gas"] = dict(trace_gas)
        steps["trace_gas"] = dict(trace_gas)

    if steps:
        config["steps"] = steps
    return config


def _screening_config_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    numeric_keys = {
        "skewness_threshold": ("skewness_threshold", "skew_threshold", "skewness_limit"),
        "kurtosis_threshold": ("kurtosis_threshold", "kurtosis_limit"),
        "spike_sigma": ("spike_sigma", "spike_detection_sigma", "despike_sigma"),
        "discontinuity_sigma": ("discontinuity_sigma", "discontinuity_detection_sigma"),
    }
    screening: dict[str, Any] = {}
    for output_key, setting_keys in numeric_keys.items():
        value = _optional_float(_first_setting(settings, setting_keys))
        if value is not None:
            screening[output_key] = value
    dropout = _optional_float(_first_setting(settings, ("dropout_min_run", "drop_out_min_run", "dropout_min_samples")))
    if dropout is not None:
        screening["dropout_min_run"] = int(dropout)
    return screening


def _qc_config_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    raw = _first_setting(settings, ("qc_meth", "qc_method", "quality_flagging_method", "quality_control_method"))
    method = _normalize_qc_setting(raw)
    qc: dict[str, Any] = {}
    if raw not in ("", None):
        qc["eddypro_qc_meth"] = str(raw).strip()
    if method:
        qc["method"] = method
        qc["enabled"] = method != "none"
    return qc


def _footprint_config_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    enabled_value = _first_setting(settings, ("footprint_enabled", "footprint", "use_footprint", "footprint_model"))
    method_value = _first_setting(settings, ("footprint_method", "footprint_model"))
    method = _normalize_footprint_setting(method_value or enabled_value)
    enabled = _truthy_setting(enabled_value)
    footprint: dict[str, Any] = {}
    if enabled is not None:
        footprint["enabled"] = enabled
    elif method:
        footprint["enabled"] = True
    if method:
        footprint["method"] = method
    _set_float_if_present(
        footprint,
        "z_m",
        settings,
        ("z_m", "measurement_height", "measurement_height_m", "sonic_height", "sonic_height_m", "anemometer_height", "anemometer_height_m"),
    )
    _set_float_if_present(footprint, "canopy_height_m", settings, ("canopy_height", "canopy_height_m", "canopy_h"))
    _set_float_if_present(footprint, "z0", settings, ("z0", "roughness_length", "roughness_length_m"))
    _set_float_if_present(footprint, "ol", settings, ("ol", "monin_obukhov_length", "monin_obukhov_length_m"))
    grid_enabled = _truthy_setting(_first_setting(settings, ("footprint_grid_enabled", "footprint_2d_grid", "source_area_grid")))
    if grid_enabled is not None:
        footprint["grid_enabled"] = grid_enabled
    return footprint


def _uncertainty_config_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    method = _normalize_uncertainty_setting(
        _first_setting(settings, ("uncertainty_method", "random_uncertainty_method", "random_error_method"))
    )
    uncertainty: dict[str, Any] = {}
    if method:
        uncertainty["method"] = method
    _set_float_if_present(uncertainty, "integral_timescale_s", settings, ("integral_timescale_s", "tau_integral_s"))
    _set_float_if_present(uncertainty, "confidence_level", settings, ("confidence_level", "uncertainty_confidence_level"))
    return uncertainty


def _sonic_correction_config_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    enabled = _truthy_setting(_first_setting(settings, ("sonic_correction_enabled", "sonic_correction", "apply_sonic_correction")))
    sonic: dict[str, Any] = {}
    if enabled is not None:
        sonic["enabled"] = enabled
    _set_str_if_present(sonic, "method", settings, ("sonic_correction_method",))
    _set_str_if_present(
        sonic,
        "sonic_model",
        settings,
        ("sonic_model", "sonic_anemometer_model", "anemometer_model", "sonic_anemometer_type", "anemometer_type"),
    )
    _set_str_if_present(
        sonic,
        "sonic_manufacturer",
        settings,
        ("sonic_manufacturer", "sonic_anemometer_manufacturer", "anemometer_manufacturer"),
    )
    _set_str_if_present(sonic, "sonic_firmware", settings, ("sonic_firmware", "sonic_firmware_version", "anemometer_firmware"))
    _set_str_if_present(sonic, "wind_format", settings, ("sonic_wind_format", "anemometer_wind_format", "wind_format"))
    _set_str_if_present(sonic, "wind_reference", settings, ("sonic_wind_reference", "wind_reference", "w_reference"))
    _set_str_if_present(sonic, "gill_wm_w_boost", settings, ("gill_wm_w_boost", "windmaster_w_boost", "w_boost"))
    for output_key, setting_keys in [
        ("north_offset_deg", ("sonic_north_offset_deg", "north_offset_deg", "anemometer_north_offset_deg")),
        ("u_offset_ms", ("sonic_u_offset_ms", "u_offset_ms", "u_offset")),
        ("v_offset_ms", ("sonic_v_offset_ms", "v_offset_ms", "v_offset")),
        ("w_offset_ms", ("sonic_w_offset_ms", "w_offset_ms", "w_offset")),
    ]:
        _set_float_if_present(sonic, output_key, settings, setting_keys)
    aoa_enabled = _truthy_setting(_first_setting(settings, ("angle_of_attack_enabled", "angle_of_attack_correction", "aoa_correction")))
    aoa: dict[str, Any] = {}
    if aoa_enabled is not None:
        aoa["enabled"] = aoa_enabled
    _set_str_if_present(
        aoa,
        "method",
        settings,
        (
            "aoa_method",
            "angle_of_attack_method",
            "angle_of_attack_correction_method",
            "calib_aoa",
            "aoa_calibration",
        ),
    )
    _set_float_if_present(aoa, "horizontal_gain_per_reference_angle", settings, ("aoa_horizontal_gain", "angle_of_attack_horizontal_gain"))
    _set_float_if_present(aoa, "vertical_gain_per_reference_angle", settings, ("aoa_vertical_gain", "angle_of_attack_vertical_gain"))
    _set_float_if_present(aoa, "reference_angle_deg", settings, ("aoa_reference_angle_deg", "angle_of_attack_reference_angle_deg"))
    if aoa:
        sonic["angle_of_attack"] = aoa
    if sonic and "enabled" not in sonic:
        sonic["enabled"] = True
    return sonic


def _crosswind_correction_config_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    enabled = _truthy_setting(_first_setting(settings, ("crosswind_enabled", "crosswind_correction", "crosswind_correction_enabled")))
    crosswind: dict[str, Any] = {}
    if enabled is not None:
        crosswind["enabled"] = enabled
    _set_str_if_present(crosswind, "method", settings, ("crosswind_correction_method",))
    _set_str_if_present(
        crosswind,
        "sonic_model",
        settings,
        ("sonic_model", "sonic_anemometer_model", "anemometer_model", "sonic_anemometer_type", "anemometer_type"),
    )
    _set_str_if_present(
        crosswind,
        "sonic_manufacturer",
        settings,
        ("sonic_manufacturer", "sonic_anemometer_manufacturer", "anemometer_manufacturer"),
    )
    _set_float_if_present(crosswind, "temperature_divisor", settings, ("crosswind_temperature_divisor", "temperature_divisor"))
    coefficients = _crosswind_coefficients_from_settings(settings)
    if coefficients:
        crosswind["coefficients"] = coefficients
    if crosswind and "enabled" not in crosswind:
        crosswind["enabled"] = True
    return crosswind


def _spectral_correction_config_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    hf_meth_raw = _first_setting(settings, ("hf_meth", "rawprocess_settings.hf_meth", "fluxcorrection_spectralanalysis_general.hf_meth"))
    lf_meth_raw = _first_setting(settings, ("lf_meth", "rawprocess_settings.lf_meth", "fluxcorrection_spectralanalysis_general.lf_meth"))
    enabled_value = _first_setting(
        settings,
        (
            "spectral_correction_enabled",
            "spectral_correction",
            "use_spectral_correction",
            "low_pass_correction",
            "high_pass_correction",
            "hf_meth",
            "lf_meth",
        ),
    )
    method_value = _first_setting(
        settings,
        (
            "spectral_correction_method",
            "spectral_method",
            "low_pass_correction_method",
            "high_pass_correction_method",
            "hf_meth",
        ),
    )
    method = _normalize_eddypro_hf_setting(hf_meth_raw) or _normalize_spectral_setting(method_value or enabled_value)
    enabled = _truthy_setting(enabled_value)
    lf_method = _normalize_eddypro_lf_setting(lf_meth_raw)
    spectral: dict[str, Any] = {}
    if hf_meth_raw not in ("", None):
        spectral["eddypro_hf_meth"] = str(hf_meth_raw).strip()
    if lf_meth_raw not in ("", None):
        spectral["eddypro_lf_meth"] = str(lf_meth_raw).strip()
    if lf_method:
        spectral["low_frequency_method"] = lf_method
    if enabled is not None:
        spectral["enabled"] = enabled
    elif method:
        spectral["enabled"] = True
    if method == "none":
        spectral["enabled"] = False
    if method:
        spectral["method"] = method
    _set_float_if_present(
        spectral,
        "path_length_m",
        settings,
        ("path_length_m", "analyzer_path_length_m", "gas_analyzer_path_length_m", "irga_path_length", "optical_path_length_m"),
    )
    _set_float_if_present(
        spectral,
        "sensor_sep_m",
        settings,
        ("sensor_sep_m", "sensor_separation_m", "gas_analyzer_sensor_separation_m", "gas_analyzer_sensor_separation", "irga_sensor_separation_m", "irga_sensor_separation"),
    )
    _set_float_if_present(
        spectral,
        "response_time_s",
        settings,
        ("response_time_s", "analyzer_response_time_s", "gas_analyzer_response_time_s", "irga_response_time"),
    )
    _set_float_if_present(
        spectral,
        "z_m",
        settings,
        ("spectral_z_m", "measurement_height", "measurement_height_m", "sonic_height", "sonic_height_m"),
    )
    _set_float_if_present(spectral, "ol", settings, ("spectral_ol", "ol", "monin_obukhov_length", "monin_obukhov_length_m"))
    measured_cospectrum = _truthy_setting(
        _first_setting(settings, ("use_fcc_measured_cospectrum", "fratini_measured_cospectrum", "measured_cospectrum"))
    )
    if measured_cospectrum is not None:
        spectral["use_fcc_measured_cospectrum"] = measured_cospectrum
    return spectral


def _trace_gas_config_from_settings(settings: dict[str, str], *, bundle_root: Path | None = None) -> dict[str, Any]:
    enabled = _truthy_setting(
        _first_setting(
            settings,
            (
                "ch4_enabled",
                "methane_enabled",
                "trace_gas_ch4_enabled",
                "trace_gas_methane_enabled",
                "li7700_enabled",
                "li_7700_enabled",
                "process_ch4",
                "process_methane",
            ),
        )
    )
    method = _first_setting(
        settings,
        (
            "ch4_method",
            "methane_method",
            "trace_gas_ch4_method",
            "li7700_method",
            "li_7700_method",
        ),
    )
    profile_id = _first_setting(
        settings,
        (
            "ch4_coefficient_profile_id",
            "methane_coefficient_profile_id",
            "methane_analyzer_coefficient_profile_id",
            "li7700_coefficient_profile_id",
            "li_7700_coefficient_profile_id",
            "li7700_profile_id",
            "coefficient_profile_id",
        ),
    )
    source_file_value = _first_setting(
        settings,
        (
            "ch4_coefficient_source_file",
            "ch4_coefficient_file",
            "methane_coefficient_source_file",
            "methane_analyzer_coefficient_file",
            "li7700_coefficient_source_file",
            "li7700_coefficient_file",
            "li_7700_coefficient_source_file",
            "li7700_wms_coefficients_file",
            "wms_coefficients_file",
        ),
    )
    source_path = _resolve_bundle_path(source_file_value, bundle_root) if source_file_value else None
    if source_path is None:
        source_path = _discover_li7700_coefficient_file(bundle_root)
    source_file = _portable_bundle_path(source_path, bundle_root) if source_path is not None else str(source_file_value or "")
    profile_from_file = _li7700_profile_from_file(source_path, profile_id=profile_id) if source_path is not None else {}
    if not profile_id:
        profile_id = str(profile_from_file.get("profile_id") or profile_from_file.get("id") or "")
    if not profile_id and source_path is not None:
        profile_id = _safe_fixture_id(source_path.stem)

    model_hint = _first_setting(
        settings,
        (
            "methane_analyzer_model",
            "li7700_model",
            "li_7700_model",
            "ch4_analyzer_model",
            "open_path_ch4_model",
        ),
    )
    has_li7700_hint = (
        enabled is not None
        or bool(method)
        or bool(profile_id)
        or bool(source_file)
        or bool(model_hint if "7700" in model_hint.lower() or "methane" in model_hint.lower() else "")
    )
    if not has_li7700_hint:
        return {}

    ch4: dict[str, Any] = {
        "enabled": True if enabled is None else enabled,
        "method": method.strip() or "li_7700_correction_sequence_v1",
    }
    if profile_id:
        ch4["coefficient_profile_id"] = profile_id

    apply_dilution = _truthy_setting(
        _first_setting(
            settings,
            (
                "ch4_apply_water_vapor_dilution",
                "methane_apply_water_vapor_dilution",
                "li7700_apply_water_vapor_dilution",
                "apply_water_vapor_dilution",
                "water_vapor_dilution_correction",
            ),
        )
    )
    if apply_dilution is not None:
        ch4["apply_water_vapor_dilution"] = apply_dilution
    use_spectral_factor = _truthy_setting(
        _first_setting(
            settings,
            (
                "ch4_use_spectral_correction_factor",
                "methane_use_spectral_correction_factor",
                "li7700_use_spectral_correction_factor",
                "use_ch4_spectral_correction",
            ),
        )
    )
    if use_spectral_factor is not None:
        ch4["use_spectral_correction_factor"] = use_spectral_factor
    spectral_factor = _optional_float(
        _first_setting(
            settings,
            (
                "ch4_spectral_correction_factor",
                "methane_spectral_correction_factor",
                "li7700_spectral_correction_factor",
                "li_7700_spectral_correction_factor",
            ),
        )
    )
    if spectral_factor is not None:
        ch4["spectral_correction_factor"] = spectral_factor

    spectroscopic = _li7700_spectroscopic_config_from_settings(settings)
    if spectroscopic:
        ch4["spectroscopic_correction"] = spectroscopic
    self_heating = _li7700_self_heating_config_from_settings(settings)
    if self_heating:
        ch4["self_heating_correction"] = self_heating
    status_diagnostics = _li7700_status_diagnostics_config_from_settings(settings)
    if status_diagnostics:
        ch4["status_diagnostics"] = status_diagnostics

    if not profile_id:
        profile_id = "li7700_imported_from_project"
        ch4["coefficient_profile_id"] = profile_id

    profile = dict(profile_from_file)
    profile.setdefault("profile_id", profile_id)
    profile.setdefault("label", _first_setting(settings, ("li7700_profile_label", "methane_profile_label", "ch4_profile_label")) or profile_id)
    profile.setdefault("instrument_family", "LI-7700")
    profile.setdefault("source", "auto_discovered_bundle_file" if source_path is not None and not source_file_value else "eddypro_project_settings")
    profile.setdefault("source_file", source_file)
    profile.setdefault(
        "normalization_command",
        _first_setting(
            settings,
            (
                "ch4_coefficient_normalization_command",
                "methane_coefficient_normalization_command",
                "li7700_coefficient_normalization_command",
                "li7700_normalization_command",
                "li_7700_normalization_command",
                "normalization_command",
            ),
        ),
    )
    limitations = _list_setting(
        _first_setting(
            settings,
            (
                "ch4_known_limitations",
                "methane_known_limitations",
                "methane_analyzer_known_limitations",
                "li7700_known_limitations",
                "li_7700_known_limitations",
            ),
        )
    )
    profile_limitations = profile.get("known_limitations", profile.get("limitations", []))
    if profile_limitations:
        limitations = [*_string_list(profile_limitations), *limitations]
    if not limitations:
        limitations = [
            "LI-7700 coefficients imported from EddyPro project evidence require official output validation before numeric parity claims.",
            "If a source coefficient file is absent, factory-compensated CH4 inputs are assumed.",
        ]
    profile["known_limitations"] = [str(item) for item in limitations if str(item)]
    profile.setdefault(
        "provenance",
        (
            "LI-7700 methane correction profile imported from EddyPro project settings"
            + (f" and coefficient file '{source_file}'." if source_file else ".")
        ),
    )
    for key in ("apply_water_vapor_dilution", "use_spectral_correction_factor", "spectral_correction_factor"):
        if key in ch4:
            profile.setdefault(key, ch4[key])
    if spectroscopic:
        profile.setdefault("spectroscopic_correction", dict(spectroscopic))
    if self_heating:
        profile.setdefault("self_heating_correction", dict(self_heating))
    if status_diagnostics:
        profile.setdefault("status_diagnostics", dict(status_diagnostics))

    registry = {profile_id: profile}
    ch4["coefficient_registry"] = registry
    return {
        "ch4": ch4,
        "li7700": {
            "coefficient_profile_id": profile_id,
            "coefficient_registry": registry,
            "source_file": source_file,
            "provenance": profile["provenance"],
            "known_limitations": profile["known_limitations"],
        },
        "li7700_coefficient_registry": registry,
    }


def _li7700_spectroscopic_config_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    spectroscopic: dict[str, Any] = {}
    _set_str_if_present(
        spectroscopic,
        "mode",
        settings,
        ("ch4_spectroscopic_mode", "methane_spectroscopic_mode", "li7700_spectroscopic_mode", "spectroscopic_mode"),
    )
    for output_key, setting_keys in [
        (
            "pressure_sensitivity_per_kpa",
            (
                "ch4_pressure_sensitivity_per_kpa",
                "methane_pressure_sensitivity_per_kpa",
                "li7700_pressure_sensitivity_per_kpa",
                "pressure_sensitivity_per_kpa",
            ),
        ),
        (
            "temperature_sensitivity_per_c",
            (
                "ch4_temperature_sensitivity_per_c",
                "methane_temperature_sensitivity_per_c",
                "li7700_temperature_sensitivity_per_c",
                "temperature_sensitivity_per_c",
            ),
        ),
        (
            "h2o_sensitivity_per_molfrac",
            (
                "ch4_h2o_sensitivity_per_molfrac",
                "methane_h2o_sensitivity_per_molfrac",
                "li7700_h2o_sensitivity_per_molfrac",
                "h2o_sensitivity_per_molfrac",
            ),
        ),
    ]:
        _set_float_if_present(spectroscopic, output_key, settings, setting_keys)
    return spectroscopic


def _li7700_self_heating_config_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    self_heating: dict[str, Any] = {}
    _set_str_if_present(
        self_heating,
        "mode",
        settings,
        ("ch4_self_heating_mode", "methane_self_heating_mode", "li7700_self_heating_mode", "self_heating_mode"),
    )
    for output_key, setting_keys in [
        (
            "sensor_body_temp_c",
            ("ch4_sensor_body_temp_c", "methane_sensor_body_temp_c", "li7700_sensor_body_temp_c", "sensor_body_temp_c"),
        ),
        (
            "temperature_excess_c",
            ("ch4_temperature_excess_c", "methane_temperature_excess_c", "li7700_temperature_excess_c", "temperature_excess_c"),
        ),
        (
            "flux_sensitivity_per_c",
            ("ch4_flux_sensitivity_per_c", "methane_flux_sensitivity_per_c", "li7700_flux_sensitivity_per_c", "flux_sensitivity_per_c"),
        ),
    ]:
        _set_float_if_present(self_heating, output_key, settings, setting_keys)
    return self_heating


def _li7700_status_diagnostics_config_from_settings(settings: dict[str, str]) -> dict[str, Any]:
    diagnostics: dict[str, Any] = {}
    for output_key, setting_keys in [
        (
            "min_rssi_fail_pct",
            (
                "ch4_min_rssi_fail_pct",
                "methane_min_rssi_fail_pct",
                "li7700_min_rssi_fail_pct",
                "min_rssi_fail_pct",
            ),
        ),
        (
            "min_rssi_warning_pct",
            (
                "ch4_min_rssi_warning_pct",
                "methane_min_rssi_warning_pct",
                "li7700_min_rssi_warning_pct",
                "min_rssi_warning_pct",
            ),
        ),
        (
            "min_signal_strength_warning_pct",
            (
                "ch4_min_signal_strength_warning_pct",
                "methane_min_signal_strength_warning_pct",
                "li7700_min_signal_strength_warning_pct",
                "min_signal_strength_warning_pct",
            ),
        ),
        (
            "max_mirror_dirty_fraction",
            (
                "ch4_max_mirror_dirty_fraction",
                "methane_max_mirror_dirty_fraction",
                "li7700_max_mirror_dirty_fraction",
                "max_mirror_dirty_fraction",
            ),
        ),
    ]:
        _set_float_if_present(diagnostics, output_key, settings, setting_keys)
    require_lock = _truthy_setting(
        _first_setting(
            settings,
            (
                "ch4_require_li7700_lock",
                "methane_require_li7700_lock",
                "li7700_require_lock",
                "require_li7700_lock",
            ),
        )
    )
    if require_lock is not None:
        diagnostics["require_lock"] = require_lock
    allowed_words = _int_list_setting(
        _first_setting(
            settings,
            (
                "ch4_allowed_status_words",
                "methane_allowed_status_words",
                "li7700_allowed_status_words",
                "allowed_status_words",
            ),
        )
    )
    if allowed_words:
        diagnostics["allowed_status_words"] = allowed_words
    bit_map = _status_bit_map_setting(
        _first_setting(
            settings,
            (
                "ch4_status_bit_map",
                "methane_status_bit_map",
                "li7700_status_bit_map",
                "li7700_diagnostic_bit_map",
                "status_bit_map",
            ),
        )
    )
    if bit_map:
        diagnostics["status_bit_map"] = bit_map
    if diagnostics:
        diagnostics["provenance"] = "LI-7700 status diagnostic policy imported from EddyPro project/settings evidence."
    return diagnostics


def _parse_eddypro_settings(path: Path) -> dict[str, str]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return {}
    settings: dict[str, str] = {}
    current_section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", ";", "!")):
            continue
        section_match = re.fullmatch(r"\[([^\]]+)\]", line)
        if section_match:
            current_section = _normalize_setting_key(section_match.group(1))
            continue
        if "=" in line:
            key, value = line.split("=", 1)
        elif ":" in line:
            key, value = line.split(":", 1)
        else:
            continue
        normalized_key = _normalize_setting_key(key)
        if normalized_key:
            cleaned_value = value.strip().strip('"').strip("'")
            if current_section:
                settings.setdefault(normalized_key, cleaned_value)
                for section_alias in _section_aliases(current_section):
                    settings[f"{section_alias}_{normalized_key}"] = cleaned_value
            else:
                settings[normalized_key] = cleaned_value
    return settings


def _columns_from_settings(settings: dict[str, str]) -> list[str]:
    value = _first_setting(settings, ("columns", "raw_columns", "file_columns", "column_names", "var_names"))
    if not value:
        return []
    return [item.strip().strip('"').strip("'") for item in re.split(r"[,;\t ]+", value) if item.strip()]


def _column_mappings_from_columns(columns: Any) -> list[dict[str, Any]]:
    mappings: list[dict[str, Any]] = []
    for column in list(columns or []):
        variable = _variable_from_column(column)
        mappings.append(
            {
                "column_name": str(column),
                "variable": variable,
                "numeric": variable != "timestamp",
                "ignore": variable in {"", "ignore"},
            }
        )
    return mappings


def _variable_from_column(column: Any) -> str:
    normalized = str(column or "").strip().lower().replace(" ", "_").replace("-", "_")
    if normalized in {"timestamp", "date_time", "datetime", "time"}:
        return "timestamp"
    if normalized in {"record", "record_number", "rn", "rec"}:
        return "ignore"
    if normalized in {"u", "ux", "u_unrot", "wind_u"}:
        return "u"
    if normalized in {"v", "vy", "v_unrot", "wind_v"}:
        return "v"
    if normalized in {"w", "wz", "w_unrot", "vertical_wind"}:
        return "w"
    if "co2" in normalized:
        return "co2_ppm"
    if "h2o" in normalized:
        return "h2o_mmol"
    if "ch4" in normalized or "methane" in normalized:
        return "ch4_ppb"
    if "n2o" in normalized or "nitrous_oxide" in normalized:
        return "n2o_ppb"
    if normalized in {"p", "pa", "press", "pressure"} or "pressure" in normalized:
        return "pressure_kpa"
    if normalized in {"ta", "ts", "tc", "temp", "temperature", "sonic_temperature"}:
        return "chamber_temp_c"
    return normalized


def _infer_reference_start_time(path: Path) -> str:
    payload = _read_json(path)
    windows = list(payload.get("windows", []) or [])
    if not windows:
        return ""
    return str(dict(windows[0] or {}).get("start_time", "") or "")


def _infer_full_output_start_time(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    if len(lines) < 2:
        return ""
    header = [item.strip().lower() for item in lines[0].split(",")]
    values = [item.strip() for item in lines[1].split(",")]
    lookup = {key: values[index] for index, key in enumerate(header) if index < len(values)}
    timestamp = lookup.get("timestamp_start") or lookup.get("date")
    if timestamp and re.fullmatch(r"\d{12}", timestamp):
        return f"{timestamp[:4]}-{timestamp[4:6]}-{timestamp[6:8]}T{timestamp[8:10]}:{timestamp[10:12]}:00"
    return ""


def _import_plan_sources(
    *,
    raw_claim: dict[str, Any],
    project_claim: dict[str, Any],
    reference_path: Path,
    output_path: Path,
    settings: dict[str, str],
    raw_inference: dict[str, Any],
    processing_config: dict[str, Any],
    raw_import_probe: dict[str, Any],
) -> list[dict[str, Any]]:
    sources = []
    if raw_claim:
        sources.append({"role": "raw_input", "path": raw_claim.get("relative_to_workspace", ""), "used_for": "raw format, header, and column inference"})
    if project_claim:
        sources.append({"role": "eddypro_project_file", "path": project_claim.get("relative_to_workspace", ""), "used_for": "sampling/timing/import settings", "parsed_key_count": len(settings)})
    if reference_path.exists():
        sources.append({"role": "reference_json", "path": str(reference_path), "used_for": "window duration and start-time fallback"})
    if output_path.exists():
        sources.append({"role": "official_full_output", "path": str(output_path), "used_for": "TIMESTAMP_START fallback"})
    if raw_inference.get("extra"):
        sources.append({"role": "import_config_draft", "path": "", "used_for": "native raw importer extra settings"})
    if processing_config:
        sources.append(
            {
                "role": "rp_config_draft",
                "path": "",
                "used_for": "rotation, lag, density correction, spectral, footprint, uncertainty, and QC processing settings",
            }
        )
    if raw_import_probe:
        sources.append(
            {
                "role": "raw_import_probe",
                "path": raw_claim.get("relative_to_workspace", ""),
                "used_for": "preflight raw decoding with inferred metadata",
                "status": raw_import_probe.get("status", ""),
                "row_count": raw_import_probe.get("row_count", 0),
            }
        )
    return sources


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists() or not path.is_file():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _first_setting(settings: dict[str, str], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = settings.get(_normalize_setting_key(key), "")
        if value not in ("", None):
            return str(value)
    return ""


def _normalize_setting_key(key: Any) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", str(key or "").strip().lower())
    return normalized.strip("_")


def _section_aliases(section: str) -> list[str]:
    aliases = {section}
    if any(token in section for token in ("sonic", "anemometer", "wind")):
        aliases.update({"sonic", "anemometer", "sonic_anemometer"})
    if any(token in section for token in ("gas", "analyzer", "irga", "co2", "h2o")):
        aliases.update({"analyzer", "gas_analyzer", "irga", "co2_h2o_analyzer"})
    if any(token in section for token in ("li7700", "li_7700", "methane", "ch4", "trace_gas")):
        aliases.update({"li7700", "li_7700", "methane", "methane_analyzer", "ch4", "ch4_analyzer", "trace_gas"})
    if any(token in section for token in ("site", "station", "tower")):
        aliases.update({"site", "station", "tower"})
    if "project" in section:
        aliases.add("project")
    if any(token in section for token in ("closed_path", "sampling", "tube", "intake")):
        aliases.update({"closed_path", "sampling_chain"})
    if "biomet" in section:
        aliases.add("biomet")
    if "dynamic" in section or "canopy" in section:
        aliases.update({"dynamic_metadata", "dynamic"})
    if "processing" in section or "eddypro" in section:
        aliases.add("processing")
    return sorted(alias for alias in aliases if alias)


def _data_type_from_setting(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized in {"2", "int2", "integer2", "short"}:
        return "int16"
    if normalized in {"4", "float", "real4", "ieee4"}:
        return "float32"
    if normalized in {"8", "double", "real8"}:
        return "float64"
    return normalized


def _normalize_rotation_setting(value: Any) -> str:
    token = _setting_token(value)
    aliases = {
        "no_rotation": "none",
        "none": "none",
        "single": "single",
        "single_rotation": "single",
        "double": "double",
        "double_rotation": "double",
        "2d": "double",
        "triple": "triple",
        "triple_rotation": "triple",
        "3d": "triple",
        "planar_fit": "planar_fit",
        "pf": "planar_fit",
        "sector_wise_planar_fit": "sector_wise_planar_fit",
        "sector_planar_fit": "sector_wise_planar_fit",
        "swpf": "sector_wise_planar_fit",
        "sector_wise_planar_fit_no_velocity_bias": "sector_wise_planar_fit_no_velocity_bias",
        "swpf_nvb": "sector_wise_planar_fit_no_velocity_bias",
    }
    return aliases.get(token, "")


def _normalize_detrend_setting(value: Any) -> str:
    token = _setting_token(value)
    aliases = {
        "block_mean": "block_mean",
        "blockmean": "block_mean",
        "mean_removal": "block_mean",
        "linear": "linear",
        "linear_detrending": "linear",
        "running": "running_mean",
        "running_mean": "running_mean",
        "moving_average": "running_mean",
        "moving_avg": "running_mean",
        "exponential_running_mean": "exponential_running_mean",
        "ewma": "exponential_running_mean",
    }
    return aliases.get(token, "")


def _normalize_density_setting(value: Any) -> str:
    token = _setting_token(value)
    aliases = {
        "wpl": "wpl",
        "webb_pearman_leuning": "wpl",
        "density_correction": "wpl",
        "mixing_ratio": "mixing_ratio",
        "mixing_ratio_priority": "mixing_ratio",
        "none": "none",
        "no": "none",
        "no_correction": "none",
        "false": "none",
        "raw": "none",
    }
    return aliases.get(token, "")


def _normalize_lag_setting(value: Any) -> str:
    token = _setting_token(value)
    aliases = {
        "none": "none",
        "no_lag": "none",
        "constant": "constant",
        "fixed": "constant",
        "covariance_max": "covariance_max",
        "covariance": "covariance_max",
        "cov_max": "covariance_max",
        "automatic": "covariance_max",
        "auto": "covariance_max",
        "covariance_max_with_default": "covariance_max_with_default",
        "cov_max_default": "covariance_max_with_default",
    }
    return aliases.get(token, "")


def _normalize_footprint_setting(value: Any) -> str:
    token = _setting_token(value)
    aliases = {
        "kljun": "kljun",
        "kormann": "kormann_meixner",
        "kormann_meixner": "kormann_meixner",
        "km": "kormann_meixner",
        "hsieh": "hsieh",
    }
    return aliases.get(token, "")


def _normalize_uncertainty_setting(value: Any) -> str:
    token = _setting_token(value)
    aliases = {
        "mann_lenschow": "mann_lenschow",
        "mann_and_lenschow": "mann_lenschow",
        "finkelstein_sims": "finkelstein_sims",
        "finkelstein_and_sims": "finkelstein_sims",
    }
    return aliases.get(token, "")


def _normalize_qc_setting(value: Any) -> str:
    token = _setting_token(value)
    aliases = {
        "0": "none",
        "none": "none",
        "1": "mauder_foken_04",
        "mauder": "mauder_foken_04",
        "mauder_foken": "mauder_foken_04",
        "mauder_foken_04": "mauder_foken_04",
        "mauder_foken_2004": "mauder_foken_04",
        "2": "foken_03",
        "foken": "foken_03",
        "foken_03": "foken_03",
        "foken_2003": "foken_03",
        "3": "goeckede_06",
        "goeckede": "goeckede_06",
        "goeckede_06": "goeckede_06",
        "goeckede_2006": "goeckede_06",
    }
    return aliases.get(token, "")


def _normalize_eddypro_lf_setting(value: Any) -> str:
    token = _setting_token(value)
    aliases = {
        "0": "none",
        "none": "none",
        "no": "none",
        "1": "analytic",
        "analytic": "analytic",
        "theoretical": "analytic",
    }
    return aliases.get(token, "")


def _normalize_eddypro_hf_setting(value: Any) -> str:
    token = _setting_token(value)
    aliases = {
        "0": "none",
        "none": "none",
        "1": "moncrieff_97",
        "moncrieff": "moncrieff_97",
        "moncrieff_97": "moncrieff_97",
        "moncrieff1997": "moncrieff_97",
        "2": "horst",
        "horst": "horst",
        "horst_97": "horst",
        "3": "ibrom",
        "ibrom": "ibrom",
        "ibrom_07": "ibrom",
        "4": "fratini",
        "fratini": "fratini",
        "fratini_12": "fratini",
        "5": "massman",
        "massman": "massman",
        "massman_00": "massman",
        "6": "custom",
        "custom": "custom",
    }
    return aliases.get(token, "")


def _normalize_spectral_setting(value: Any) -> str:
    token = _setting_token(value)
    aliases = {
        "moncrieff": "moncrieff_97",
        "moncrieff_97": "moncrieff_97",
        "moncrieff1997": "moncrieff_97",
        "massman": "massman",
        "massman_00": "massman",
        "horst": "horst",
        "horst_97": "horst",
        "ibrom": "ibrom",
        "ibrom_07": "ibrom",
        "fratini": "fratini",
        "fratini_12": "fratini",
        "none": "none",
    }
    return aliases.get(token, "")


def _truthy_setting(value: Any) -> bool | None:
    token = _setting_token(value)
    if not token:
        return None
    if token in {"1", "true", "yes", "y", "on", "enabled", "enable", "apply", "applied"}:
        return True
    if token in {"0", "false", "no", "n", "off", "disabled", "disable", "none", "no_correction", "not_used"}:
        return False
    return True


def _set_str_if_present(target: dict[str, Any], output_key: str, settings: dict[str, str], setting_keys: tuple[str, ...]) -> None:
    value = _first_setting(settings, setting_keys)
    if value not in ("", None):
        target[output_key] = str(value).strip()


def _set_float_if_present(target: dict[str, Any], output_key: str, settings: dict[str, str], setting_keys: tuple[str, ...]) -> None:
    value = _optional_float(_first_setting(settings, setting_keys))
    if value is not None:
        target[output_key] = value


def _list_setting(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    return [item.strip().strip('"').strip("'") for item in re.split(r"[,;|]+", str(value)) if item.strip()]


def _int_list_setting(value: Any) -> list[int]:
    values: list[int] = []
    for item in _list_setting(value):
        try:
            values.append(int(item, 0))
            continue
        except ValueError:
            pass
        number = _optional_float(item)
        if number is not None:
            values.append(int(number))
    return values


def _status_bit_map_setting(value: Any) -> dict[int, str]:
    if value in (None, ""):
        return {}
    mapping: dict[int, str] = {}
    for item in _list_setting(value):
        if ":" not in item and "=" not in item:
            continue
        separator = ":" if ":" in item else "="
        key, label = item.split(separator, 1)
        key = key.strip().lower().removeprefix("bit")
        try:
            mapping[int(key, 0)] = label.strip()
        except ValueError:
            continue
    return mapping


def _string_list(value: Any) -> list[str]:
    if value in (None, ""):
        return []
    if isinstance(value, (list, tuple, set)):
        return [str(item) for item in value if str(item)]
    return _list_setting(value)


def _crosswind_coefficients_from_settings(settings: dict[str, str]) -> dict[str, list[float]]:
    coefficients: dict[str, list[float]] = {}
    for output_key, setting_keys in [
        ("A", ("crosswind_coefficients_a", "crosswind_a")),
        ("B", ("crosswind_coefficients_b", "crosswind_b")),
        ("C", ("crosswind_coefficients_c", "crosswind_c")),
    ]:
        values: list[float] = []
        for item in _list_setting(_first_setting(settings, setting_keys)):
            try:
                values.append(float(item))
            except ValueError:
                values = []
                break
        if values:
            coefficients[output_key] = values
    if {"A", "B", "C"}.issubset(coefficients) and all(len(coefficients[key]) == 3 for key in ("A", "B", "C")):
        return coefficients
    return {}


def _discover_bundle_file(bundle_root: Path | None, *, stems: tuple[str, ...], suffixes: tuple[str, ...]) -> Path | None:
    if bundle_root is None or not bundle_root.exists():
        return None
    candidates: list[Path] = []
    for path in bundle_root.rglob("*"):
        if not path.is_file() or path.name in BUNDLE_MANIFEST_NAMES:
            continue
        lower = "/".join(part.lower() for part in path.relative_to(bundle_root).parts)
        if path.suffix.lower() in suffixes and any(stem in lower for stem in stems):
            candidates.append(path)
    return sorted(candidates, key=lambda item: (len(item.parts), str(item)))[0] if candidates else None


def _discover_li7700_coefficient_file(bundle_root: Path | None) -> Path | None:
    if bundle_root is None or not bundle_root.exists():
        return None
    suffixes = {".json", ".csv", ".txt", ".yaml", ".yml", ".ini", ".metadata"}
    candidates: list[Path] = []
    for path in bundle_root.rglob("*"):
        if not path.is_file() or path.name in BUNDLE_MANIFEST_NAMES or path.suffix.lower() not in suffixes:
            continue
        lower = "/".join(part.lower() for part in path.relative_to(bundle_root).parts)
        family_match = any(token in lower for token in ("li7700", "li_7700", "li-7700", "methane", "ch4"))
        coefficient_match = any(token in lower for token in ("coefficient", "coeff", "profile", "calibration", "wms"))
        if family_match and coefficient_match:
            candidates.append(path)
    return sorted(candidates, key=lambda item: ("/raw/" in f"/{'/'.join(item.relative_to(bundle_root).parts).lower()}/", len(item.parts), str(item)))[0] if candidates else None


def _resolve_bundle_path(value: str, bundle_root: Path | None) -> Path | None:
    if not value:
        return None
    path = Path(str(value))
    if path.is_absolute():
        return path if path.exists() else None
    if bundle_root is not None:
        candidate = bundle_root / path
        if candidate.exists():
            return candidate
        name_match = next((item for item in bundle_root.rglob(path.name) if item.is_file()), None)
        if name_match is not None:
            return name_match
    return None


def _li7700_profile_from_file(path: Path | None, *, profile_id: str = "") -> dict[str, Any]:
    if path is None or not path.exists() or not path.is_file():
        return {}
    if path.suffix.lower() == ".json":
        payload = _read_json(path)
        if not payload:
            return {}
        for container_key in ("profiles", "coefficient_profiles", "li7700_profiles", "li7700_coefficient_registry"):
            container = payload.get(container_key)
            if isinstance(container, dict):
                if profile_id and isinstance(container.get(profile_id), dict):
                    profile = dict(container[profile_id])
                    profile.setdefault("profile_id", profile_id)
                    return profile
                first = next((value for value in container.values() if isinstance(value, dict)), None)
                if isinstance(first, dict):
                    return dict(first)
            if isinstance(container, list):
                for item in container:
                    if not isinstance(item, dict):
                        continue
                    candidate_id = str(item.get("profile_id", item.get("id", item.get("coefficient_profile_id", ""))))
                    if not profile_id or candidate_id == profile_id:
                        profile = dict(item)
                        if candidate_id:
                            profile.setdefault("profile_id", candidate_id)
                        return profile
        if any(
            key in payload
            for key in (
                "profile_id",
                "coefficient_profile_id",
                "spectroscopic_correction",
                "self_heating_correction",
                "known_limitations",
                "instrument_family",
            )
        ):
            return dict(payload)
    return {"source": "auto_discovered_bundle_file"}


def _portable_bundle_path(path: Path, bundle_root: Path | None) -> str:
    if bundle_root is not None and _is_relative_to(path, bundle_root):
        return str(path.relative_to(bundle_root)).replace("\\", "/")
    return str(path)


def _data_fields_from_header(path: Path) -> list[str]:
    try:
        header = path.read_text(encoding="utf-8", errors="ignore").splitlines()[0]
    except (IndexError, OSError):
        return []
    delimiter = "\t" if "\t" in header else ","
    fields = [item.strip().strip('"').strip("'") for item in header.split(delimiter) if item.strip()]
    return [field for field in fields if _normalize_setting_key(field) not in {"timestamp", "time", "datetime", "date_time", "date"}]


def _setting_token(value: Any) -> str:
    token = str(value or "").strip().lower()
    token = re.sub(r"[^a-z0-9]+", "_", token)
    return token.strip("_")


def _optional_float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(str(value).strip())
    except ValueError:
        return None


def _merge_config(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _merge_config(dict(merged[key]), value)
        else:
            merged[key] = deepcopy(value)
    return merged


def _reference_window_minutes(reference_payload: dict[str, Any]) -> float | None:
    windows = list(reference_payload.get("windows", []) or [])
    if not windows:
        return None
    first = dict(windows[0] or {})
    try:
        start = datetime.fromisoformat(str(first.get("start_time", "")))
        end = datetime.fromisoformat(str(first.get("end_time", "")))
    except ValueError:
        return None
    duration_min = (end - start).total_seconds() / 60.0
    return duration_min if duration_min > 0 else None


def _workspace_path(claim: dict[str, Any], root: Path) -> str:
    path = Path(str(claim.get("path", "")))
    return str(path.relative_to(root)) if _is_relative_to(path, root) else str(path)


def _public_declared_manifest(declared: dict[str, Any]) -> dict[str, Any]:
    return {
        "fixture_id": declared.get("fixture_id", ""),
        "site_class": declared.get("site_class", ""),
        "software": declared.get("software", ""),
        "software_version": declared.get("software_version", ""),
        "file_roles": sorted(_declared_file_roles(declared)),
        "has_official_eddypro_run": isinstance(declared.get("official_eddypro_run", declared.get("eddypro_run")), dict),
        "has_official_run_normalization": isinstance(declared.get("official_run_normalization_result"), dict)
        and bool(dict(declared.get("official_run_normalization_result", {}) or {}).get("reference_json")),
        "has_import_plan": isinstance(declared.get("import_plan"), dict),
        "has_rp_config": isinstance(declared.get("rp_config"), dict),
        "has_thresholds": isinstance(declared.get("thresholds"), dict),
    }


def _safe_fixture_id(value: str) -> str:
    cleaned = "".join(char.lower() if char.isalnum() else "_" for char in value.strip())
    return "_".join(part for part in cleaned.split("_") if part) or "official_raw_fixture"


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest().upper()
