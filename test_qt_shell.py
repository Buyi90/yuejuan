#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""V1 desktop shell must be PySide6 with the four-page teacher workflow."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
OVERLAY_SOURCE = (ROOT / "overlay.py").read_text(encoding="utf-8")
THEME_SOURCE = (ROOT / "theme.py").read_text(encoding="utf-8")


FORBIDDEN_MAIN_TABS = ("批改", "答案配置", "配置", "服务商", "历史", "方案")
REQUIRED_PAGES = ("AI", "参数", "评分", "过程")
TK_SHIMS = (
    "StringVar",
    "BooleanVar",
    "IntVar",
    "after",
    "mainloop",
    "title",
    "destroy",
    "update_idletasks",
    "winfo_exists",
)


def test_app_imports_pyside6_not_ttkbootstrap() -> None:
    tree = ast.parse(APP_SOURCE)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "PySide6" in APP_SOURCE
    assert "ttkbootstrap" not in imported
    assert "ttkbootstrap" not in APP_SOURCE
    assert "ttk.Window" not in APP_SOURCE


def test_aimarker_app_is_qmainwindow() -> None:
    from PySide6.QtWidgets import QMainWindow
    from app import AIMarkerApp

    assert issubclass(AIMarkerApp, QMainWindow)


def test_main_navigation_is_four_pages() -> None:
    for page in REQUIRED_PAGES:
        assert page in APP_SOURCE
    for old_tab in FORBIDDEN_MAIN_TABS:
        assert f'"{old_tab}"' not in APP_SOURCE
        assert f"'{old_tab}'" not in APP_SOURCE
    assert "show_history_dialog" in APP_SOURCE or "历史记录" in APP_SOURCE
    assert "show_preset_dialog" in APP_SOURCE or "方案" in APP_SOURCE


def test_window_geometry_is_narrow_teacher_tool() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        size = app.size()
        assert 380 <= size.width() <= 480
        assert 720 <= size.height() <= 860
        assert app.title() == "AI智阅小助手"
        for name in TK_SHIMS:
            assert callable(getattr(app, name))
        assert callable(getattr(app.box_tree, "selection"))
    finally:
        app.update()
        app.after(200, app.destroy)
        app.update()
        if app.winfo_exists():
            app.destroy()


def test_overlay_uses_edge_tool_windows_and_starts_hidden() -> None:
    assert "self.edges" in OVERLAY_SOURCE
    assert "self.visible = False" in OVERLAY_SOURCE
    assert "tk.Canvas(self.window" not in OVERLAY_SOURCE
    assert "tk.Toplevel" not in OVERLAY_SOURCE
    assert "Qt.Tool" in OVERLAY_SOURCE or "Qt.ToolTip" in OVERLAY_SOURCE or "Qt.FramelessWindowHint" in OVERLAY_SOURCE


def test_theme_is_qt_not_ttkbootstrap() -> None:
    assert "ttkbootstrap" not in THEME_SOURCE
    assert "def icon_button" in THEME_SOURCE
    assert "QPushButton" in THEME_SOURCE or "PySide6" in THEME_SOURCE
    assert "apply_window_icon" in THEME_SOURCE


def test_history_and_presets_are_dialogs_not_main_tabs() -> None:
    assert "def show_history_dialog" in APP_SOURCE or "def _show_history_dialog" in APP_SOURCE
    assert "def show_preset_dialog" in APP_SOURCE or "def _show_preset_dialog" in APP_SOURCE
    assert "def refresh_history" in APP_SOURCE
    assert "def refresh_presets" in APP_SOURCE
    assert "def save_as_preset" in APP_SOURCE


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    if failed:
        raise SystemExit(f"{failed} failed")
    print(f"all {len(tests)} tests passed")
