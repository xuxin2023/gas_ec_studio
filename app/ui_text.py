from __future__ import annotations


UI_REFERENCE_REPLACEMENTS = (
    ("official_eddypro_executable_run", "official_reference_run"),
    ("official_eddypro_run_checklist", "official_reference_run_checklist"),
    ("official_eddypro_run", "official_reference_run"),
    ("public_eddypro_fixture_catalog", "public_reference_fixture_catalog"),
    ("public_eddypro_claim_boundary", "public_reference_claim_boundary"),
    ("public_eddypro_acquisition", "public_reference_acquisition"),
    ("public_eddypro_dataset", "public_reference_dataset"),
    ("eddypro_computation_stress_suite", "reference_computation_stress_suite"),
    ("eddypro_computation_scope_audit", "reference_computation_scope_audit"),
    ("eddypro_partial_capability_closure", "reference_partial_capability_closure"),
    ("eddypro_surrogate_evidence_closure", "reference_surrogate_evidence_closure"),
    ("eddypro_coverage_audit", "reference_coverage_audit"),
    ("eddypro_release_gate", "reference_release_gate"),
    ("eddypro_closure_gate", "reference_closure_gate"),
    ("eddypro_export_cache", "reference_export_cache"),
    ("eddypro_gap_", "reference_gap_"),
    ("eddypro_closure_", "reference_closure_"),
    ("eddypro_", "reference_"),
    ("EddyPro", "行业参考"),
    ("EDDYPRO", "行业参考"),
    ("eddypro", "reference"),
)


def ui_safe_text(value: object) -> str:
    text = str(value)
    for old, new in UI_REFERENCE_REPLACEMENTS:
        text = text.replace(old, new)
    return text
