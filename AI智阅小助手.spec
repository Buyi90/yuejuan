# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_submodules


block_cipher = None
project_dir = Path(SPECPATH).resolve()

hiddenimports = (
    [
        "tkinter",
        "tkinter.ttk",
        "tkinter.filedialog",
        "platformdirs_helper",
    ]
    + collect_submodules("requests")
    + collect_submodules("ttkbootstrap")
    + collect_submodules("PIL")
    + collect_submodules("pyautogui")
)

a = Analysis(
    [str(project_dir / "main.py")],
    pathex=[str(project_dir)],
    binaries=[],
    datas=[(str(project_dir / "assets"), "assets")],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[str(project_dir / "pyi_runtime_tk.py")],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name="AI智阅小助手",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(project_dir / "assets" / "logo.ico"),
)
