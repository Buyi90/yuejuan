# -*- mode: python ; coding: utf-8 -*-

from PyInstaller.utils.hooks import collect_submodules
from PyInstaller.building.datastruct import Tree


block_cipher = None

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
    ["main.py"],
    pathex=[],
    binaries=[
        (r"C:\Users\lenovo\AppData\Local\Programs\Python\Python312\DLLs\_tkinter.pyd", "."),
        (r"C:\Users\lenovo\AppData\Local\Programs\Python\Python312\DLLs\tcl86t.dll", "."),
        (r"C:\Users\lenovo\AppData\Local\Programs\Python\Python312\DLLs\tk86t.dll", "."),
    ],
    datas=[
        (r"C:\Users\lenovo\AppData\Local\Programs\Python\Python312\tcl\tcl8.6", "_tcl_data"),
        (r"C:\Users\lenovo\AppData\Local\Programs\Python\Python312\tcl\tk8.6", "_tk_data"),
        (r"C:\Users\lenovo\AppData\Local\Programs\Python\Python312\tcl\tcl8", "tcl8"),
        (r"C:\Users\lenovo\AppData\Local\Programs\Python\Python312\Lib\tkinter", "tkinter"),
        ("assets", "assets"),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=["pyi_runtime_tk.py"],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

a.datas += Tree(r"C:\Users\lenovo\AppData\Local\Programs\Python\Python312\Lib\tkinter", prefix="tkinter")

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
    icon="assets/logo.ico",
)
