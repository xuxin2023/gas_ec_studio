from __future__ import annotations

import json
from pathlib import Path

from models.spectral_models import EvidenceBundleManifest, SpectralRunResult


class RunResultStore:
    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.spectral_root = self.root / "spectral_runs"
        self.evidence_root = self.root / "evidence_manifests"
        self.spectral_library_root = self.root / "spectral_libraries"
        self.index_path = self.root / "spectral_runs_index.json"
        self.spectral_root.mkdir(parents=True, exist_ok=True)
        self.evidence_root.mkdir(parents=True, exist_ok=True)
        self.spectral_library_root.mkdir(parents=True, exist_ok=True)
        if not self.index_path.exists():
            self._write_index([])

    def save_spectral_run(self, result: SpectralRunResult) -> Path:
        path = self.spectral_root / f"{result.run_id}.json"
        path.write_text(json.dumps(result.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")

        index_rows = [row for row in self._read_index() if row.get("run_id") != result.run_id]
        index_rows.append(
            {
                "run_id": result.run_id,
                "created_at": result.created_at.isoformat(),
                "data_source": result.data_source,
                "time_range": result.time_range,
                "qc_only": result.qc_only,
                "path": str(path),
            }
        )
        index_rows.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
        self._write_index(index_rows)
        return path

    def load_spectral_run(self, run_id: str) -> SpectralRunResult | None:
        path = self.spectral_root / f"{run_id}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return SpectralRunResult.from_dict(payload)

    def list_spectral_runs(self, limit: int | None = None) -> list[SpectralRunResult]:
        return self.list_recent_runs(limit=limit)

    def list_recent_runs(self, limit: int | None = None) -> list[SpectralRunResult]:
        rows: list[SpectralRunResult] = []
        for item in self._read_index():
            run_id = str(item.get("run_id", ""))
            if not run_id:
                continue
            run = self.load_spectral_run(run_id)
            if run is not None:
                rows.append(run)
            if limit is not None and len(rows) >= limit:
                break
        return rows

    def latest_spectral_run(self) -> SpectralRunResult | None:
        rows = self.list_recent_runs(limit=1)
        return rows[0] if rows else None

    def get_previous_batch(self, current_run_id: str | None = None) -> SpectralRunResult | None:
        rows = self.list_recent_runs()
        if not rows:
            return None
        if current_run_id is None:
            return rows[1] if len(rows) > 1 else None
        for index, row in enumerate(rows):
            if row.run_id == current_run_id:
                return rows[index + 1] if index + 1 < len(rows) else None
        return None

    def save_evidence_manifest(self, manifest: EvidenceBundleManifest) -> Path:
        path = self.evidence_root / f"{manifest.bundle_id}.json"
        path.write_text(json.dumps(manifest.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def load_evidence_manifest(self, bundle_id: str) -> EvidenceBundleManifest | None:
        path = self.evidence_root / f"{bundle_id}.json"
        if not path.exists():
            return None
        payload = json.loads(path.read_text(encoding="utf-8"))
        return EvidenceBundleManifest.from_dict(payload)

    def latest_evidence_manifest(self) -> EvidenceBundleManifest | None:
        manifest_paths = sorted(self.evidence_root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not manifest_paths:
            return None
        payload = json.loads(manifest_paths[0].read_text(encoding="utf-8"))
        return EvidenceBundleManifest.from_dict(payload)

    def build_spectral_assessment_library(
        self,
        *,
        run_ids: list[str] | None = None,
        limit: int | None = None,
        dataset_id: str = "",
        target_bins: int = 24,
        group_by: list[str] | None = None,
        min_windows_per_group: int = 1,
    ) -> dict:
        from core.ec_fcc.analysis import build_spectral_assessment_library

        if run_ids:
            runs = [run for run_id in run_ids for run in [self.load_spectral_run(run_id)] if run is not None]
        else:
            runs = self.list_recent_runs(limit=limit)
        return build_spectral_assessment_library(
            runs,
            dataset_id=dataset_id,
            target_bins=target_bins,
            group_by=group_by,
            min_windows_per_group=min_windows_per_group,
        )

    def save_spectral_assessment_library(self, library: dict, library_id: str | None = None) -> Path:
        resolved_id = str(library_id or library.get("library_id") or "spectral_library").strip() or "spectral_library"
        safe_id = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in resolved_id)
        path = self.spectral_library_root / f"{safe_id}.json"
        path.write_text(json.dumps(library, ensure_ascii=False, indent=2), encoding="utf-8")
        return path

    def latest_spectral_assessment_library(self) -> dict | None:
        library_paths = sorted(self.spectral_library_root.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True)
        if not library_paths:
            return None
        payload = json.loads(library_paths[0].read_text(encoding="utf-8"))
        return dict(payload) if isinstance(payload, dict) else None

    def _read_index(self) -> list[dict]:
        if not self.index_path.exists():
            return []
        payload = json.loads(self.index_path.read_text(encoding="utf-8"))
        return payload if isinstance(payload, list) else []

    def _write_index(self, rows: list[dict]) -> None:
        self.index_path.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
