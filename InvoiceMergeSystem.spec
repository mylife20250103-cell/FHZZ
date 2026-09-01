# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules

project = Path(SPECPATH)

a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[
        (
            str(project / "app" / "services" / "kyd_et_cell_image_data.bin"),
            "app/services",
        ),
    ],
    hiddenimports=collect_submodules("app")
    + collect_submodules("win32com")
    + [
        "win32com",
        "win32com.client",
        "win32com.client.gencache",
        "win32com.client.dynamic",
        "win32com.storagecon",
        "win32timezone",
        "pywintypes",
        "pythoncom",
        "openpyxl",
        "PySide6",
        "xlrd",
        "olefile",
        "PIL",
        "PIL.Image",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest"],
    noarchive=False,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="发票合并系统_V1.1.10",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
