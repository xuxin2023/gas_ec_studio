from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Build the EddyPro parity release gate artifact and return its CI exit code.",
    )
    parser.add_argument("--workspace-root", default=".", help="Repository/workspace root.")
    parser.add_argument("--output", required=True, help="Path to write eddypro_release_gate.json.")
    parser.add_argument("--capability-matrix", default="", help="Optional capability matrix JSON path.")
    parser.add_argument("--fixture-pack", default="", help="Optional fixture pack JSON path.")
    parser.add_argument("--official-raw-evidence-pack", default="", help="Accepted evidence-pack JSON path.")
    parser.add_argument("--official-raw-closure-run", default="", help="Official raw closure-run JSON path.")
    parser.add_argument("--official-raw-bundle", default="", help="Official raw bundle directory used to build evidence.")
    parser.add_argument("--eddypro-computation-scope-audit", default="", help="Existing computation scope audit JSON path.")
    parser.add_argument("--eddypro-computation-stress-suite", default="", help="Existing computation stress suite JSON path.")
    parser.add_argument("--skip-computation-gate", action="store_true", help="Do not build the source-derived computation gate.")
    parser.add_argument("--skip-acceptance", action="store_true", help="Do not rerun evidence-pack acceptance commands.")
    parser.add_argument("--acceptance-timeout-s", type=float, default=300.0, help="Timeout per acceptance command.")
    parser.add_argument(
        "--summary-md",
        default="",
        help="Optional Markdown summary output. Defaults to GITHUB_STEP_SUMMARY when present.",
    )
    args = parser.parse_args(argv)

    workspace_root = Path(args.workspace_root).resolve()
    if str(workspace_root) not in sys.path:
        sys.path.insert(0, str(workspace_root))

    from core.comparison.eddypro_release_gate import build_eddypro_release_gate

    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    gate = build_eddypro_release_gate(
        capability_matrix_path=args.capability_matrix or None,
        fixture_pack_path=args.fixture_pack or None,
        workspace_root=workspace_root,
        official_raw_bundle_dir=args.official_raw_bundle or None,
        official_raw_evidence_pack_path=args.official_raw_evidence_pack or None,
        official_raw_closure_run_path=args.official_raw_closure_run or None,
        computation_scope_audit_path=args.eddypro_computation_scope_audit or None,
        computation_stress_suite_path=args.eddypro_computation_stress_suite or None,
        build_computation_gate=not bool(args.skip_computation_gate),
        output_dir=output_path.parent,
        run_acceptance=not bool(args.skip_acceptance),
        acceptance_timeout_s=float(args.acceptance_timeout_s),
    )
    output_path.write_text(json.dumps(gate, ensure_ascii=False, indent=2), encoding="utf-8")

    summary_path = args.summary_md or os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        _write_summary(Path(summary_path), gate, output_path)

    _print_summary(gate, output_path)
    return int(gate.get("ci_exit_code", 2) or 2)


def _print_summary(gate: dict[str, Any], output_path: Path) -> None:
    summary = dict(gate.get("summary", {}) or {})
    print(f"EddyPro release gate: {gate.get('status', 'blocked')}")
    print(f"can_release_full_eddypro_parity: {gate.get('can_release_full_eddypro_parity', False)}")
    print(
        "can_release_source_derived_functional_parity: "
        f"{gate.get('can_release_source_derived_functional_parity', False)}"
    )
    print(
        "can_release_source_derived_computational_superiority: "
        f"{gate.get('can_release_source_derived_computational_superiority', False)}"
    )
    print(f"surrogate_evidence_closure_status: {gate.get('surrogate_evidence_closure_status', 'not_configured')}")
    print(f"surrogate_ci_exit_code: {gate.get('surrogate_ci_exit_code', 2)}")
    print(f"source_derived_computation_ci_exit_code: {gate.get('source_derived_computation_ci_exit_code', 2)}")
    print(f"source_derived_computation_gate_status: {summary.get('source_derived_computation_gate_status', 'not_supplied')}")
    print(f"computation_surface_status: {summary.get('computation_surface_status', 'not_supplied')}")
    print(f"official_raw_acceptance_gate_status: {summary.get('official_raw_acceptance_gate_status', 'not_run')}")
    print(f"official_raw_closure_run_gate_status: {summary.get('official_raw_closure_run_gate_status', 'not_available')}")
    print(f"capability_completion_score: {summary.get('capability_completion_score', 0.0)}")
    print(f"artifact: {output_path}")
    for reason in list(summary.get("blocking_reasons", []) or [])[:8]:
        print(f"blocker: {reason}")


def _write_summary(path: Path, gate: dict[str, Any], output_path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    summary = dict(gate.get("summary", {}) or {})
    blocking_reasons = list(summary.get("blocking_reasons", []) or [])
    lines = [
        "## EddyPro Release Gate",
        "",
        f"- Status: `{gate.get('status', 'blocked')}`",
        f"- Can release full EddyPro parity: `{gate.get('can_release_full_eddypro_parity', False)}`",
        f"- CI exit code: `{gate.get('ci_exit_code', 2)}`",
        f"- Can release source-derived functional parity: `{gate.get('can_release_source_derived_functional_parity', False)}`",
        f"- Source-derived CI exit code: `{gate.get('surrogate_ci_exit_code', 2)}`",
        f"- Can release source-derived computational superiority: `{gate.get('can_release_source_derived_computational_superiority', False)}`",
        f"- Source-derived computation CI exit code: `{gate.get('source_derived_computation_ci_exit_code', 2)}`",
        f"- Source-derived computation gate: `{summary.get('source_derived_computation_gate_status', 'not_supplied')}`",
        f"- Computation surface: `{summary.get('computation_surface_status', 'not_supplied')}`",
        f"- Surrogate evidence closure: `{gate.get('surrogate_evidence_closure_status', 'not_configured')}`",
        f"- Surrogate accepted items: `{summary.get('surrogate_accepted_item_count', 0)}`",
        f"- Surrogate missing items: `{summary.get('surrogate_missing_item_count', 0)}`",
        f"- Official raw acceptance: `{summary.get('official_raw_acceptance_gate_status', 'not_run')}`",
        f"- Official raw closure run: `{summary.get('official_raw_closure_run_gate_status', 'not_available')}`",
        f"- Capability completion score: `{summary.get('capability_completion_score', 0.0)}`",
        f"- Artifact: `{output_path}`",
        "",
        "> Source-derived functional parity and source-derived computational superiority are narrow software/evidence-chain closures. They must not be described as official field numeric parity, real hardware validation, or vendor-certified EddyPro equivalence.",
    ]
    computation_blockers = list(summary.get("source_derived_computation_blocking_reasons", []) or [])
    if computation_blockers:
        lines.extend(["", "### Computation Gate Blocking Reasons"])
        lines.extend(f"- {reason}" for reason in computation_blockers)
    if blocking_reasons:
        lines.extend(["", "### Blocking Reasons"])
        lines.extend(f"- {reason}" for reason in blocking_reasons)
    else:
        lines.extend(["", "No release blockers were reported."])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
