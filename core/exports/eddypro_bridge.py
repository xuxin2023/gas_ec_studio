from __future__ import annotations

from dataclasses import asdict, is_dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any

from models.hf_models import NormalizedHFFrame


class EddyProBridgeExporter:
    """Minimal EddyPro-style bridge export without copying external implementation."""

    def __init__(self, runtime_root: Path) -> None:
        self.runtime_root = Path(runtime_root)
        self.exports_root = self.runtime_root / "exports" / "eddypro_bridge"
        self.exports_root.mkdir(parents=True, exist_ok=True)

    def export_bridge_bundle(
        self,
        *,
        rows: list[NormalizedHFFrame],
        project: object,
        site: object,
        config_snapshot: dict[str, Any],
        data_source_label: str,
    ) -> dict[str, Any]:
        timestamp = datetime.now()
        export_root = self.exports_root / f"eddypro_bridge_{timestamp:%Y%m%d_%H%M%S}"
        export_root.mkdir(parents=True, exist_ok=True)

        ascii_path = export_root / "hf_ascii.txt"
        metadata_path = export_root / "metadata_snapshot.json"

        ascii_headers = self._headers()
        ascii_rows = [self._row_payload(row) for row in rows]
        self._write_ascii(ascii_path, ascii_headers, ascii_rows)

        metadata_payload = {
            "exported_at": timestamp.isoformat(),
            "format": {
                "kind": "eddypro_bridge_skeleton",
                "encoding": "utf-8",
                "delimiter": "\t",
                "header": True,
            },
            "data_source": {
                "label": data_source_label,
                "row_count": len(rows),
                "time_range": self._time_range(rows),
                "device_ids": sorted({row.device_id for row in rows}),
                "device_uids": sorted({row.device_uid for row in rows}),
            },
            "field_mapping": self._field_mapping(),
            "metadata_snapshot": {
                "project": self._to_jsonable(project),
                "site": self._to_jsonable(site),
                "config_snapshot": self._to_jsonable(config_snapshot),
            },
            "paired_files": {
                "ascii_data_file": str(ascii_path),
                "metadata_file": str(metadata_path),
            },
        }
        metadata_path.write_text(json.dumps(metadata_payload, ensure_ascii=False, indent=2), encoding="utf-8")

        return {
            "export_root": str(export_root),
            "ascii_path": str(ascii_path),
            "metadata_path": str(metadata_path),
            "summary_text": f"Exported validation bridge skeleton with {len(rows)} HF rows.",
        }

    def _headers(self) -> list[str]:
        return [
            "TIMESTAMP",
            "DEVICE_UID",
            "DEVICE_ID",
            "MODE",
            "FRAME_QUALITY",
            "CO2_PPM",
            "H2O_MMOL",
            "PRESSURE_KPA",
            "CHAMBER_TEMP_C",
            "CASE_TEMP_C",
            "U_MPS",
            "V_MPS",
            "W_MPS",
        ]

    def _row_payload(self, row: NormalizedHFFrame) -> list[str]:
        vector = self._wind_vector(row)
        return [
            row.timestamp.isoformat(),
            row.device_uid,
            row.device_id,
            str(row.mode),
            row.frame_quality.value,
            self._format_float(row.co2_ppm),
            self._format_float(row.h2o_mmol),
            self._format_float(row.pressure_kpa),
            self._format_float(row.chamber_temp_c),
            self._format_float(row.case_temp_c),
            self._format_float(vector.get("u")),
            self._format_float(vector.get("v")),
            self._format_float(vector.get("w")),
        ]

    def _wind_vector(self, row: NormalizedHFFrame) -> dict[str, float | None]:
        payload = self._load_json_dict(row.raw_text) or self._load_json_dict(row.status_text or "")
        if not payload:
            return {"u": None, "v": None, "w": None}
        return {
            "u": self._pick_value(payload, ("u", "u_ms", "u_mps", "wind_u")),
            "v": self._pick_value(payload, ("v", "v_ms", "v_mps", "wind_v")),
            "w": self._pick_value(payload, ("w", "w_ms", "w_mps", "vertical_velocity", "vertical_wind")),
        }

    def _field_mapping(self) -> list[dict[str, str]]:
        return [
            {"bridge_field": "TIMESTAMP", "source": "NormalizedHFFrame.timestamp", "units": "ISO8601", "notes": "High-frequency sample time"},
            {"bridge_field": "DEVICE_UID", "source": "NormalizedHFFrame.device_uid", "units": "text", "notes": "Internal acquisition device UID"},
            {"bridge_field": "DEVICE_ID", "source": "NormalizedHFFrame.device_id", "units": "text", "notes": "Analyzer device identifier"},
            {"bridge_field": "MODE", "source": "NormalizedHFFrame.mode", "units": "integer", "notes": "Acquisition mode snapshot"},
            {"bridge_field": "FRAME_QUALITY", "source": "NormalizedHFFrame.frame_quality", "units": "enum", "notes": "Original frame quality status"},
            {"bridge_field": "CO2_PPM", "source": "NormalizedHFFrame.co2_ppm", "units": "ppm", "notes": "CO2 mixing ratio surrogate"},
            {"bridge_field": "H2O_MMOL", "source": "NormalizedHFFrame.h2o_mmol", "units": "mmol mol-1 equivalent", "notes": "Water vapor signal"},
            {"bridge_field": "PRESSURE_KPA", "source": "NormalizedHFFrame.pressure_kpa", "units": "kPa", "notes": "Pressure input"},
            {"bridge_field": "CHAMBER_TEMP_C", "source": "NormalizedHFFrame.chamber_temp_c", "units": "degC", "notes": "Primary temperature channel"},
            {"bridge_field": "CASE_TEMP_C", "source": "NormalizedHFFrame.case_temp_c", "units": "degC", "notes": "Secondary temperature channel"},
            {"bridge_field": "U_MPS", "source": "raw_text/status_text JSON", "units": "m s-1", "notes": "Optional horizontal wind u component"},
            {"bridge_field": "V_MPS", "source": "raw_text/status_text JSON", "units": "m s-1", "notes": "Optional horizontal wind v component"},
            {"bridge_field": "W_MPS", "source": "raw_text/status_text JSON", "units": "m s-1", "notes": "Optional vertical wind component"},
        ]

    def _write_ascii(self, path: Path, headers: list[str], rows: list[list[str]]) -> None:
        lines = ["\t".join(headers)]
        lines.extend("\t".join(row) for row in rows)
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _time_range(self, rows: list[NormalizedHFFrame]) -> dict[str, str | int | None]:
        if not rows:
            return {"start": None, "end": None, "row_count": 0}
        ordered = sorted(rows, key=lambda item: item.timestamp)
        return {
            "start": ordered[0].timestamp.isoformat(),
            "end": ordered[-1].timestamp.isoformat(),
            "row_count": len(ordered),
        }

    def _load_json_dict(self, payload: str) -> dict[str, Any] | None:
        if not payload:
            return None
        try:
            parsed = json.loads(payload)
        except json.JSONDecodeError:
            return None
        return parsed if isinstance(parsed, dict) else None

    def _pick_value(self, payload: dict[str, Any], keys: tuple[str, ...]) -> float | None:
        for key in keys:
            value = payload.get(key)
            if value is not None:
                return float(value)
        return None

    def _format_float(self, value: float | None) -> str:
        if value is None:
            return ""
        return f"{float(value):.6f}"

    def _to_jsonable(self, payload: Any) -> Any:
        if is_dataclass(payload):
            return self._to_jsonable(asdict(payload))
        if isinstance(payload, dict):
            return {key: self._to_jsonable(value) for key, value in payload.items()}
        if isinstance(payload, list):
            return [self._to_jsonable(item) for item in payload]
        if isinstance(payload, datetime):
            return payload.isoformat()
        if isinstance(payload, Path):
            return str(payload)
        return payload
