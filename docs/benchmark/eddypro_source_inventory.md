# EddyPro Official Source Inventory

`gas_ec_studio` tracks public EddyPro source-code anchors as a benchmark artifact before claiming full numerical parity.

## Scope

The inventory records:

- Official EddyPro Engine repository URL and local commit.
- Official EddyPro GUI repository URL and local commit.
- Presence, SHA-256, and size of key upstream source modules.
- Token-level feature evidence for raw ingestion, rotations, spectral correction, footprint, statistical screening, and GUI controls.

The callable entry point is:

```powershell
python - <<'PY'
from core.comparison.eddypro_source_inventory import build_eddypro_source_inventory
print(build_eddypro_source_inventory()["status"])
PY
```

## Export Integration

Result bundles write `eddypro_source_inventory.json` and expose it in:

- `summary.json`
- `export_manifest.json`
- headless batch manifests
- delivery audit and package manifest
- formal report delivery audit
- fixture pack summary

## Truthfulness

This artifact does not copy or execute EddyPro. It proves which public source revision and feature modules guided parity work. Real raw fixtures with official EddyPro output remain required for final raw-to-final numeric parity.
