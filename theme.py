from __future__ import annotations

import sys
from functools import lru_cache
from io import BytesIO
from pathlib import Path

from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import QPushButton

import qtcompat as tk


# 统一管理界面外观：主题、字体、操作框配色与尺寸约束。
# 这样 UI 风格只需在此处维护一处，app.py / overlay.py 共用同一套常量。


AVAILABLE_THEMES = {
    "flatly": "清新蓝",
    "darkly": "深色暗黑",
    "cosmo": "现代橙",
    "minty": "薄荷绿",
    "superhero": "超级英雄",
}

THEME_NAME = "flatly"

FONT_STACK = ("Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", "sans-serif")
FONT_FAMILY = FONT_STACK[0]
FONT_BASE = (FONT_FAMILY, 12)
FONT_SMALL = (FONT_FAMILY, 10)
FONT_LARGE = (FONT_FAMILY, 14)
FONT_TITLE = (FONT_FAMILY, 18, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 12)
FONT_SCORE = (FONT_FAMILY, 36, "bold")
FONT_MONO = ("Consolas", 10)
FONT_ICON = ("Segoe MDL2 Assets", 12)
FONT = FONT_BASE

ICON = {
    "play": "\uE768",
    "pause": "\uE769",
    "stop": "\uE71A",
    "settings": "\uE713",
    "save": "\uE74E",
    "save_as": "\uE792",
    "camera": "\uE722",
    "refresh": "\uE72C",
    "delete": "\uE74D",
    "add": "\uE710",
    "copy": "\uE8C8",
    "folder": "\uE8B7",
    "info": "\uE946",
    "check": "\uE73E",
    "eye": "\uE7B3",
    "hide": "\uE8F4",
    "debug": "\uE90F",
    "scan": "\uE8FE",
    "chart": "\uE9D9",
    "send": "\uE724",
    "test": "\uEA3A",
    "open": "\uE8E5",
    "import": "\uE8B5",
    "export": "\uEDE1",
    "theme": "\uE790",
    "chevron_down": "\uE70D",
    "chevron_up": "\uE70E",
    "warning": "\uE7BA",
    "edit": "\uE70F",
}

COLORS = {
    "primary": "#3B82F6",
    "success": "#27AE60",
    "warning": "#F39C12",
    "danger": "#E74C3C",
    "info": "#3B82F6",
    "light": "#F8FAFC",
    "dark": "#0F172A",
    "muted": "#64748B",
    "border": "#E2E8F0",
    "card_bg": "#FFFFFF",
    "hover": "#EFF6FF",
}

SPACING = {
    "xs": 1,
    "sm": 2,
    "md": 4,
    "lg": 6,
    "xl": 8,
    "xxl": 12,
}

FORM_SPACING = {
    "label_entry": 1,
    "row": 2,
    "section": 4,
}

RADIUS = {
    "sm": 4,
    "md": 8,
    "lg": 12,
    "xl": 16,
    "round": 999,
}


