from __future__ import annotations

import tkinter as tk
import sys
from functools import lru_cache
from io import BytesIO
from pathlib import Path

# 统一管理界面外观：主题、字体、操作框配色与尺寸约束。
# 这样 UI 风格只需在此处维护一处，app.py / overlay.py 共用同一套常量。


# ttkbootstrap 主题名称 - 5种精选主题
AVAILABLE_THEMES = {
    "flatly": "清新蓝",
    "darkly": "深色暗黑",
    "cosmo": "现代橙",
    "minty": "薄荷绿",
    "superhero": "超级英雄",
}

THEME_NAME = "flatly"  # 默认主题

# C# Avalonia 界面使用 Segoe UI + 微软雅黑回退；等宽输出用 Consolas。
FONT_STACK = ("Segoe UI", "Microsoft YaHei UI", "sans-serif")
FONT_FAMILY = FONT_STACK[0]
FONT_BASE = (FONT_FAMILY, 11)  # 基础字号提升
FONT_SMALL = (FONT_FAMILY, 9)
FONT_LARGE = (FONT_FAMILY, 13)
FONT_TITLE = (FONT_FAMILY, 16, "bold")
FONT_SUBTITLE = (FONT_FAMILY, 11)
FONT_SCORE = (FONT_FAMILY, 36, "bold")  # 专门的分数字体
FONT_MONO = ("Consolas", 10)
FONT_ICON = ("Segoe MDL2 Assets", 12)

# Segoe MDL2 Assets 私用区字形，按钮用图像绘制，避免和中文抢同一个字体。
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

# 色彩系统对齐 C# Fluent 主色，其余语义色保持可扫读。
COLORS = {
    "primary": "#3B82F6",      # C# 主色
    "success": "#27AE60",      # 翠绿 - 成功/高分
    "warning": "#F39C12",      # 琥珀 - 警告/中分
    "danger": "#E74C3C",       # 珊瑚红 - 危险/低分
    "info": "#3B82F6",         # 与主色一致
    "light": "#F8FAFC",        # C# 页面底
    "dark": "#0F172A",         # 深色文字
    "muted": "#64748B",        # 次要信息
    "border": "#E2E8F0",       # 边框色
    "card_bg": "#FFFFFF",      # 卡片背景
    "hover": "#EFF6FF",        # 悬停效果
}

# 间距系统 - 超紧凑化
SPACING = {
    "xs": 1,    # 极小 - 同一元素内
    "sm": 2,    # 小 - 相关元素
    "md": 4,    # 中 - 表单行距
    "lg": 6,    # 大 - 卡片内边距
    "xl": 8,    # 超大 - 卡片外边距
    "xxl": 12,  # 保留用于特殊情况
}

# 表单专用紧凑间距
FORM_SPACING = {
    "label_entry": 1,   # 标签和输入框之间
    "row": 2,           # 行间距
    "section": 4,       # 分组间距
}

# 圆角系统
RADIUS = {
    "sm": 4,
    "md": 8,
    "lg": 12,
    "xl": 16,
    "round": 999,  # 完全圆角
}


# 三类操作框的中文名、配色与默认尺寸（add_box 时使用）。
BOX_META = {
    "recognition": {"name": "识别框", "color": "#2e7d32", "size": (520, 280)},
    "score": {"name": "打分框", "color": "#1565c0", "size": (140, 56)},
    "submit": {"name": "提交框", "color": "#ef6c00", "size": (150, 60)},
}

# 各类操作框允许的最小尺寸（宽, 高），用于批改前的合法性校验。
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
    """给 Tk 窗口套上 C# 同款 logo.ico。"""
    path = logo_ico_path()
    try:
        window.iconbitmap(path)
        window._brand_icon_applied = True
        return True
    except Exception:
        window._brand_icon_applied = False
        return False


def logo_photo(master, size: int = 28):
    from PIL import Image, ImageTk

    image = Image.open(logo_ico_path()).convert("RGBA")
    image.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    offset = ((size - image.width) // 2, (size - image.height) // 2)
    canvas.alpha_composite(image, offset)
    photo = ImageTk.PhotoImage(canvas, master=master)
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
    from PIL import Image, ImageTk

    image = Image.open(BytesIO(_glyph_png(ICON[name], size, color))).convert("RGBA")
    photo = ImageTk.PhotoImage(image, master=master)
    keep = getattr(master, "_brand_images", None)
    if keep is None:
        master._brand_images = []
        keep = master._brand_images
    keep.append(photo)
    return photo


def icon_button(parent, icon: str, text: str, *, size: int = 14, **kwargs):
    import ttkbootstrap as ttk

    color = kwargs.pop("color", "#0F172A")
    photo = icon_photo(parent.winfo_toplevel(), icon, size=size, color=color)
    button = ttk.Button(parent, text=text, image=photo, compound="left", **kwargs)
    button._brand_image = photo
    return button


def icon_text(icon: str, label: str) -> str:
    return f"{ICON[icon]} {label}"


def set_icon_button(button, icon: str, text: str, *, size: int = 14, color: str = "#0F172A", **kwargs):
    photo = icon_photo(button.winfo_toplevel(), icon, size=size, color=color)
    button.configure(text=text, image=photo, compound="left", **kwargs)
    button._brand_image = photo
    return button


def style_text(widget: tk.Text, colors, *, mono: bool = False) -> None:
    """让原生 tk.Text 跟随 ttkbootstrap 主题配色，边框清晰可见。"""
    widget.configure(
        background=COLORS["card_bg"],
        foreground=COLORS["dark"],
        insertbackground=COLORS["info"],
        selectbackground=COLORS["info"],
        selectforeground="#FFFFFF",
        relief="solid",          # 改为solid边框，更清晰
        borderwidth=1,           # 边框1px
        highlightthickness=1,    # 高亮边框1px
        highlightbackground=COLORS["border"],  # 边框颜色
        highlightcolor=COLORS["info"],         # 焦点时边框颜色
        padx=SPACING["md"],
        pady=SPACING["md"],
        font=FONT_MONO if mono else FONT_BASE,
        wrap="word",
    )


def style_listbox(widget: tk.Listbox, colors) -> None:
    """让原生 tk.Listbox 跟随主题配色，边框清晰可见。"""
    widget.configure(
        background=colors.inputbg,
        foreground=colors.inputfg,
        selectbackground=colors.primary,
        selectforeground=colors.selectfg,
        relief="solid",          # 改为solid边框，更清晰
        borderwidth=1,           # 边框1px
        highlightthickness=1,    # 高亮边框1px
        highlightbackground=colors.border,  # 边框颜色
        highlightcolor=colors.primary,      # 焦点时边框颜色
        activestyle="none",
        font=FONT_BASE,
    )
