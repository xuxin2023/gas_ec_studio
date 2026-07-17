from __future__ import annotations


PUBLIC_REFERENCE_REPLACEMENTS = (
    ("official_eddypro_executable_run", "official_validation_run"),
    ("official_eddypro_run_checklist", "official_validation_run_checklist"),
    ("official_eddypro_run", "official_validation_run"),
    ("public_eddypro_fixture_catalog", "public_validation_fixture_catalog"),
    ("public_eddypro_claim_boundary", "public_validation_claim_boundary"),
    ("public_eddypro_acquisition", "public_validation_acquisition"),
    ("public_eddypro_dataset", "public_validation_dataset"),
    ("eddypro_computation_stress_suite", "validation_computation_stress_suite"),
    ("eddypro_computation_scope_audit", "validation_computation_scope_audit"),
    ("eddypro_partial_capability_closure", "validation_partial_capability_closure"),
    ("eddypro_surrogate_evidence_closure", "validation_surrogate_evidence_closure"),
    ("eddypro_coverage_audit", "validation_coverage_audit"),
    ("eddypro_release_gate", "validation_release_gate"),
    ("eddypro_closure_gate", "validation_closure_gate"),
    ("eddypro_export_cache", "validation_export_cache"),
    ("eddypro_gap_", "validation_gap_"),
    ("eddypro_closure_", "validation_closure_"),
    ("eddypro_compare", "result_validation"),
    ("eddypro_", "validation_"),
    ("reference_compare", "result_validation"),
    ("行业参考", "系统验证"),
    ("raw-to-final", "端到端"),
    ("parity", "一致性"),
    ("EddyPro", "验证引擎"),
    ("EDDYPRO", "验证引擎"),
    ("eddypro", "validation"),
)

PUBLIC_FORBIDDEN_TOKENS = ("EddyPro", "EDDYPRO", "eddypro", "行业参考", "raw-to-final")


def public_safe_text(value: object) -> str:
    text = str(value)
    for old, new in PUBLIC_REFERENCE_REPLACEMENTS:
        text = text.replace(old, new)
    return text


def find_public_text_violations(values: object) -> list[str]:
    text = "\n".join(str(value) for value in values) if isinstance(values, (list, tuple, set)) else str(values)
    return [token for token in PUBLIC_FORBIDDEN_TOKENS if token in text]
