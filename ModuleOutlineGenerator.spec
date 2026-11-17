# Build on 64-bit Windows with Python 3.11 or 3.12; this is an onedir build.
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files

root = Path(SPECPATH)
resources = [
    (str(root / "frontend" / "index.html"), "frontend"),
    (str(root / "backend" / "schema.sql"), "backend"),
    (str(root / "backend" / "seed.sql"), "backend"),
]
resources += [(str(root / "backend" / "templates" / f"template_{lang}.docx"), "backend/templates")
              for lang in ("en", "zh", "pt")]
resources += collect_data_files("docx") + collect_data_files("docxtpl")

a = Analysis(
    [str(root / "desktop_launcher.py")],
    pathex=[str(root), str(root / "backend")],
    binaries=[], datas=resources,
    hiddenimports=["openpyxl", "xlrd"],
    hookspath=[], hooksconfig={}, runtime_hooks=[],
    excludes=["gunicorn", "pytest", "IPython", "matplotlib"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [], exclude_binaries=True,
    name="ModuleOutlineGenerator", debug=False,
    bootloader_ignore_signals=False, strip=False, upx=False,
    console=False, disable_windowed_traceback=True,
    contents_directory="_internal",
)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False,
               name="ModuleOutlineGenerator-Windows")
