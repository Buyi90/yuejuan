#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Python UI should follow the C# app fonts, logo, and toolbar icons."""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
ABOUT_SOURCE = (ROOT / "about_dialog.py").read_text(encoding="utf-8")
THEME_SOURCE = (ROOT / "theme.py").read_text(encoding="utf-8")

DECORATIVE_EMOJI = (
    "🚀",
    "⏸",
    "▶",
    "📝",
    "📊",
    "🎨",
    "💾",
    "ℹ️",
    "📸",
    "🤖",
    "⚡",
    "📚",
    "💬",
    "🔍",
    "📷",
    "📁",
    "🗑",
    "👁",
    "➕",
    "📋",
    "🧪",
    "📤",
    "🔄",
    "📦",
    "📂",
    "📥",
    "⚠️",
    "⏹",
    "🔧",
    "⚙",
)


def test_logo_assets_exist() -> None:
    assert (ROOT / "assets" / "logo.ico").is_file()
    assert (ROOT / "assets" / "logo.svg").is_file()


def test_theme_uses_readable_chinese_font_and_color_stack() -> None:
    import theme

    assert theme.FONT_FAMILY == "Microsoft YaHei UI"
    assert "Microsoft YaHei" in theme.FONT_STACK
    assert "Segoe UI" in theme.FONT_STACK
    assert theme.FONT_ICON[0] == "Segoe MDL2 Assets"
    assert theme.FONT_MONO[0] == "Consolas"
    assert theme.COLORS["primary"] == "#3B82F6"
    assert theme.COLORS["light"] == "#F8FAFC"
    assert theme.COLORS["info"] == "#3B82F6"
    assert Path(theme.logo_ico_path()).is_file()
    assert Path(theme.logo_svg_path()).is_file()


def test_theme_exposes_mdl2_toolbar_icons() -> None:
    import theme

    for key in ("play", "pause", "stop", "save", "info", "camera", "settings"):
        glyph = theme.ICON[key]
        assert isinstance(glyph, str) and len(glyph) == 1
        assert "E" == f"{ord(glyph):04X}"[0]


def test_chrome_buttons_keep_chinese_and_drop_emoji() -> None:
    for needle in ("开始批改", "暂停", "停止", "保存配置", "关于"):
        assert needle in APP_SOURCE
    for emoji in DECORATIVE_EMOJI:
        assert emoji not in APP_SOURCE
        assert emoji not in ABOUT_SOURCE


def test_about_dialog_uses_shared_theme_and_logo() -> None:
    assert "theme.FONT" in ABOUT_SOURCE
    assert "logo" in ABOUT_SOURCE.lower()
    assert "Microsoft YaHei UI\", 20" not in ABOUT_SOURCE


def test_window_applies_brand_icon() -> None:
    assert "apply_window_icon" in APP_SOURCE or "iconbitmap" in APP_SOURCE
    assert "logo.ico" in APP_SOURCE or "logo_ico_path" in APP_SOURCE or "apply_window_icon" in THEME_SOURCE


def test_header_uses_logo_not_emoji_badges() -> None:
    assert "截图识别" not in APP_SOURCE
    assert "多模型评分" not in APP_SOURCE
    assert "自动回填" not in APP_SOURCE
    assert "TitleLogo" in APP_SOURCE or "logo" in APP_SOURCE.lower()


def test_fetch_model_buttons_use_icon_helper() -> None:
    lines = [
        line
        for line in APP_SOURCE.splitlines()
        if "获取模型" in line and ("ttk.Button" in line or "theme.icon_button" in line)
    ]
    assert lines
    for line in lines:
        assert "theme.icon_button" in line


def test_dialogs_apply_brand_icon_and_toolbar_icons() -> None:
    submit = (ROOT / "submit_dialog.py").read_text(encoding="utf-8")
    correction = (ROOT / "correction_dialog.py").read_text(encoding="utf-8")
    assert "apply_window_icon" in submit
    assert "apply_window_icon" in correction
    assert "theme.icon_button" in submit
    assert "theme.icon_button" in correction
    assert "ttk.Button" not in submit
    assert "ttk.Button" not in correction


def test_smoke_creates_branded_window() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.update_idletasks()
        assert app.title() == "AI智阅小助手"
        assert theme_font_is_readable(app)
        assert getattr(app, "_brand_icon_applied", False) is True
    finally:
        app.update()
        app.after(200, app.destroy)
        app.update()
        if app.winfo_exists():
            app.destroy()


def theme_font_is_readable(app) -> bool:
    import theme

    if theme.FONT_FAMILY != "Microsoft YaHei UI":
        return False
    if "Microsoft YaHei UI" in theme.APP_STYLESHEET:
        return True
    font_fn = getattr(app, "font", None)
    if callable(font_fn):
        qt_font = font_fn()
        family = qt_font.family() if hasattr(qt_font, "family") else ""
        if family:
            return "YaHei" in family or "Microsoft" in family
    tk_call = getattr(getattr(app, "tk", None), "call", None)
    if callable(tk_call):
        return tk_call("font", "actual", theme.FONT_BASE, "-family") in {
            "Microsoft YaHei UI",
            "Microsoft YaHei",
        }
    return True


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"all {len(tests)} tests passed")