def _build_app_stylesheet() -> str:
    c = COLORS
    r = RADIUS
    return f"""
QWidget {{
    color: {c["dark"]};
    font-family: "Microsoft YaHei UI", "Microsoft YaHei", "Segoe UI", sans-serif;
    font-size: 12px;
}}
QMainWindow, QDialog, QWidget#qt_scrollarea_viewport {{
    background-color: #F4F7FC;
}}
QMainWindow > QWidget {{
    background-color: #F4F7FC;
}}
QLabel {{
    background-color: transparent;
    color: {c["dark"]};
}}
QPushButton {{
    background-color: #FFFFFF;
    color: {c["dark"]};
    border: 1px solid {c["border"]};
    border-radius: 10px;
    padding: 4px 8px;
    min-height: 26px;
    min-width: 0px;
    font-size: 12px;
}}
QPushButton[compact="true"] {{
    padding: 3px 6px;
    min-height: 26px;
    min-width: 0px;
    font-size: 11px;
    border-radius: 8px;
}}
QPushButton:hover {{
    background-color: {c["hover"]};
}}
QPushButton:pressed {{
    background-color: #DBEAFE;
}}
QPushButton:disabled {{
    color: {c["muted"]};
    background-color: #F1F5F9;
}}
QPushButton#btnPrimary {{
    background-color: {c["primary"]};
    color: #FFFFFF;
    border: 1px solid {c["primary"]};
}}
QPushButton#btnPrimary:hover {{
    background-color: #2563EB;
}}
QPushButton#btnSuccess {{
    background-color: {c["success"]};
    color: #FFFFFF;
    border: 1px solid {c["success"]};
}}
QPushButton#btnSuccess:hover {{
    background-color: #1E8449;
}}
QPushButton#btnDanger {{
    background-color: {c["danger"]};
    color: #FFFFFF;
    border: 1px solid {c["danger"]};
}}
QPushButton#btnDanger:hover {{
    background-color: #C0392B;
}}
QPushButton#btnInfo {{
    background-color: {c["info"]};
    color: #FFFFFF;
    border: 1px solid {c["info"]};
}}
QPushButton#btnWarning {{
    background-color: {c["warning"]};
    color: #FFFFFF;
    border: 1px solid {c["warning"]};
}}
QPushButton#btnGhost {{
    background-color: #FFFFFF;
    color: {c["dark"]};
    border: 1px solid {c["border"]};
}}
QTabWidget::pane {{
    border: none;
    background: #F4F7FC;
    top: 0px;
}}
QTabBar {{
    background: transparent;
    qproperty-drawBase: false;
}}
QTabBar::tab {{
    background: #FFFFFF;
    color: #334155;
    border: 1px solid {c["border"]};
    border-radius: 14px;
    padding: 6px 8px;
    margin: 2px 3px 8px 0px;
    min-width: 72px;
    min-height: 22px;
    font-size: 12px;
    font-weight: 600;
}}
QTabBar::tab:selected {{
    background: {c["primary"]};
    color: #FFFFFF;
    border: 1px solid {c["primary"]};
}}
QTabBar::tab:hover:!selected {{
    background: {c["hover"]};
}}
QLineEdit, QComboBox, QTextEdit, QPlainTextEdit, QSpinBox {{
    background: #FFFFFF;
    color: {c["dark"]};
    border: 1px solid {c["border"]};
    border-radius: 8px;
    padding: 4px 8px;
    min-height: 26px;
    selection-background-color: {c["info"]};
    selection-color: #FFFFFF;
}}
QComboBox {{
    combobox-popup: 0;
    padding-right: 20px;
}}
QComboBox::drop-down {{
    border: none;
    width: 18px;
    subcontrol-origin: padding;
    subcontrol-position: center right;
}}
QComboBox QAbstractItemView {{
    background: #FFFFFF;
    border: 1px solid {c["border"]};
    border-radius: 8px;
    selection-background-color: {c["hover"]};
    selection-color: {c["dark"]};
    outline: 0;
}}
QFrame#cardPanel {{
    background: {c["card_bg"]};
    border: 1px solid {c["border"]};
    border-radius: 12px;
}}
QFrame#commandDock {{
    background: {c["card_bg"]};
    border: 1px solid {c["border"]};
    border-radius: 12px;
}}
QFrame#providerToolbar {{
    background: transparent;
}}
QPushButton[toolbar="true"] {{
    padding: 3px 4px;
    min-height: 26px;
    min-width: 0px;
    font-size: 11px;
}}
QPushButton#btnSuccess[toolbar="true"], QPushButton#btnSuccess[compact="true"] {{
    background-color: {c["success"]};
    color: #FFFFFF;
    border: 1px solid {c["success"]};
}}
QPushButton#btnDanger[toolbar="true"], QPushButton#btnDanger[compact="true"] {{
    background-color: {c["danger"]};
    color: #FFFFFF;
    border: 1px solid {c["danger"]};
}}
QPushButton#btnInfo[toolbar="true"], QPushButton#btnInfo[compact="true"] {{
    background-color: {c["info"]};
    color: #FFFFFF;
    border: 1px solid {c["info"]};
}}
QPushButton#btnPrimary[toolbar="true"], QPushButton#btnPrimary[compact="true"] {{
    background-color: {c["primary"]};
    color: #FFFFFF;
    border: 1px solid {c["primary"]};
}}
QPushButton#btnWarning[toolbar="true"], QPushButton#btnWarning[compact="true"] {{
    background-color: {c["warning"]};
    color: #FFFFFF;
    border: 1px solid {c["warning"]};
}}
QFrame#statusChip {{
    background: #ECFDF3;
    border: 1px solid #BBF7D0;
    border-radius: 999px;
    padding: 1px 8px;
}}
QLabel#progressLabel {{
    color: {c["muted"]};
    font-weight: 600;
    min-width: 56px;
    padding: 0 4px;
    background: transparent;
}}
QLabel#appTitle {{
    font-size: 14px;
    font-weight: 700;
    color: {c["dark"]};
    background: transparent;
}}

QFrame#fieldChip {{
    background: #FFFFFF;
    border: 1px solid {c["border"]};
    border-radius: 10px;
    min-width: 0px;
}}
QFrame#fieldChip QLabel {{
    color: {c["muted"]};
    font-size: 12px;
    background: transparent;
    min-width: 0px;
}}
QFrame#fieldChip QLineEdit, QFrame#fieldChip QComboBox {{
    border: none;
    background: transparent;
    min-height: 24px;
    min-width: 0px;
    padding: 2px 4px;
}}
QFrame#accentBar {{
    border: none;
    border-radius: 2px;
}}
QProgressBar {{
    background: #E2E8F0;
    border: none;
    border-radius: 4px;
    max-height: 6px;
    min-height: 6px;
}}
QProgressBar::chunk {{
    background: {c["primary"]};
    border-radius: 4px;
}}
QScrollArea {{
    background: #F4F7FC;
    border: none;
}}
QScrollBar:vertical {{
    background: transparent;
    width: 8px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: #CBD5E1;
    border-radius: 4px;
    min-height: 24px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0px;
}}
QScrollBar:horizontal {{
    height: 0px;
    background: transparent;
}}
QTreeWidget {{
    background: #FFFFFF;
    border: 1px solid {c["border"]};
    border-radius: 8px;
}}
QHeaderView::section {{
    background: #F8FAFC;
    color: {c["muted"]};
    border: none;
    border-bottom: 1px solid {c["border"]};
    padding: 4px 6px;
    font-weight: 600;
}}
QCheckBox {{
    background: transparent;
    spacing: 6px;
}}
QCheckBox::indicator {{
    width: 16px;
    height: 16px;
    border-radius: 4px;
    border: 1px solid {c["border"]};
    background: #FFFFFF;
}}
QCheckBox::indicator:checked {{
    background: {c["primary"]};
    border: 1px solid {c["primary"]};
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: #E2E8F0;
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    width: 14px;
    height: 14px;
    margin: -5px 0;
    border-radius: 7px;
    background: {c["primary"]};
}}
"""


