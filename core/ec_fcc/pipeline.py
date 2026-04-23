from __future__ import annotations

from dataclasses import asdict
from datetime import datetime
from uuid import uuid4

import numpy as np

from core.ec_fcc.analysis import (
    analyze_lag,
    build_velocity_proxy,
    correction_factor,
    cross_spectrum,
    flux_estimate,
    infer_sample_rate,
    ogive_curve,
    pick_window_slices,
    power_spectrum,
    series_from_rows,
    transfer_function_provenance,
    transfer_function,
)
from core.ec_fcc.qc import classify_window_qc
from models.hf_models import NormalizedHFFrame
from models.spectral_models import SpectralRunResult, WindowSpectralResult
from models.station_models import ProjectProfile, SiteProfile


class ECFCCPipeline:
    def run(
        self,
        *,
        rows: list[NormalizedHFFrame],
        project: ProjectProfile,
        site: SiteProfile,
        config: dict,
        data_source: str,
        time_range: str,
        qc_only: bool = False,
    ) -> SpectralRunResult:
        created_at = datetime.now()
        run_id = f"spectral_{created_at:%Y%m%d_%H%M%S}_{uuid4().hex[:6]}"

        fallback_rate = float(config.get("sample_hz") or config.get("timing", {}).get("sample_hz") or 10.0)
        sample_rate_hz = infer_sample_rate(rows, fallback_hz=fallback_rate)
        block_minutes = float(config.get("block_minutes") or config.get("timing", {}).get("block_minutes") or 30.0)
        slices = pick_window_slices(len(rows), sample_rate_hz, block_minutes=block_minutes)

        if not rows or not slices:
            return SpectralRunResult(
                run_id=run_id,
                created_at=created_at,
                data_source=data_source,
                time_range=time_range,
                qc_only=qc_only,
                summary=_empty_summary(
                    run_id=run_id,
                    created_at=created_at,
                    sample_rate_hz=sample_rate_hz,
                    config=config,
                    message="当前高频数据不足，无法生成谱修正结果。",
                    project=project,
                    site=site,
                ),
                windows=[],
                artifacts={
                    "project_snapshot": asdict(project),
                    "site_snapshot": asdict(site),
                    "config_snapshot": config,
                    "sample_rate_hz": sample_rate_hz,
                },
            )

        lag_cfg = config.get("lag_phase", {})
        expected_lag_s = float(lag_cfg.get("expected_lag_s", 2.4))
        search_window_s = float(lag_cfg.get("search_window_s", 8.0))
        expected_lag_samples = max(1, int(expected_lag_s * sample_rate_hz))

        correction_cfg = config.get("correction_factor", {})
        factor_cap = float(correction_cfg.get("factor_cap", 1.35))
        windows: list[WindowSpectralResult] = []

        for index, (start, end) in enumerate(slices, start=1):
            window_rows = rows[start:end]
            if len(window_rows) < max(48, int(sample_rate_hz * 8.0)):
                continue

            series = series_from_rows(window_rows)
            vertical_velocity = build_velocity_proxy(series, expected_lag_samples)
            lag_result = analyze_lag(
                vertical_velocity=vertical_velocity,
                co2_series=np.asarray(series["co2"], dtype=float),
                h2o_series=np.asarray(series["h2o"], dtype=float),
                sample_rate_hz=sample_rate_hz,
                search_window_s=search_window_s,
            )
            power_freq, power_ref, power_measured = power_spectrum(np.asarray(series["co2"], dtype=float), sample_rate_hz)
            cross_freq, cross_value = cross_spectrum(
                vertical_velocity,
                np.asarray(series["co2"], dtype=float),
                sample_rate_hz,
            )
            ogive_freq, ogive_value = ogive_curve(cross_freq, cross_value)
            transfer_freq, transfer_value = transfer_function(power_freq, power_ref, power_measured)
            base_factor, loss_ratio = correction_factor(power_freq, power_ref, power_measured)
            provenance = transfer_function_provenance(
                power_freq=power_freq,
                power_ref=power_ref,
                power_measured=power_measured,
                sample_rate_hz=sample_rate_hz,
                config=config,
                series=series,
                lag_seconds=float(lag_result.lag_seconds),
                lag_confidence=float(lag_result.confidence),
                base_factor=float(base_factor),
                factor_cap=float(factor_cap),
            )
            factor = float(provenance.correction_factor_components.get("total_factor", min(base_factor, factor_cap)))

            flux_before = flux_estimate(vertical_velocity, np.asarray(series["co2"], dtype=float))
            flux_after = flux_before * factor
            ogive_final = float(ogive_value[-1]) if ogive_value else 0.0
            lag_disagreement = abs(lag_result.co2_lag_seconds - lag_result.h2o_lag_seconds)
            qc = classify_window_qc(
                lag_confidence=lag_result.confidence,
                correction_factor=factor,
                loss_ratio=loss_ratio,
                ogive_final=ogive_final,
                lag_disagreement_s=lag_disagreement,
            )

            windows.append(
                WindowSpectralResult(
                    window_id=f"{run_id}_w{index:03d}",
                    start_time=window_rows[0].timestamp,
                    end_time=window_rows[-1].timestamp,
                    qc_grade=str(qc["qc_grade"]),
                    anomaly_type=str(qc["anomaly_type"]),
                    lag_seconds=float(lag_result.lag_seconds),
                    lag_confidence=float(lag_result.confidence),
                    correction_factor=float(factor),
                    high_freq_loss_risk=str(qc["high_freq_loss_risk"]),
                    reason=str(qc["reason"]),
                    lag_curve_x=lag_result.lag_curve_x,
                    lag_curve_y=lag_result.lag_curve_y,
                    power_freq=[float(item) for item in power_freq],
                    power_ref=[float(item) for item in power_ref],
                    power_measured=[float(item) for item in power_measured],
                    cross_freq=[float(item) for item in cross_freq],
                    cross_value=[float(item) for item in cross_value],
                    ogive_freq=[float(item) for item in ogive_freq],
                    ogive_value=[float(item) for item in ogive_value],
                    qc_band_value=float(qc["qc_band_value"]),
                    transfer_freq=[float(item) for item in transfer_freq],
                    transfer_value=[float(item) for item in transfer_value],
                    transfer_function_components=provenance.transfer_function_components,
                    correction_factor_components=provenance.correction_factor_components,
                    total_transfer_function_freq=provenance.total_transfer_function_freq,
                    total_transfer_function_value=provenance.total_transfer_function_value,
                    effective_cutoff_info=provenance.effective_cutoff_info,
                    correction_factor_detail=provenance.correction_factor_detail,
                    provenance_notes=provenance.provenance_notes,
                    model_version=provenance.model_version,
                    corrected_flux_before=float(flux_before),
                    corrected_flux_after=float(flux_after),
                    sample_count=len(window_rows),
                )
            )

        summary = _build_summary(
            run_id=run_id,
            created_at=created_at,
            windows=windows,
            sample_rate_hz=sample_rate_hz,
            config=config,
            project=project,
            site=site,
        )
        return SpectralRunResult(
            run_id=run_id,
            created_at=created_at,
            data_source=data_source,
            time_range=time_range,
            qc_only=qc_only,
            summary=summary,
            windows=windows,
            artifacts={
                "project_snapshot": asdict(project),
                "site_snapshot": asdict(site),
                "config_snapshot": config,
                "sample_rate_hz": sample_rate_hz,
                "window_count": len(windows),
            },
        )


