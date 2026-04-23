from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from statistics import fmean
from typing import Any
from uuid import uuid4

import pandas as pd

from models.comparison_models import EddyProCompareResult, WindowCompareResult


@dataclass(slots=True)
class _ComparableWindow:
    window_key: str
    start_time: datetime | None
    end_time: datetime | None
    lag_seconds: float | None = None
    flux: float | None = None
    correction_factor: float | None = None
    qc_grade: str | None = None
    notes: list[str] = field(default_factory=list)


class EddyProComparator:
    def __init__(self, runtime_root: Path | str | None = None, *, match_tolerance_seconds: float = 60.0) -> None:
        self.runtime_root = Path(runtime_root) if runtime_root is not None else Path("runtime_data")
        self.match_tolerance_seconds = float(match_tolerance_seconds)

    def load_current_results(self, export_dir: Path | str) -> dict[str, Any]:
        export_root = Path(export_dir)
        rp_path = export_root / "rp_results.csv"
        spectral_path = export_root / "spectral_qc_results.csv"
        summary_path = export_root / "summary.json"
        config_path = export_root / "config_snapshot.json"
        site_path = export_root / "project_site_snapshot.json"

        rp_windows = self._load_windows_from_csv(rp_path, source_label="current:rp") if rp_path.exists() else []
        spectral_windows = (
            self._load_windows_from_csv(spectral_path, source_label="current:spectral") if spectral_path.exists() else []
        )
        merged_windows = self._merge_current_windows(rp_windows, spectral_windows)

        return {
            "source_type": "current_results",
            "export_dir": export_root,
            "files": {
                "rp_results": rp_path if rp_path.exists() else None,
                "spectral_qc_results": spectral_path if spectral_path.exists() else None,
                "summary": summary_path if summary_path.exists() else None,
                "config_snapshot": config_path if config_path.exists() else None,
                "project_site_snapshot": site_path if site_path.exists() else None,
            },
            "summary": self._load_json(summary_path),
            "config_snapshot": self._load_json(config_path),
            "project_site_snapshot": self._load_json(site_path),
            "windows": merged_windows,
        }

    def load_reference_results(self, reference_dir: Path | str, mapping: dict | None = None) -> dict[str, Any]:
        reference_root = Path(reference_dir)
        resolved = self._resolve_reference_mapping(reference_root, mapping or {})
        window_rows = self._load_windows_from_csv(resolved["window_csv"], source_label="reference:window_csv")

        return {
            "source_type": "reference_results",
            "reference_dir": reference_root,
            "mapping": {key: str(value) for key, value in resolved.items()},
            "summary": self._load_json(resolved.get("summary_json")),
            "metadata": self._load_json(resolved.get("metadata_json")),
            "windows": window_rows,
        }

    def compare(self, current: dict[str, Any], reference: dict[str, Any]) -> EddyProCompareResult:
        created_at = datetime.now(UTC).replace(tzinfo=None)
        compare_id = f"compare_{created_at:%Y%m%d_%H%M%S}_{uuid4().hex[:8]}"

        current_windows = list(current.get("windows", []))
        reference_windows = list(reference.get("windows", []))
        matched_pairs, unmatched_current, unmatched_reference = self._match_windows(current_windows, reference_windows)

        window_results: list[WindowCompareResult] = []
        lag_deltas: list[float] = []
        flux_deltas: list[float] = []
        correction_deltas: list[float] = []
        qc_matches = 0

        for current_window, reference_window, match_note in matched_pairs:
            result = self._build_window_compare_result(current_window, reference_window, match_note)
            window_results.append(result)
            if result.lag_delta is not None:
                lag_deltas.append(abs(result.lag_delta))
            if result.flux_delta is not None:
                flux_deltas.append(abs(result.flux_delta))
            if result.correction_factor_delta is not None:
                correction_deltas.append(abs(result.correction_factor_delta))
            if result.qc_match:
                qc_matches += 1

        for current_window in unmatched_current:
            window_results.append(
                self._build_window_compare_result(current_window, None, "current window has no matched EddyPro reference window")
            )
        for reference_window in unmatched_reference:
            window_results.append(
                self._build_window_compare_result(None, reference_window, "reference window has no matched current result window")
            )

        matched_window_count = len(matched_pairs)
        summary_metrics = {
            "compare_id": compare_id,
            "created_at": created_at.isoformat(),
            "current_window_count": len(current_windows),
            "reference_window_count": len(reference_windows),
            "matched_window_count": matched_window_count,
            "unmatched_current_count": len(unmatched_current),
            "unmatched_reference_count": len(unmatched_reference),
            "avg_lag_delta": self._average_or_none(lag_deltas),
            "avg_flux_delta": self._average_or_none(flux_deltas),
            "avg_correction_factor_delta": self._average_or_none(correction_deltas),
            "qc_match_ratio": (qc_matches / matched_window_count) if matched_window_count else 0.0,
        }
        risk_summary = self._build_risk_summary(summary_metrics)
        summary_metrics["risk_summary"] = list(risk_summary)

        notes = []
        if not current.get("files", {}).get("rp_results"):
            notes.append("rp_results.csv missing from current export; lag/flux fields may rely on other files")
        if not current.get("files", {}).get("spectral_qc_results"):
            notes.append("spectral_qc_results.csv missing from current export; correction/qc fields may be incomplete")

        return EddyProCompareResult(
            compare_id=compare_id,
            created_at=created_at,
            current_source=self._source_payload(current),
            reference_source=self._source_payload(reference),
            summary_metrics=summary_metrics,
            window_results=window_results,
            risk_summary=risk_summary,
            notes=notes,
        )

    def export(self, compare_result: EddyProCompareResult, output_dir: Path | str) -> dict[str, Any]:
        output_root = Path(output_dir)
        if output_root.name.startswith("compare_"):
            compare_root = output_root
        else:
            compare_root = output_root / f"compare_{compare_result.created_at:%Y%m%d_%H%M%S}"
        compare_root.mkdir(parents=True, exist_ok=True)

        summary_path = compare_root / "compare_summary.json"
        windows_path = compare_root / "compare_windows.csv"
        manifest_path = compare_root / "compare_manifest.json"

        summary_payload = dict(compare_result.summary_metrics)
        summary_payload["compare_id"] = compare_result.compare_id
        summary_payload["created_at"] = compare_result.created_at.isoformat()
        summary_path.write_text(json.dumps(summary_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        fieldnames = [
            "window_key",
            "start_time",
            "end_time",
            "current_lag_seconds",
            "reference_lag_seconds",
            "lag_delta",
            "current_flux",
            "reference_flux",
            "flux_delta",
            "current_correction_factor",
            "reference_correction_factor",
            "correction_factor_delta",
            "current_qc_grade",
            "reference_qc_grade",
            "qc_match",
            "notes",
        ]
        with windows_path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            for window in compare_result.window_results:
                row = window.to_dict()
                row["notes"] = " | ".join(window.notes)
                writer.writerow(row)

        manifest_payload = {
            "compare_id": compare_result.compare_id,
            "created_at": compare_result.created_at.isoformat(),
            "export_root": str(compare_root),
            "files": {
                "compare_summary": str(summary_path),
                "compare_windows": str(windows_path),
                "compare_manifest": str(manifest_path),
            },
            "current_source": compare_result.current_source,
            "reference_source": compare_result.reference_source,
            "summary_metrics": compare_result.summary_metrics,
            "risk_summary": compare_result.risk_summary,
            "notes": compare_result.notes,
        }
        manifest_path.write_text(json.dumps(self._jsonable(manifest_payload), ensure_ascii=False, indent=2), encoding="utf-8")

        return manifest_payload

    def build_attribution(
        self,
        compare_result: EddyProCompareResult,
        *,
        current_runs: dict[str, Any] | None = None,
        reference_meta: dict[str, Any] | None = None,
    ) -> Any:
        from core.comparison.attribution import classify_compare_result

        return classify_compare_result(compare_result, current_runs=current_runs, reference_meta=reference_meta)

    def default_export_root(self) -> Path:
        return self.runtime_root / "exports" / "eddypro_compare"

    def _load_windows_from_csv(self, path: Path, *, source_label: str) -> list[_ComparableWindow]:
        if not path.exists():
            return []
        frame = pd.read_csv(path)
        if frame.empty:
            return []

        windows: list[_ComparableWindow] = []
        for row in frame.to_dict(orient="records"):
            start_time = self._pick_datetime(row, ("start_time", "start", "window_start", "start_timestamp", "date_start"))
            end_time = self._pick_datetime(row, ("end_time", "end", "window_end", "end_timestamp", "date_end"))
            window_key = self._window_key(
                row=row,
                start_time=start_time,
                end_time=end_time,
                fallback_prefix=source_label,
            )
            notes: list[str] = []
            if start_time is None or end_time is None:
                notes.append("window timestamp incomplete")
            flux = self._pick_float(
                row,
                (
                    "density_corrected_flux",
                    "corrected_flux_after",
                    "corrected_flux",
                    "flux",
                    "co2_flux",
                    "fc",
                    "Fc",
                    "raw_flux",
                ),
            )
            if flux is None:
                notes.append("flux field missing")
            correction_factor = self._pick_float(
                row,
                ("correction_factor", "spectral_correction_factor", "correction", "cf"),
            )
            if correction_factor is None:
                notes.append("correction_factor missing")
            qc_grade = self._pick_string(row, ("qc_grade", "qc", "qc_class", "qc_flag", "flag_qc"))
            if qc_grade is None:
                notes.append("qc_grade missing")
            windows.append(
                _ComparableWindow(
                    window_key=window_key,
                    start_time=start_time,
                    end_time=end_time,
                    lag_seconds=self._pick_float(row, ("lag_seconds", "lag", "lag_s", "time_lag")),
                    flux=flux,
                    correction_factor=correction_factor,
                    qc_grade=qc_grade,
                    notes=notes,
                )
            )
        return windows

    def _merge_current_windows(
        self,
        rp_windows: list[_ComparableWindow],
        spectral_windows: list[_ComparableWindow],
    ) -> list[_ComparableWindow]:
        merged: dict[str, _ComparableWindow] = {}
        for window in rp_windows:
            merged[window.window_key] = self._clone_window(window)
        for window in spectral_windows:
            existing = merged.get(window.window_key)
            if existing is None:
                merged[window.window_key] = self._clone_window(window)
                continue
            merged[window.window_key] = _ComparableWindow(
                window_key=existing.window_key,
                start_time=existing.start_time or window.start_time,
                end_time=existing.end_time or window.end_time,
                lag_seconds=existing.lag_seconds if existing.lag_seconds is not None else window.lag_seconds,
                flux=existing.flux if existing.flux is not None else window.flux,
                correction_factor=(
                    existing.correction_factor if existing.correction_factor is not None else window.correction_factor
                ),
                qc_grade=existing.qc_grade or window.qc_grade,
                notes=[*existing.notes, *[note for note in window.notes if note not in existing.notes]],
            )
        return sorted(merged.values(), key=lambda item: (item.start_time or datetime.min, item.end_time or datetime.min))

    def _clone_window(self, window: _ComparableWindow) -> _ComparableWindow:
        return _ComparableWindow(
            window_key=window.window_key,
            start_time=window.start_time,
            end_time=window.end_time,
            lag_seconds=window.lag_seconds,
            flux=window.flux,
            correction_factor=window.correction_factor,
            qc_grade=window.qc_grade,
            notes=list(window.notes),
        )

    def _resolve_reference_mapping(self, reference_root: Path, mapping: dict[str, Any]) -> dict[str, Path]:
        resolved: dict[str, Path] = {}
        if "window_csv" in mapping:
            resolved["window_csv"] = self._resolve_path(reference_root, mapping["window_csv"])
        else:
            csv_files = sorted(reference_root.glob("*.csv"))
            if not csv_files:
                raise FileNotFoundError("reference window CSV not found; pass mapping['window_csv']")
            resolved["window_csv"] = csv_files[0]

        for key in ("summary_json", "metadata_json"):
            if key in mapping:
                resolved[key] = self._resolve_path(reference_root, mapping[key])
            else:
                candidates = sorted(reference_root.glob("*.json"))
                if len(candidates) == 1:
                    resolved[key] = candidates[0]
                elif key == "summary_json":
                    match = next((path for path in candidates if "summary" in path.name.lower()), None)
                    if match is not None:
                        resolved[key] = match
                elif key == "metadata_json":
                    match = next((path for path in candidates if "meta" in path.name.lower()), None)
                    if match is not None:
                        resolved[key] = match
        return resolved

    def _resolve_path(self, root: Path, raw_path: Any) -> Path:
        path = Path(str(raw_path))
        return path if path.is_absolute() else root / path

    def _match_windows(
        self,
        current_windows: list[_ComparableWindow],
        reference_windows: list[_ComparableWindow],
    ) -> tuple[list[tuple[_ComparableWindow, _ComparableWindow, str | None]], list[_ComparableWindow], list[_ComparableWindow]]:
        matched_pairs: list[tuple[_ComparableWindow, _ComparableWindow, str | None]] = []
        unmatched_current: list[_ComparableWindow] = []
        reference_remaining = list(reference_windows)
        strict_lookup: dict[tuple[datetime | None, datetime | None], list[_ComparableWindow]] = {}
        for window in reference_remaining:
            strict_lookup.setdefault((window.start_time, window.end_time), []).append(window)

        for current_window in current_windows:
            strict_key = (current_window.start_time, current_window.end_time)
            strict_candidates = strict_lookup.get(strict_key, [])
            if strict_candidates:
                reference_window = strict_candidates.pop(0)
                reference_remaining.remove(reference_window)
                matched_pairs.append((current_window, reference_window, None))
                continue

            best_match = self._closest_window(current_window, reference_remaining)
            if best_match is None:
                unmatched_current.append(current_window)
                continue
            reference_remaining.remove(best_match)
            matched_pairs.append((current_window, best_match, "matched within time tolerance"))

        return matched_pairs, unmatched_current, reference_remaining

    def _closest_window(
        self,
        current_window: _ComparableWindow,
        candidates: list[_ComparableWindow],
    ) -> _ComparableWindow | None:
        best_window: _ComparableWindow | None = None
        best_distance: float | None = None
        for candidate in candidates:
            distance = self._window_distance_seconds(current_window, candidate)
            if distance is None or distance > self.match_tolerance_seconds:
                continue
            if best_distance is None or distance < best_distance:
                best_window = candidate
                best_distance = distance
        return best_window

    def _window_distance_seconds(self, left: _ComparableWindow, right: _ComparableWindow) -> float | None:
        if left.start_time is None or right.start_time is None:
            return None
        start_delta = abs((left.start_time - right.start_time).total_seconds())
        if left.end_time is None or right.end_time is None:
            return start_delta
        end_delta = abs((left.end_time - right.end_time).total_seconds())
        return max(start_delta, end_delta)

    def _build_window_compare_result(
        self,
        current_window: _ComparableWindow | None,
        reference_window: _ComparableWindow | None,
        match_note: str | None,
    ) -> WindowCompareResult:
        notes: list[str] = []
        start_time = current_window.start_time if current_window is not None else reference_window.start_time
        end_time = current_window.end_time if current_window is not None else reference_window.end_time
        window_key = (
            current_window.window_key
            if current_window is not None
            else reference_window.window_key if reference_window is not None else "unknown_window"
        )

        if current_window is not None:
            notes.extend(current_window.notes)
        if reference_window is not None:
            notes.extend(note for note in reference_window.notes if note not in notes)
        if match_note:
            notes.append(match_note)

        current_lag = current_window.lag_seconds if current_window is not None else None
        reference_lag = reference_window.lag_seconds if reference_window is not None else None
        current_flux = current_window.flux if current_window is not None else None
        reference_flux = reference_window.flux if reference_window is not None else None
        current_cf = current_window.correction_factor if current_window is not None else None
        reference_cf = reference_window.correction_factor if reference_window is not None else None
        current_qc = current_window.qc_grade if current_window is not None else None
        reference_qc = reference_window.qc_grade if reference_window is not None else None

        return WindowCompareResult(
            window_key=window_key,
            start_time=start_time,
            end_time=end_time,
            current_lag_seconds=current_lag,
            reference_lag_seconds=reference_lag,
            lag_delta=self._delta(current_lag, reference_lag),
            current_flux=current_flux,
            reference_flux=reference_flux,
            flux_delta=self._delta(current_flux, reference_flux),
            current_correction_factor=current_cf,
            reference_correction_factor=reference_cf,
            correction_factor_delta=self._delta(current_cf, reference_cf),
            current_qc_grade=current_qc,
            reference_qc_grade=reference_qc,
            qc_match=(current_qc == reference_qc) if current_qc is not None and reference_qc is not None else None,
            notes=notes,
        )

    def _build_risk_summary(self, summary_metrics: dict[str, Any]) -> list[str]:
        risks: list[str] = []
        avg_lag_delta = summary_metrics.get("avg_lag_delta")
        avg_flux_delta = summary_metrics.get("avg_flux_delta")
        qc_match_ratio = float(summary_metrics.get("qc_match_ratio") or 0.0)

        if avg_lag_delta is not None and avg_lag_delta > 1.0:
            risks.append(f"lag 偏差偏大：平均绝对偏差 {avg_lag_delta:.3f} s")
        if avg_flux_delta is not None and avg_flux_delta > 0.1:
            risks.append(f"flux 偏差偏大：平均绝对偏差 {avg_flux_delta:.6f}")
        if summary_metrics.get("matched_window_count", 0) and qc_match_ratio < 0.8:
            risks.append(f"qc 等级一致性偏低：匹配比例 {qc_match_ratio:.1%}")
        if not risks:
            risks.append("当前未发现显著 lag/flux/qc 对标风险")
        return risks

    def _source_payload(self, source: dict[str, Any]) -> dict[str, Any]:
        payload = {key: value for key, value in source.items() if key != "windows"}
        payload["window_count"] = len(source.get("windows", []))
        return self._jsonable(payload)

    def _load_json(self, path: Path | None) -> dict[str, Any]:
        if path is None or not path.exists():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return {}

    def _window_key(
        self,
        *,
        row: dict[str, Any],
        start_time: datetime | None,
        end_time: datetime | None,
        fallback_prefix: str,
    ) -> str:
        explicit = self._pick_string(row, ("window_key", "window_id", "id", "record"))
        if explicit:
            return explicit
        if start_time is not None or end_time is not None:
            return f"{start_time.isoformat() if start_time else 'none'}__{end_time.isoformat() if end_time else 'none'}"
        return f"{fallback_prefix}_{uuid4().hex[:8]}"

    def _pick_datetime(self, row: dict[str, Any], keys: tuple[str, ...]) -> datetime | None:
        for key in keys:
            if key not in row:
                continue
            value = row.get(key)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            try:
                parsed = pd.to_datetime(value, utc=False)
            except Exception:
                continue
            if pd.isna(parsed):
                continue
            if isinstance(parsed, pd.Timestamp):
                if parsed.tzinfo is not None:
                    parsed = parsed.tz_convert(None)
                return parsed.to_pydatetime()
            if isinstance(parsed, datetime):
                return parsed
        return None

    def _pick_float(self, row: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            if key not in row:
                continue
            value = row.get(key)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            try:
                return float(value)
            except (TypeError, ValueError):
                continue
        return None

    def _pick_string(self, row: dict[str, Any], keys: tuple[str, ...]) -> str | None:
        for key in keys:
            if key not in row:
                continue
            value = row.get(key)
            if value is None or (isinstance(value, float) and pd.isna(value)):
                continue
            text = str(value).strip()
            if text:
                return text
        return None

    def _delta(self, current_value: float | None, reference_value: float | None) -> float | None:
        if current_value is None or reference_value is None:
            return None
        return current_value - reference_value

    def _average_or_none(self, values: list[float]) -> float | None:
        return fmean(values) if values else None

    def _jsonable(self, payload: Any) -> Any:
        if isinstance(payload, dict):
            return {key: self._jsonable(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._jsonable(item) for item in payload]
        if isinstance(payload, datetime):
            return payload.isoformat()
        if isinstance(payload, Path):
            return str(payload)
        return payload