APP_STYLESHEET = _build_app_stylesheet()


def apply_app_stylesheet() -> None:
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance()
    if app is not None:
        app.setStyleSheet(APP_STYLESHEET)


BOX_META = {
    "recognition": {"name": "识别框", "color": "#2e7d32", "size": (520, 280)},
    "score": {"name": "打分框", "color": "#1565c0", "size": (140, 56)},
    "submit": {"name": "提交框", "color": "#ef6c00", "size": (150, 60)},
}

BOX_MIN_SIZE = {
    "recognition": (50, 50),
    "score": (30, 20),
    "submit": (40, 20),
}


def box_color(kind: str) -> str:
    return BOX_META.get(kind, {}).get("color", "#1565c0")


def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", Path(sys.executable).parent))
    return Path(__file__).resolve().parent


def logo_ico_path() -> str:
    return str(_base_dir() / "assets" / "logo.ico")


def logo_svg_path() -> str:
    return str(_base_dir() / "assets" / "logo.svg")


def apply_window_icon(window) -> bool:
    path = logo_ico_path()
    try:
        window.iconbitmap(path)
        if hasattr(window, "setWindowIcon"):
            window.setWindowIcon(QIcon(path))
        window._brand_icon_applied = True
        return True
    except Exception:
        window._brand_icon_applied = False
        return False


