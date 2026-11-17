# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path
import os
import sys

# PyInstaller 按 PATH 解析依赖；宿主工具的 ICU/OpenSSL 不能进入程序包。
# 依赖只从当前 Python、安装的包（由各 hook 添加）和 Windows 系统目录获取。
windows = Path(os.environ["SystemRoot"])
os.environ["PATH"] = os.pathsep.join(
    str(path)
    for path in (
        Path(sys.executable).parent,
        Path(sys.base_prefix),
        Path(sys.base_prefix) / "DLLs",
        windows / "System32",
        windows,
    )
    if path.is_dir()
)

from PyInstaller.utils.hooks import collect_submodules

project = Path(SPECPATH)

a = Analysis(
    [str(project / "main.py")],
    pathex=[str(project)],
    binaries=[],
    datas=[
        (str(project / "app" / "assets" / "ui"), "app/assets/ui"),
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
        "sqlalchemy",
        "urllib.request",
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
    name="发票合并系统_V1.1.21",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=None,
)