def _empty_summary(
    *,
    run_id: str,
    created_at: datetime,
    sample_rate_hz: float,
    config: dict,
    message: str,
    project: ProjectProfile,
    site: SiteProfile,
) -> dict:
    return {
        "status": "empty",
        "message": message,
        "sample_rate_hz": sample_rate_hz,
        "window_count": 0,
        "valid_window_count": 0,
        "good_window_count": 0,
        "attention_window_count": 0,
        "average_lag_seconds": 0.0,
        "average_lag_confidence": 0.0,
        "average_correction_factor": 1.0,
        "average_tube_component": 1.0,
        "average_separation_component": 1.0,
        "average_path_component": 1.0,
        "average_phase_component": 1.0,
        "high_freq_loss_risk": "未知",
        "batch_label": f"{created_at:%Y-%m-%d %H:%M} / {run_id[-6:]}",
        "config_snapshot": config,
        "project_code": project.code,
        "site_code": site.station_code,
    }


def _build_summary(
    *,
    run_id: str,
    created_at: datetime,
    windows: list[WindowSpectralResult],
    sample_rate_hz: float,
    config: dict,
    project: ProjectProfile,
    site: SiteProfile,
) -> dict:
    if not windows:
        return _empty_summary(
            run_id=run_id,
            created_at=created_at,
            sample_rate_hz=sample_rate_hz,
            config=config,
            message="没有可用窗口完成谱分析。",
            project=project,
            site=site,
        )

    lag_confidence = np.array([window.lag_confidence for window in windows], dtype=float)
    correction = np.array([window.correction_factor for window in windows], dtype=float)
    tube_component = np.array([window.correction_factor_components.get("tube_component", 1.0) for window in windows], dtype=float)
    separation_component = np.array(
        [window.correction_factor_components.get("separation_component", 1.0) for window in windows],
        dtype=float,
    )
    path_component = np.array([window.correction_factor_components.get("path_component", 1.0) for window in windows], dtype=float)
    phase_component = np.array([window.correction_factor_components.get("phase_component", 1.0) for window in windows], dtype=float)
    lag_seconds = np.array([window.lag_seconds for window in windows], dtype=float)
    grades = [window.qc_grade for window in windows]
    risk_weights = {"低": 0.0, "中": 1.0, "高": 2.0}
    mean_risk = np.mean([risk_weights.get(window.high_freq_loss_risk, 0.0) for window in windows])
    high_freq_loss_risk = "高" if mean_risk >= 1.4 else ("中" if mean_risk >= 0.5 else "低")

    good_count = sum(1 for grade in grades if grade == "A")
    attention_count = sum(1 for grade in grades if grade in {"B", "C"})
    valid_count = sum(1 for grade in grades if grade in {"A", "B"})

    return {
        "status": "ok",
        "message": "谱分析已完成。",
        "sample_rate_hz": sample_rate_hz,
        "window_count": len(windows),
        "valid_window_count": valid_count,
        "good_window_count": good_count,
        "attention_window_count": attention_count,
        "average_lag_seconds": float(lag_seconds.mean()),
        "average_lag_confidence": float(lag_confidence.mean()),
        "average_correction_factor": float(correction.mean()),
        "average_tube_component": float(tube_component.mean()),
        "average_separation_component": float(separation_component.mean()),
        "average_path_component": float(path_component.mean()),
        "average_phase_component": float(phase_component.mean()),
        "high_freq_loss_risk": high_freq_loss_risk,
        "batch_label": f"{created_at:%Y-%m-%d %H:%M} / {run_id[-6:]}",
        "config_snapshot": config,
        "project_code": project.code,
        "site_code": site.station_code,
    }