def _pixmap_from_png_bytes(data: bytes) -> QPixmap:
    pix = QPixmap()
    pix.loadFromData(data)
    return pix


def logo_photo(master, size: int = 28):
    import qtcompat as _qt
    _qt.ensure_app()
    from PIL import Image

    image = Image.open(logo_ico_path()).convert("RGBA")
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = ((size - image.width) // 2, (size - image.height) // 2)
    canvas.alpha_composite(image, offset)
    buffer = BytesIO()
    canvas.save(buffer, format="PNG")
    photo = _pixmap_from_png_bytes(buffer.getvalue())
    keep = getattr(master, "_brand_images", None)
    if keep is None:
        master._brand_images = []
        keep = master._brand_images
    keep.append(photo)
    return photo


@lru_cache(maxsize=128)
def _glyph_png(char: str, size: int, color: str) -> bytes:
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.truetype(r"C:\Windows\Fonts\segmdl2.ttf", size)
    probe = Image.new("RGBA", (size * 2, size * 2), (0, 0, 0, 0))
    draw = ImageDraw.Draw(probe)
    left, top, right, bottom = draw.textbbox((0, 0), char, font=font)
    width = max(size, right - left)
    height = max(size, bottom - top)
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.text(((-left + (width - (right - left)) // 2), (-top + (height - (bottom - top)) // 2)), char, font=font, fill=color)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def icon_photo(master, name: str, size: int = 14, color: str = "#0F172A"):
    import qtcompat as _qt
    _qt.ensure_app()
    photo = _pixmap_from_png_bytes(_glyph_png(ICON[name], size, color))
    keep = getattr(master, "_brand_images", None)
    if keep is None:
        master._brand_images = []
        keep = master._brand_images
    keep.append(photo)
    return photo


def icon_button(parent, icon: str, text: str, *, size: int = 14, **kwargs):
    color = kwargs.pop("color", "#0F172A")
    bootstyle = kwargs.pop("bootstyle", None)
    kwargs.pop("style", None)
    toplevel = parent.winfo_toplevel() if hasattr(parent, "winfo_toplevel") else parent
    photo = icon_photo(toplevel, icon, size=size, color=color)
    button = tk.Button(parent, text=text, image=photo, compound="left", bootstyle=bootstyle, **kwargs)
    button._brand_image = photo
    button.setProperty("compact", True)
    button.setMinimumWidth(0)
    try:
        button.style().unpolish(button)
        button.style().polish(button)
    except Exception:
        pass
    return button


def icon_text(icon: str, label: str) -> str:
    return f"{ICON[icon]} {label}"


def set_icon_button(button, icon: str, text: str, *, size: int = 14, color: str = "#0F172A", **kwargs):
    toplevel = button.winfo_toplevel() if hasattr(button, "winfo_toplevel") else button
    try:
        photo = icon_photo(toplevel, icon, size=size, color=color)
        button.configure(text=text, image=photo, **kwargs)
        button._brand_image = photo
    except Exception:
        button.configure(text=text, **kwargs)
    return button


def style_text(widget, colors, *, mono: bool = False) -> None:
    widget.configure(
        background=COLORS["card_bg"],
        foreground=COLORS["dark"],
        insertbackground=COLORS["info"],
        selectbackground=COLORS["info"],
        selectforeground="#FFFFFF",
        relief="solid",
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=COLORS["border"],
        highlightcolor=COLORS["info"],
        padx=SPACING["md"],
        pady=SPACING["md"],
        font=FONT_MONO if mono else FONT_BASE,
        wrap="word",
    )


def style_listbox(widget, colors) -> None:
    widget.configure(
        background=getattr(colors, "inputbg", COLORS["card_bg"]),
        foreground=getattr(colors, "inputfg", COLORS["dark"]),
        selectbackground=getattr(colors, "primary", COLORS["primary"]),
        selectforeground=getattr(colors, "selectfg", "#FFFFFF"),
        relief="solid",
        borderwidth=1,
        highlightthickness=1,
        highlightbackground=getattr(colors, "border", COLORS["border"]),
        highlightcolor=getattr(colors, "primary", COLORS["primary"]),
        activestyle="none",
        font=FONT_BASE,
    )
