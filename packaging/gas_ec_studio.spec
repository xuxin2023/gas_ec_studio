from pathlib import Path
import os

from PyInstaller.utils.hooks import collect_all, collect_data_files


PROJECT_ROOT = Path(SPECPATH).resolve().parent
BUILD_NAME = os.environ.get("GAS_EC_BUILD_NAME", "GasECStudio-0.1.0-rc3-win64")

pyqtgraph_datas = collect_data_files("pyqtgraph")
rasterio_datas, rasterio_binaries, rasterio_hiddenimports = collect_all("rasterio")
pyproj_datas, pyproj_binaries, pyproj_hiddenimports = collect_all("pyproj")
rio_cogeo_datas, rio_cogeo_binaries, rio_cogeo_hiddenimports = collect_all("rio_cogeo")
morecantile_datas, morecantile_binaries, morecantile_hiddenimports = collect_all("morecantile")
datas = [
    (str(PROJECT_ROOT / "app" / "assets"), "app/assets"),
    (str(PROJECT_ROOT / "CHANGELOG.md"), "."),
    (str(PROJECT_ROOT / "references"), "references"),
    (str(PROJECT_ROOT / "docs"), "docs"),
    (str(PROJECT_ROOT / "core" / "exports" / "templates"), "core/exports/templates"),
    *pyqtgraph_datas,
    *rasterio_datas,
    *pyproj_datas,
    *rio_cogeo_datas,
    *morecantile_datas,
]

a = Analysis(
    [str(PROJECT_ROOT / "app" / "main.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=[*rasterio_binaries, *pyproj_binaries, *rio_cogeo_binaries, *morecantile_binaries],
    datas=datas,
    hiddenimports=[
        *rasterio_hiddenimports,
        *pyproj_hiddenimports,
        *rio_cogeo_hiddenimports,
        *morecantile_hiddenimports,
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["IPython", "jupyter", "matplotlib", "notebook", "pytest", "tkinter", "torch"],
    noarchive=False,
    optimize=1,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name=BUILD_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=str(PROJECT_ROOT / "packaging" / "version_info.txt"),
    icon=str(PROJECT_ROOT / "packaging" / "gas_ec_studio.ico"),
)
