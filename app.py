from __future__ import annotations

import json
import os
import queue
import threading
import time
from typing import Any

from PySide6.QtCore import QSize, Qt
from PySide6.QtWidgets import QLabel, QGridLayout, QHBoxLayout, QMainWindow, QProgressBar, QPushButton, QSizePolicy, QVBoxLayout, QWidget

import qtcompat as tk
from qtcompat import DANGER, INFO, OUTLINE, PRIMARY, SECONDARY, SUCCESS, WARNING
from qtcompat import filedialog, messagebox, ttk

import theme
from about_dialog import show_about_dialog
from ai_client import grade_dual, grade_with_optional_ocr, list_provider_models, test_provider
from ollama_discovery import discover_ollama, prepare_ollama_provider, refresh_ollama_providers
from automation import fill_and_submit
from history import add_history, clear_history, export_csv, export_docx, export_html, export_json, export_pdf, export_xlsx
from image_tools import black_pixel_ratio, capture_region, image_to_base64, is_blank, preprocess_image
from image_tools import image_quality_report
from models import AppConfig, Provider, RegionBox, config_from_dict, normalize_operation_boxes, provider_for_role, unify_grading_roles
from hotkeys import PauseHotkeyWatcher, normalize_hotkey, parse_hotkey
from overlay import FloatingBoxManager
from scoring import apply_scoring
from grading_pipeline import GradingHooks, GradingNetworkRecoverable, GradingSession, pipeline_config_from_app_config
from storage import CONFIG_FILE, PRESETS_FILE, clear_blank_reference, load_blank_reference, load_config, load_presets, save_blank_reference, save_config, save_presets


# 主 UI 基于 PySide6，tk 兼容层由 qtcompat 提供。



class AppGradingHooks(GradingHooks):
    """Bridge C# pipeline callbacks onto the existing Tk worker."""

    def __init__(self, app: "AIMarkerApp", stream_callback=None) -> None:
        self.app = app
        self.stream_callback = stream_callback
        self.last_quality: dict[str, Any] | None = None

    def capture(self) -> Any:
        recog = self.app.get_box("recognition")
        if not recog:
            raise RuntimeError("缺少识别框")
        img = preprocess_image(
            capture_region(recog, self.app.config_data.recognition_margin),
            self.app.config_data.preprocess_level,
        )
        quality = image_quality_report(img)
        self.last_quality = quality
        self.app.work_queue.put(
            ("output", f"识别区质量：{quality['level']}，尺寸 {quality['width']}x{quality['height']}，暗像素占比 {quality['dark_ratio'] * 100:.2f}%\n")
        )
        return img

    def is_blank(self, image: Any) -> bool:
        if self.app.skip_blank_once:
            self.app.skip_blank_once = False
            return False
        if not self.app.config_data.blank_detection_enabled:
            return False
        ref = load_blank_reference()
        if not ref:
            return False
        cur = black_pixel_ratio(image)
        blank, reason = is_blank(cur, ref, self.app.config_data.blank_threshold)
        self.app.work_queue.put(("output", f"空白检测：{reason}\n"))
        return bool(blank)

    def grade(self, image: Any) -> dict[str, Any]:
        self.app.work_queue.put(("status", "正在调用 AI"))
        provider = self.app.get_active_provider()
        if not self.app.config_data.workflow.primary_enabled:
            raise RuntimeError("主评未启用，请在配置页打开主评开关")
        callback = self.stream_callback
        grade = (
            grade_dual(self.app.config_data, image, provider, callback)
            if self.app.config_data.workflow.dual_enabled
            else grade_with_optional_ocr(self.app.config_data, image, provider, callback)
        )
        scored = apply_scoring(grade, self.app.config_data.scoring)
        scores: list[float] = []
        if grade.sub_scores:
            scores = [float(item.get("score")) for item in grade.sub_scores if item.get("score") is not None]
        if not scores:
            raw = grade.raw_score if grade.raw_score is not None else grade.score
            if raw is not None:
                scores = [float(raw)]
        result = {
            "student_answer": grade.student_answer,
            "ai_score": grade.raw_score,
            "final_score": scored["final_score"],
            "comment": grade.comment,
            "basis": grade.scoring_basis,
            "calculation": grade.calculation,
            "sub_scores": scored["sub_scores"],
            "bonus": scored["bonus"],
            "dual_eval": grade.dual_eval,
            "max_score": self.app._max_score(),
            "quality": self.last_quality,
            "image_base64": image_to_base64(image) if self.app.config_data.save_images else "",
        }
        return {"scores": scores, "result": result}

    def fill_and_submit(self, score, values=None) -> None:
        score_box = self.app.get_box("score")
        submit_box = self.app.get_box("submit")
        if not (score_box and submit_box and self.app.continuous):
            return
        result = {"final_score": score, "sub_scores": [{"score": item} for item in (values or []) if item is not None]}
        fill_and_submit(
            score_box,
            submit_box,
            score,
            self.app._score_values_for_fill(result),
            self.app.config_data.workflow.score_switch_mode,
        )

    def sleep(self, seconds: float) -> None:
        self.app._interruptible_sleep(seconds)

    def is_running(self) -> bool:
        return bool(self.app.running)

    def wait_if_paused(self) -> None:
        self.app._wait_if_paused()

    def send_hotkey(self, spec: str) -> bool:
        return self.app._send_page_refresh_hotkey(spec)

    def log(self, message: str) -> None:
        self.app.work_queue.put(("output", f"{message}\n"))

    def emit_status(self, text: str) -> None:
        self.app.work_queue.put(("status", text))

    def emit_result(self, result, image=None) -> None:
        payload = dict(result or {})
        payload.setdefault("max_score", self.app._max_score())
        if self.last_quality is not None:
            payload.setdefault("quality", self.last_quality)
        if image is not None and self.app.config_data.save_images and not payload.get("image_base64"):
            payload["image_base64"] = image_to_base64(image)
        auto_submit = bool(self.app.continuous)
        self.app.work_queue.put(("result", (payload, image, auto_submit)))

    def emit_progress(self, text: str) -> None:
        try:
            self.app.loop_count = int(str(text).split("/")[0])
        except Exception:
            pass
        self.app.work_queue.put(("progress", text))

    def emit_history(self) -> None:
        self.app.work_queue.put(("history", None))

    def emit_error(self, text: str) -> None:
        self.app.running = False
        self.app.continuous = False
        self.app.paused = False
        self.app.work_queue.put(("error", text))


class AIMarkerApp(tk.Window):
    def __init__(self):
        super().__init__()
        self._closed = False
        self._destroying = False
        self.title("AI智阅小助手")
        self.geometry("420x780")
        self.minsize(400, 720)
        theme.apply_window_icon(self)

        self.config_data: AppConfig = load_config()
        self.config_data.boxes = normalize_operation_boxes(self.config_data.boxes)
        self.floating_boxes: FloatingBoxManager | None = None
        self.status_var = tk.StringVar(value="就绪")
        self.progress_var = tk.StringVar(value="0/0")
        self.running = False
        self.current_result: dict[str, Any] | None = None
        self.current_image = None
        self.loop_count = 0
        self.continuous = False
        self.paused = False
        self.skip_blank_once = False
        self.work_queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._text_widgets: list[tk.Text] = []
        self._list_widgets: list[tk.Listbox] = []
        self.comment_expanded = False
        self.output_expanded = False
        self._restore_boxes_after_worker = False
        self.pause_hotkey_watcher = PauseHotkeyWatcher(
            get_spec=lambda: getattr(self.config_data.workflow, "pause_hotkey", "F8"),
            on_trigger=self._on_pause_hotkey,
            is_active=lambda: self.running and self.continuous,
        )
        self._build_style()
        self._build()
        self._ensure_floating_boxes()
        self._apply_native_widget_theme()
        self.after(150, self._poll_queue)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.pause_hotkey_watcher.start()
        self._refresh_pause_button()

    def _create_card(self, parent) -> tuple[ttk.Frame, ttk.Frame]:
        card = ttk.Frame(parent)
        card.setObjectName("cardPanel")
        inner = ttk.Frame(card)
        inner.pack(fill="x", padx=10, pady=8)
        return card, inner

    def _card_section(self, parent, title: str, color: str = theme.COLORS["primary"]):
        card, inner = self._create_card(parent)
        card.pack(fill="x", pady=(0, 8))
        self._create_section_title(inner, title, color).pack(fill="x", pady=(0, 6))
        return inner

    def _field_chip(self, parent, label: str, var, widget: str = "entry", values=None):
        cell = ttk.Frame(parent)
        cell.setObjectName("fieldChip")
        cell.setMinimumHeight(30)
        cell.setMaximumHeight(34)
        cell.setMinimumWidth(0)
        cell.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        lay = QHBoxLayout(cell)
        lay.setContentsMargins(8, 2, 6, 2)
        lay.setSpacing(4)
        lab = ttk.Label(cell, text=label, font=(theme.FONT_FAMILY, 9))
        lab.setMinimumWidth(0)
        lab.setMaximumWidth(72)
        lab.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        lay.addWidget(lab, 0)
        if widget == "combo":
            field = ttk.Combobox(cell, textvariable=var, values=values or [], state="readonly")
        else:
            field = ttk.Entry(cell, textvariable=var)
            if widget == "readonly":
                field.setReadOnly(True)
        field.setMinimumWidth(0)
        field.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        lay.addWidget(field, 1)
        return cell

    def _ensure_grid(self, parent) -> QGridLayout:
        layout = parent.layout()
        if isinstance(layout, QGridLayout):
            return layout
        layout = QGridLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setHorizontalSpacing(6)
        layout.setVerticalSpacing(6)
        layout.setColumnStretch(0, 1)
        layout.setColumnStretch(1, 1)
        return layout

    def _two_col_field(self, parent, row: int, left_label: str, left_var, right_label: str, right_var) -> int:
        left_kind = "readonly" if left_label in {"已改数量", "打分个数"} else "entry"
        right_kind = "readonly" if right_label in {"已改数量", "打分个数"} else "entry"
        left = self._field_chip(parent, left_label, left_var, widget=left_kind)
        right = self._field_chip(parent, right_label, right_var, widget=right_kind)
        layout = self._ensure_grid(parent)
        layout.addWidget(left, row, 0)
        layout.addWidget(right, row, 1)
        return row + 1

    def _two_col_combo(self, parent, row: int, left_label: str, left_var, left_values, right_label: str, right_var, right_values) -> int:
        left = self._field_chip(parent, left_label, left_var, widget="combo", values=left_values)
        right = self._field_chip(parent, right_label, right_var, widget="combo", values=right_values)
        layout = self._ensure_grid(parent)
        layout.addWidget(left, row, 0)
        layout.addWidget(right, row, 1)
        return row + 1

    def _create_section_title(self, parent, text: str, color: str = theme.COLORS["primary"]) -> ttk.Frame:
        """创建带左侧竖线的分组标题（参考小作拓风格）"""
        container = ttk.Frame(parent)

        # 左侧竖线
        line = tk.Frame(container, bg=color, width=3, height=18)
        line.setObjectName("accentBar")
        line.setFixedSize(3, 18)
        line.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        line.pack(side="left", fill="y", padx=(0, 6))

        # 标题文字
        label = ttk.Label(container, text=text, font=(theme.FONT_FAMILY, 11, "bold"))
        label.pack(side="left")

        return container

    def _compact_form_row(self, parent, row: int, label_text: str, widget_var, widget_type: str = "entry", **kwargs) -> int:
        """创建紧凑的表单行：标签在左，控件在右"""
        ttk.Label(parent, text=label_text, font=(theme.FONT_FAMILY, 10)).grid(
            row=row, column=0, sticky="w", pady=2, padx=(0, 4)
        )

        if widget_type == "entry":
            widget = ttk.Entry(parent, textvariable=widget_var, width=kwargs.get('width', 8))
        elif widget_type == "combobox":
            widget = ttk.Combobox(parent, textvariable=widget_var,
                                 values=kwargs.get('values', []),
                                 state="readonly", width=kwargs.get('width', 7))
        elif widget_type == "checkbutton":
            widget = ttk.Checkbutton(parent, text="", variable=widget_var)
        else:
            widget = ttk.Entry(parent, textvariable=widget_var, width=kwargs.get('width', 8))

        widget.grid(row=row, column=1, sticky="w", pady=2)
        return row + 1

    def _create_scrollable_tab(self, title: str) -> tuple[ttk.Frame, ttk.Frame]:
        tab = ttk.Frame(self.tabs)
        self.tabs.add(tab, text=title)
        canvas = tk.Canvas(tab, highlightthickness=0, bg=theme.COLORS["light"])
        canvas.setWidgetResizable(True)
        canvas.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        canvas.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        scrollable_frame = ttk.Frame(canvas)
        scrollable_frame.setMinimumWidth(0)
        scrollable_frame.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        canvas.create_window((0, 0), window=scrollable_frame, anchor="nw")
        canvas.pack(fill="both", expand=True)
        return tab, scrollable_frame

    def _build_style(self) -> None:
        style = self.style
        colors = style.colors

        # 全局样式
        style.configure(".", font=theme.FONT_BASE)

        # 标题样式
        style.configure("Title.TLabel", font=theme.FONT_TITLE)
        style.configure("Subtitle.TLabel", font=theme.FONT_SUBTITLE, foreground=colors.secondary)
        style.configure("Status.TLabel", font=theme.FONT_SMALL)

        # 卡片样式 - 更现代的设计
        style.configure("Card.TLabelframe",
                       padding=theme.SPACING["lg"],
                       relief="flat",
                       borderwidth=0)
        style.configure("Card.TLabelframe.Label",
                       font=(theme.FONT_FAMILY, 11, "bold"),
                       foreground=theme.COLORS["primary"])

        # 主要卡片样式（识别答案、评分）
        style.configure("Primary.Card.TLabelframe",
                       padding=theme.SPACING["xl"],
                       relief="solid",
                       borderwidth=2)
        style.configure("Primary.Card.TLabelframe.Label",
                       font=(theme.FONT_FAMILY, 12, "bold"),
                       foreground=theme.COLORS["info"])

        # 标签页样式
        style.configure("TNotebook.Tab",
                       padding=(20, 10),
                       font=theme.FONT_BASE)

        # 按钮样式
        style.configure("TButton",
                       padding=(12, 8),
                       font=theme.FONT_BASE)
        style.configure("Primary.TButton",
                       padding=(16, 10),
                       font=(theme.FONT_FAMILY, 11, "bold"))
        style.configure("Icon.TButton",
                       padding=(14, 9),
                       font=(theme.FONT_FAMILY, 10))

        # 分数标签样式
        style.configure("Score.TLabel",
                       font=theme.FONT_SCORE,
                       foreground=theme.COLORS["success"])

    def _register_text(self, widget: tk.Text, *, mono: bool = False) -> tk.Text:
        widget._mono = mono  # type: ignore[attr-defined]
        self._text_widgets.append(widget)
        return widget

    def _register_listbox(self, widget: tk.Listbox) -> tk.Listbox:
        self._list_widgets.append(widget)
        return widget

    def _apply_native_widget_theme(self) -> None:
        """tk.Text / tk.Listbox 不受 ttk 主题管控，这里统一刷成与主题一致的配色。"""
        colors = self.style.colors
        for widget in self._text_widgets:
            theme.style_text(widget, colors, mono=getattr(widget, "_mono", False))
        for widget in self._list_widgets:
            theme.style_listbox(widget, colors)

    def _build(self) -> None:
        outer = ttk.Frame(self, padding=8)
        outer.pack(fill="both", expand=True)

        header = ttk.Frame(outer)
        header.pack(fill="x", pady=(0, 6))

        logo = ttk.Label(header, image=theme.logo_photo(self, 22), name="titlelogo")
        logo.setMaximumHeight(22)
        logo.setMaximumWidth(22)
        logo.pack(side="left", padx=(0, 6))
        title_label = ttk.Label(header, text="AI智阅小助手", font=(theme.FONT_FAMILY, 12, "bold"))
        title_label.setObjectName("appTitle")
        title_label.setMaximumHeight(22)
        title_label.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        title_label.pack(side="left")

        status_chip = ttk.Frame(header)
        status_chip.setObjectName("statusChip")
        status_chip.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        status_chip.setMaximumHeight(22)
        self.status_label_widget = ttk.Label(
            status_chip,
            textvariable=self.status_var,
            font=(theme.FONT_FAMILY, 9, "bold"),
            foreground=theme.COLORS["success"],
        )
        self.status_label_widget.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
        self.status_label_widget.pack(side="left", padx=8, pady=1)
        status_chip.pack(side="right")

        current_theme_display = theme.AVAILABLE_THEMES.get(theme.THEME_NAME, "清新蓝")
        self.theme_var = tk.StringVar(value=current_theme_display)
        theme_names = list(theme.AVAILABLE_THEMES.values())
        self.theme_combo = ttk.Combobox(
            header,
            textvariable=self.theme_var,
            values=theme_names,
            state="readonly",
            width=8,
        )
        self.theme_combo.bind("<<ComboboxSelected>>", self.change_theme)
        self.theme_combo.hide()

        self.tabs = ttk.Notebook(outer)
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(True)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setElideMode(Qt.ElideNone)
        self.tabs.pack(fill="both", expand=True)
        self._build_provider_tab()
        self._build_config_tab()
        self._build_answer_config_tab()
        self._build_work_tab()
        self._apply_visible_tab_labels()

        dock = ttk.Frame(outer)
        dock.setObjectName("commandDock")
        dock.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
        dock.pack(fill="x", pady=(6, 0))

        action_bar = ttk.Frame(dock)
        action_bar.setObjectName("commandActions")
        action_grid = QGridLayout(action_bar)
        action_bar.pack(fill="x", pady=(4, 2), padx=6)
        action_grid.setContentsMargins(0, 0, 0, 0)
        action_grid.setHorizontalSpacing(4)
        action_grid.setVerticalSpacing(2)
        start_btn = theme.icon_button(
            action_bar, "play", "开始批改", size=12, color="#FFFFFF", bootstyle=PRIMARY, command=self.start_grading
        )
        self.pause_button = theme.icon_button(
            action_bar, "pause", "暂停", size=12, color=theme.COLORS["warning"], bootstyle=(WARNING, OUTLINE), command=self.toggle_pause, state="disabled"
        )
        stop_btn = theme.icon_button(
            action_bar, "stop", "停止", size=12, color=theme.COLORS["danger"], bootstyle=(DANGER, OUTLINE), command=self.stop
        )
        debug_btn = theme.icon_button(
            action_bar, "debug", "调试", size=12, color=theme.COLORS["primary"], bootstyle=(SECONDARY, OUTLINE), command=self.debug_once
        )
        for col, btn in enumerate((start_btn, self.pause_button, stop_btn, debug_btn)):
            if btn is start_btn:
                btn.setObjectName("btnPrimary")
            elif btn is debug_btn:
                btn.setObjectName("btnGhost")
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumWidth(0)
            action_grid.addWidget(btn, 0, col)
            action_grid.setColumnStretch(col, 1)
        track = ttk.Frame(dock)
        track.setObjectName("progressTrack")
        track.pack(fill="x", padx=6, pady=(0, 2))
        track.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        track_layout = track.layout() or QHBoxLayout(track)
        track_layout.setContentsMargins(4, 2, 4, 2)
        track_layout.setSpacing(8)
        self.progress_bar = QProgressBar(track)
        self.progress_bar.setObjectName("commandProgress")
        self.progress_bar.setTextVisible(False)
        self.progress_bar.setRange(0, 1)
        self.progress_bar.setValue(0)
        self.progress_bar.setFixedHeight(6)
        self.progress_bar.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        track_layout.addWidget(self.progress_bar, 1)
        track_layout.setAlignment(self.progress_bar, Qt.AlignVCenter)
        self.progress_label = ttk.Label(
            track,
            textvariable=self.progress_var,
            font=(theme.FONT_FAMILY, 10, "bold"),
            name="progressLabel",
        )
        self.progress_label.setObjectName("progressLabel")
        self.progress_label.setMinimumWidth(56)
        self.progress_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        track_layout.addWidget(self.progress_label, 0)
        track_layout.setAlignment(self.progress_label, Qt.AlignVCenter | Qt.AlignRight)
        self.progress_var.trace_add("write", self._sync_progress_bar)
        self._sync_progress_bar()

        footer = ttk.Frame(dock)
        footer_grid = QGridLayout(footer)
        footer.pack(fill="x", padx=6, pady=(0, 4))
        footer_grid.setContentsMargins(0, 0, 0, 0)
        footer_grid.setHorizontalSpacing(4)
        footer_grid.setVerticalSpacing(2)
        footer_btns = [
            theme.icon_button(footer, "folder", "历史记录", command=self.show_history_dialog),
            theme.icon_button(footer, "save_as", "方案管理", command=self.show_preset_dialog),
            theme.icon_button(footer, "info", "关于", bootstyle=(INFO, OUTLINE), command=self.show_about),
            theme.icon_button(footer, "save", "保存配置", bootstyle=(SUCCESS, OUTLINE), command=self.save_all),
        ]
        for col, btn in enumerate(footer_btns):
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setMinimumWidth(0)
            footer_grid.addWidget(btn, 0, col)
            footer_grid.setColumnStretch(col, 1)
        for btn in list(action_bar.findChildren(QPushButton)) + list(footer.findChildren(QPushButton)):
            btn.setProperty("compact", True)
            btn.setMinimumWidth(0)
            btn.setIconSize(QSize(12, 12))
            btn.style().unpolish(btn)
            btn.style().polish(btn)

    def _apply_visible_tab_labels(self) -> None:
        labels = [
            "AI" + chr(0x914D) + chr(0x7F6E),
            chr(0x6539) + chr(0x5377) + chr(0x53C2) + chr(0x6570),
            chr(0x8BC4) + chr(0x5206) + chr(0x6807) + chr(0x51C6),
            chr(0x8BC4) + chr(0x5206) + chr(0x8FC7) + chr(0x7A0B),
        ]
        for i, label in enumerate(labels):
            self.tabs.setTabText(i, label)
        bar = self.tabs.tabBar()
        bar.setExpanding(True)
        bar.setUsesScrollButtons(False)
        bar.setDrawBase(False)
        bar.setElideMode(Qt.ElideNone)

    def _build_work_tab(self) -> None:
        tab = ttk.Frame(self.tabs, padding=theme.SPACING["sm"])
        self.tabs.add(tab, text="过程")

        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x", pady=(0, theme.SPACING["sm"]))
        theme.icon_button(toolbar, "check", "检查配置", bootstyle=(SECONDARY, OUTLINE), command=self.check_readiness).pack(side="left", padx=(0, 4))
        theme.icon_button(toolbar, "camera", "截图预览", bootstyle=(INFO, OUTLINE), command=self.preview_capture).pack(side="left", padx=(0, 4))
        theme.icon_button(toolbar, "scan", "采集范本", bootstyle=(SECONDARY, OUTLINE), command=self.capture_blank_reference).pack(side="left")

        # 主滚动区域 - 使用Canvas实现
        canvas_frame = ttk.Frame(tab)
        canvas_frame.pack(fill="both", expand=True)

        # 添加背景色
        self.work_canvas = tk.Canvas(canvas_frame, highlightthickness=0, bg=theme.COLORS["light"])
        self.work_canvas.setWidgetResizable(True)
        self.work_canvas.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.work_canvas.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)

        self.scroll_content = ttk.Frame(self.work_canvas)
        self.work_canvas.create_window((0, 0), window=self.scroll_content, anchor="nw", tags="content")
        self.work_canvas.pack(fill="both", expand=True)

        # 鼠标滚轮绑定 - 只绑定到canvas，不使用bind_all
        def on_mousewheel(event):
            self.work_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        self.work_canvas.bind("<MouseWheel>", on_mousewheel)
        self.scroll_content.bind("<MouseWheel>", on_mousewheel)

        # 内容区域 - 超紧凑卡片布局
        content = self.scroll_content

        # 1. 识别答案卡片（最重要）
        answer_card = self._card_section(content, "学生答案")

        self.answer_view = self._register_text(tk.Text(answer_card, wrap="word", height=5, font=(theme.FONT_FAMILY, 11, "bold")))
        self.answer_view.pack(fill="both", expand=True)
        self.answer_view.tag_config("highlight", foreground=theme.COLORS["dark"], font=(theme.FONT_FAMILY, 11, "bold"))

        # 2. 参考答案对比卡片
        reference_card = self._card_section(content, "参考答案")
        self.reference_view = self._register_text(tk.Text(reference_card, wrap="word", height=3, font=(theme.FONT_FAMILY, 10)))
        self.reference_view.pack(fill="both", expand=True)
        self.reference_view.tag_config("ref", foreground=theme.COLORS["muted"])
        self.reference_view.configure(state="disabled")  # 只读

        # 3. 评分结果卡片（醒目显示）
        score_card = self._card_section(content, "评分")

        score_display = ttk.Frame(score_card)
        score_display.pack(fill="x")

        # 最终得分 - 超大号显示
        final_frame = ttk.Frame(score_display)
        final_frame.pack(side="left", fill="x", expand=True, padx=theme.SPACING["lg"])

        ttk.Label(final_frame, text="最终得分", font=(theme.FONT_FAMILY, 11, "bold"), foreground=theme.COLORS["muted"]).pack(anchor="w")

        score_container = ttk.Frame(final_frame)
        score_container.pack(fill="x", pady=(theme.SPACING["xs"], 0))

        self.final_score_label = ttk.Label(score_container, text="--", font=theme.FONT_SCORE, bootstyle=SUCCESS)
        self.final_score_label.pack(side="left", anchor="w")

        self.score_unit_label = ttk.Label(score_container, text="分", font=(theme.FONT_FAMILY, 18, "bold"), foreground=theme.COLORS["muted"])
        self.score_unit_label.pack(side="left", anchor="s", padx=(theme.SPACING["xs"], 0), pady=(0, 6))

        # 分隔线
        ttk.Separator(score_display, orient="vertical").pack(side="left", fill="y", padx=theme.SPACING["lg"])

        # 详细分数信息 - 卡片式展示
        detail_frame = ttk.Frame(score_display)
        detail_frame.pack(side="left", fill="both", expand=True, padx=theme.SPACING["lg"])

        # 使用网格布局展示详细信息
        detail_grid = ttk.Frame(detail_frame)
        detail_grid.pack(fill="both", expand=True)

        # AI原始分
        ai_score_frame = ttk.Frame(detail_grid)
        ai_score_frame.grid(row=0, column=0, sticky="w", pady=theme.SPACING["xs"])
        ttk.Label(ai_score_frame, text="AI原始分", font=(theme.FONT_FAMILY, 9), foreground=theme.COLORS["muted"]).pack(side="left")
        self.ai_score_value = ttk.Label(ai_score_frame, text="--", font=(theme.FONT_FAMILY, 12, "bold"), foreground=theme.COLORS["info"])
        self.ai_score_value.pack(side="left", padx=(theme.SPACING["sm"], 0))

        # 满分
        max_score_frame = ttk.Frame(detail_grid)
        max_score_frame.grid(row=1, column=0, sticky="w", pady=theme.SPACING["xs"])
        ttk.Label(max_score_frame, text="满分", font=(theme.FONT_FAMILY, 9), foreground=theme.COLORS["muted"]).pack(side="left")
        self.max_score_value = ttk.Label(max_score_frame, text="--", font=(theme.FONT_FAMILY, 12, "bold"), foreground=theme.COLORS["dark"])
        self.max_score_value.pack(side="left", padx=(theme.SPACING["sm"], 0))

        # 4. 评分说明（可折叠，超紧凑）
        comment_card = self._card_section(content, "评分说明")

        self.comment_toggle_btn = theme.icon_button(comment_card, "chevron_down", "展开", bootstyle=(INFO, OUTLINE), command=self.toggle_comment)
        self.comment_toggle_btn.pack(fill="x")

        self.comment_view = self._register_text(tk.Text(comment_card, wrap="word", height=4, font=(theme.FONT_FAMILY, 9)))
        self.comment_view.pack(fill="both")
        self.comment_view.pack_forget()  # 默认隐藏
        self.comment_view.tag_config("comment", foreground=theme.COLORS["dark"], spacing1=2, spacing3=2)
        self.comment_view.tag_config("basis", foreground=theme.COLORS["muted"], font=(theme.FONT_FAMILY, 9))
        self.comment_expanded = False

        # 5. AI详细输出（折叠，超紧凑）
        output_card = self._card_section(content, "AI输出")

        self.output_toggle_btn = theme.icon_button(output_card, "chevron_down", "展开", bootstyle=(SECONDARY, OUTLINE), command=self.toggle_output)
        self.output_toggle_btn.pack(fill="x")

        self.output = self._register_text(tk.Text(output_card, wrap="word", height=5, font=(theme.FONT_FAMILY, 8)), mono=True)
        self.output.pack(fill="both")
        self.output.pack_forget()  # 默认隐藏
        self.output_expanded = False
        self.output.tag_config("muted", foreground=theme.COLORS["muted"])

    def _build_answer_config_tab(self) -> None:
        """答案配置标签页 - 紧凑化设计"""
        _, tab = self._create_scrollable_tab("评分")
        page = ttk.Frame(tab, padding=8)
        page.pack(fill="both", expand=True)

        # 初始化变量（如果还没初始化）
        # ┃ 参考答案
        answer_inner = self._card_section(page, "参考答案")
        self.answer = self._labeled_text(answer_inner, "", self.config_data.answer, 6)

        # ┃ 评分标准
        rubric_inner = self._card_section(page, "评分标准")
        self.rubric = self._labeled_text(rubric_inner, "", self.config_data.rubric, 6)

        # ┃ 评分材料图片
        material_card = self._card_section(page, "评分材料", "#27AE60")

        material_bar = ttk.Frame(material_card)
        material_bar.pack(fill="x", pady=(0, theme.SPACING["xs"]))
        add_btn = theme.icon_button(material_bar, "add", "添加", color="#FFFFFF", bootstyle=SUCCESS, command=self.add_material_images)
        add_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        add_btn.pack(side="left", fill="x", expand=True, padx=2)
        remove_btn = theme.icon_button(material_bar, "delete", "移除", color="#FFFFFF", bootstyle=DANGER, command=self.remove_material_image)
        remove_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        remove_btn.pack(side="left", fill="x", expand=True, padx=2)
        view_btn = theme.icon_button(material_bar, "eye", "查看", color="#FFFFFF", bootstyle=INFO, command=self.open_material_image)
        view_btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        view_btn.pack(side="left", fill="x", expand=True, padx=2)

        self.material_list = self._register_listbox(tk.Listbox(material_card, height=4))
        self.material_list.pack(fill="x")
        self.refresh_material_images()

    def _init_config_vars(self) -> None:
        workflow = self.config_data.workflow
        scoring = self.config_data.scoring

        self.grade_level = tk.StringVar(value=self.config_data.grade_level)
        self.subject = tk.StringVar(value=self.config_data.subject)
        self.question_type = tk.StringVar(value="填空")
        self.active_provider = tk.StringVar(value=self.config_data.active_provider)
        self.primary_enabled = tk.BooleanVar(value=workflow.primary_enabled)
        self.secondary_enabled = tk.BooleanVar(value=workflow.dual_enabled)
        self.arbitration_enabled = tk.BooleanVar(value=workflow.arbitration_enabled)
        shared_provider = workflow.primary_provider_name or self.config_data.active_provider
        # 主评/副评/仲裁/OCR 共用同一家服务商和同一个模型。
        self.primary_provider = tk.StringVar(value=shared_provider)
        self.secondary_provider = tk.StringVar(value=shared_provider)
        self.arbitration_provider = tk.StringVar(value=shared_provider)
        self.ocr_provider = tk.StringVar(value=shared_provider)
        shared_model = workflow.primary_model or self._provider_model_name(shared_provider)
        self.primary_model = tk.StringVar(value=shared_model)
        self.secondary_model = tk.StringVar(value=shared_model)
        self.arbitration_model = tk.StringVar(value=shared_model)
        self.ocr_model = tk.StringVar(value=shared_model)
        self.recognition_mode = tk.StringVar(value=self._choice_label(self.RECOGNITION_MODE_CHOICES, "direct"))
        self.mode = tk.StringVar(value=self._choice_label(self.GRADE_MODE_CHOICES, workflow.mode))
        self.max_score = tk.StringVar(value=str(scoring.max_score))
        self.round_step = tk.StringVar(value=str(scoring.round_step))
        self.round_method = tk.StringVar(value=self._choice_label(self.ROUND_METHOD_CHOICES, scoring.round_method))
        self.save_images = tk.BooleanVar(value=self.config_data.save_images)
        self.preprocess = tk.IntVar(value=1)
        self.recognition_margin = tk.StringVar(value=str(self.config_data.recognition_margin))
        self.blank_enabled = tk.BooleanVar(value=self.config_data.blank_detection_enabled)
        self.capture_delay = tk.StringVar(value=str(workflow.capture_delay))
        self.scoring_delay = tk.StringVar(value=str(workflow.scoring_delay))
        self.next_paper_delay = tk.StringVar(value=str(workflow.next_paper_delay))
        self.score_switch_mode = tk.StringVar(value=self._choice_label(self.SCORE_SWITCH_CHOICES, "single"))
        self.target_count = tk.StringVar(value=str(workflow.target_count))
        self.pause_hotkey = tk.StringVar(value=workflow.pause_hotkey)
        self.retry_limit = tk.StringVar(value=str(workflow.retry_limit))
        self.enable_abnormal_termination = tk.BooleanVar(value=workflow.enable_abnormal_termination)
        self.abnormal_termination_count = tk.StringVar(value=str(workflow.abnormal_termination_count))
        self.enable_page_refresh = tk.BooleanVar(value=workflow.enable_page_refresh)
        self.page_refresh_frequency = tk.StringVar(value=str(workflow.page_refresh_frequency))
        self.page_refresh_hotkey = tk.StringVar(value=workflow.page_refresh_hotkey)
        self.page_refresh_wait_seconds = tk.StringVar(value=str(workflow.page_refresh_wait_seconds))
        self.dual_threshold = tk.StringVar(value=str(workflow.dual_threshold))
        self.graded_count = tk.StringVar(value=str(self.loop_count or 0))
        self.score_box_count = tk.StringVar(value=str(sum(1 for box in self.config_data.boxes if box.kind == "score")))

    GRADE_MODE_CHOICES = [
        ("normal", "普通批改"),
        ("trial", "试批"),
        ("unattended", "无人值守"),
    ]
    RECOGNITION_MODE_CHOICES = [
        ("direct", "直接识别"),
        ("ocr_first", "先识别再评分"),
    ]
    ROUND_METHOD_CHOICES = [
        ("round", "四舍五入"),
        ("floor", "向下取整"),
        ("ceil", "向上取整"),
    ]
    SCORE_SWITCH_CHOICES = [
        ("single", "单框填写"),
        ("tab", "Tab 切换"),
        ("enter", "回车切换"),
        ("space", "空格切换"),
    ]
    PROVIDER_SOURCE_CHOICES = [
        ("network", "网络接口"),
        ("local", "本机 Ollama"),
        ("lan", "局域网 Ollama"),
        ("custom", "自定义"),
    ]
    PROVIDER_PROTOCOL_CHOICES = [
        ("openai_compatible", "OpenAI 兼容"),
        ("ollama", "Ollama 本地"),
    ]
    API_FORMAT_CHOICES = [
        ("", "自动"),
        ("responses", "Responses（原生）"),
        ("chat_completions", "Chat Completions"),
    ]
    REASONING_CHOICES = [
        ("low", "低"),
        ("medium", "中等"),
        ("high", "高"),
    ]
    PREPROCESS_TEXTS = {
        0: "0 原图直出",
        1: "1 推荐：增强对比",
        2: "2 去噪后再识别",
        3: "3 黑白二值",
    }

    def _choice_labels(self, choices: list[tuple[str, str]]) -> list[str]:
        return [label for _value, label in choices]

    def _choice_label(self, choices: list[tuple[str, str]], value: str) -> str:
        mapping = {item: label for item, label in choices}
        reverse = {label: label for _item, label in choices}
        if choices is self.REASONING_CHOICES:
            raw = (value or "medium").strip().lower()
            if raw in {"", "minimal", "none", "default"}:
                raw = "medium"
            value = raw
        if value in mapping:
            return mapping[value]
        if value in reverse:
            return value
        return choices[0][1] if choices else value

    def _choice_value(self, choices: list[tuple[str, str]], label: str, default: str) -> str:
        mapping = {item_label: item for item, item_label in choices}
        reverse = {item: item for item, _label in choices}
        if label in mapping:
            return mapping[label]
        if label in reverse:
            return label
        return default

    def _preprocess_text(self, level: int) -> str:
        return self.PREPROCESS_TEXTS.get(int(level or 0), "1 推荐：增强对比")

    def _refresh_preprocess_label(self) -> None:
        if hasattr(self, "preprocess_label"):
            self.preprocess_label.configure(text=self._preprocess_text(self.preprocess.get()))

    def _provider_model_name(self, provider_name: str) -> str:
        provider = self.get_provider_by_name(provider_name) or self.get_active_provider()
        return provider.model

    def _build_config_tab(self) -> None:
        _, tab = self._create_scrollable_tab("参数")
        page = ttk.Frame(tab, padding=8)
        page.pack(fill="both", expand=True)
        self._init_config_vars()

        inner = self._card_section(page, "数值设置")
        grid = ttk.Frame(inner)
        grid.pack(fill="x")
        self._two_col_field(grid, 0, "改卷数量", self.target_count, "取卡延时", self.capture_delay)
        self._two_col_field(grid, 1, "已改数量", self.graded_count, "打分延时", self.scoring_delay)

        inner = self._card_section(page, "题目设置")
        grid = ttk.Frame(inner)
        grid.pack(fill="x")
        self._two_col_field(grid, 0, "题目满分", self.max_score, "批改间隔", self.next_paper_delay)
        self._ensure_grid(grid).addWidget(self._field_chip(grid, "仲裁阈值", self.dual_threshold), 1, 0)
        self._ensure_grid(grid).addWidget(
            self._field_chip(
                grid,
                "批改模式",
                self.mode,
                widget="combo",
                values=self._choice_labels(self.GRADE_MODE_CHOICES),
            ),
            2,
            0,
        )

        inner = self._card_section(page, "标记设置")
        self._build_box_tab(inner)

        inner = self._card_section(page, "批改流程")
        form = ttk.Frame(inner)
        form.pack(fill="x")
        row = 0
        role_row = ttk.Frame(form)
        role_row.grid(row=row, column=0, columnspan=2, sticky="ew", pady=(0, 6))
        ttk.Checkbutton(role_row, text="启用主评", variable=self.primary_enabled).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(role_row, text="启用副评", variable=self.secondary_enabled).pack(side="left", padx=(0, 14))
        ttk.Checkbutton(role_row, text="启用仲裁", variable=self.arbitration_enabled).pack(side="left")
        row += 1
        row = self._shared_grading_provider_row(form, row)
        row = self._model_only_row(form, row, "模型", self.primary_model)
        ttk.Checkbutton(form, text="保存答题卡截图到历史", variable=self.save_images).grid(row=row, column=1, sticky="w", pady=4)
        row += 1
        row = self._entry(form, row, "识别框内边距(px)", self.recognition_margin)
        ttk.Checkbutton(form, text="启用空白答题卡检测", variable=self.blank_enabled).grid(row=row, column=1, sticky="w", pady=4)
        row += 1
        row = self._entry(form, row, "暂停快捷键", self.pause_hotkey)
        ttk.Label(form, text="仅连续批改开始后生效，例如 F8 或 Ctrl+Shift+P。").grid(row=row, column=1, sticky="w")
        row += 1
        row = self._entry(form, row, "分值重试次数", self.retry_limit)
        ttk.Checkbutton(form, text="连续相同分值时异常终止", variable=self.enable_abnormal_termination).grid(row=row, column=1, sticky="w", pady=4)
        row += 1
        row = self._entry(form, row, "异常终止份数", self.abnormal_termination_count)
        ttk.Checkbutton(form, text="定时刷新页面", variable=self.enable_page_refresh).grid(row=row, column=1, sticky="w", pady=4)
        row += 1
        row = self._entry(form, row, "翻页刷新频率(份)", self.page_refresh_frequency)
        row = self._entry(form, row, "翻页刷新热键", self.page_refresh_hotkey)
        row = self._entry(form, row, "翻页后等待(秒)", self.page_refresh_wait_seconds)
        form.columnconfigure(1, weight=1)
    def _build_provider_tab(self) -> None:
        _, tab = self._create_scrollable_tab("AI")
        container = ttk.Frame(tab, padding=theme.SPACING["sm"])
        container.pack(fill="both", expand=True)

        # ┃ 选择服务商（下拉选择）
        card, inner = self._create_card(container)
        card.pack(fill="x", pady=(0, 8))
        section = self._create_section_title(inner, "选择服务商", "#3498DB")
        section.pack(fill="x", pady=(0, theme.SPACING["sm"]))

        select_frame = ttk.Frame(inner)
        select_frame.pack(fill="x", pady=(0, theme.SPACING["md"]))

        # 服务商下拉选择框
        self.provider_selector_var = tk.StringVar()
        provider_selector_label = ttk.Label(select_frame, text="当前服务商", font=(theme.FONT_FAMILY, 9))
        provider_selector_label.setObjectName("providerSelectorLabel")
        provider_selector_label.setFixedWidth(76)
        provider_selector_label.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        provider_selector_label.pack(side="left", padx=(0, 0))
        self.provider_selector = ttk.Combobox(select_frame, textvariable=self.provider_selector_var,
                                              state="readonly", width=20)
        self.provider_selector.setObjectName("providerSelector")
        self.provider_selector.pack(side="left", fill="x", expand=True)
        self.provider_selector.bind("<<ComboboxSelected>>", self.on_provider_selector_changed)

        # 操作按钮（紧凑）
        btn_frame = ttk.Frame(inner)
        btn_frame.setObjectName("providerToolbar")
        self._provider_fetch_buttons = []
        self._provider_test_buttons = []
        self._provider_action_busy = False
        add_txt = chr(0x65B0) + chr(0x589E)
        copy_txt = chr(0x590D) + chr(0x5236)
        del_txt = chr(0x5220) + chr(0x9664)
        save_txt = chr(0x4FDD) + chr(0x5B58)
        test_txt = chr(0x6D4B) + chr(0x8BD5)
        fetch_txt = chr(0x83B7) + chr(0x53D6) + chr(0x6A21) + chr(0x578B)
        specs = [
            ("add", add_txt, "#FFFFFF", SUCCESS, self.add_provider),
            ("copy", copy_txt, "#FFFFFF", INFO, self.copy_provider),
            ("delete", del_txt, "#FFFFFF", DANGER, self.delete_provider),
            ("save", save_txt, "#FFFFFF", PRIMARY, self.save_provider_from_form),
            ("test", test_txt, "#FFFFFF", SECONDARY, self.test_selected_provider),
            ("refresh", fetch_txt, theme.COLORS["info"], (INFO, OUTLINE), self.fetch_provider_models),
        ]
        grid = QGridLayout(btn_frame)
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(4)
        grid.setVerticalSpacing(4)
        btn_frame.pack(fill="x", pady=(0, theme.SPACING["md"]))
        for i, (icon, label, color, style, cmd) in enumerate(specs):
            btn = theme.icon_button(btn_frame, icon, label, size=11, color=color, bootstyle=style, command=cmd)
            name = tk._bootstyle_name(style)
            if name:
                btn.setObjectName(name)
            btn.setProperty("toolbar", True)
            btn.setIconSize(QSize(11, 11))
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.setProperty("compact", True)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            if icon == "refresh":
                self._provider_fetch_buttons.append(btn)
            elif icon == "test":
                self._provider_test_buttons.append(btn)
            grid.addWidget(btn, i // 3, i % 3)

        card, inner = self._create_card(container)
        card.pack(fill="x", pady=(0, 8))
        section = self._create_section_title(inner, "服务商配置", "#9B59B6")
        section.pack(fill="x", pady=(theme.SPACING["md"], theme.SPACING["sm"]))

        self.provider_name_var = tk.StringVar()
        self.provider_endpoint_var = tk.StringVar()
        self.provider_key_var = tk.StringVar()
        self.provider_model_var = tk.StringVar()
        self.provider_models_var = tk.StringVar()
        self.provider_reasoning_var = tk.StringVar(value=self._choice_label(self.REASONING_CHOICES, "medium"))
        self.provider_source_var = tk.StringVar(value=self._choice_label(self.PROVIDER_SOURCE_CHOICES, "network"))
        self.provider_protocol_var = tk.StringVar(value=self._choice_label(self.PROVIDER_PROTOCOL_CHOICES, "openai_compatible"))
        self.provider_api_format_var = tk.StringVar(value=self._choice_label(self.API_FORMAT_CHOICES, ""))
        self.provider_test_prompt_var = tk.StringVar(value="请只回复：连接成功")

        form = ttk.Frame(inner)
        form.setObjectName("providerForm")
        form.pack(fill="both", expand=True)

        row = 0
        name_entry = ttk.Entry(form, textvariable=self.provider_name_var)
        name_entry.setObjectName("providerNameEntry")
        ttk.Label(form, text="名称", font=(theme.FONT_FAMILY, 9)).grid(row=row, column=0, sticky="w", pady=3)
        name_entry.grid(row=row, column=1, sticky="ew", pady=3)
        row += 1
        ttk.Label(form, text="模型来源", font=(theme.FONT_FAMILY, 9)).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Combobox(form, textvariable=self.provider_source_var, values=self._choice_labels(self.PROVIDER_SOURCE_CHOICES),
                     state="readonly", width=16).grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        ttk.Label(form, text="接口协议", font=(theme.FONT_FAMILY, 9)).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Combobox(form, textvariable=self.provider_protocol_var,
                     values=self._choice_labels(self.PROVIDER_PROTOCOL_CHOICES), state="readonly", width=20).grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        ttk.Label(form, text="上游格式", font=(theme.FONT_FAMILY, 9)).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Combobox(form, textvariable=self.provider_api_format_var,
                     values=self._choice_labels(self.API_FORMAT_CHOICES), state="readonly", width=20).grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        row = self._entry(form, row, "API端点", self.provider_endpoint_var)
        row = self._entry(form, row, "API Key", self.provider_key_var, show="*")
        ttk.Label(form, text="当前模型", font=(theme.FONT_FAMILY, 9)).grid(row=row, column=0, sticky="w", pady=2)
        model_line = ttk.Frame(form)
        model_line.grid(row=row, column=1, sticky="ew", pady=2)
        self.provider_model_combo = ttk.Combobox(model_line, textvariable=self.provider_model_var)
        self.provider_model_combo.pack(side="left", fill="x", expand=True)
        theme.icon_button(model_line, "refresh", "获取模型", bootstyle=(INFO, OUTLINE), command=self.fetch_provider_models).pack(side="left", padx=(6, 0))
        row += 1
        row = self._entry(form, row, "模型列表", self.provider_models_var)
        ttk.Label(form, text="推理强度", font=(theme.FONT_FAMILY, 9)).grid(row=row, column=0, sticky="w", pady=2)
        ttk.Combobox(form, textvariable=self.provider_reasoning_var, values=self._choice_labels(self.REASONING_CHOICES),
                     state="readonly", width=12).grid(row=row, column=1, sticky="w", pady=2)
        row += 1
        row = self._entry(form, row, "测试对话", self.provider_test_prompt_var)

        for label_widget in form.findChildren(QLabel):
            label_widget.setObjectName("providerFieldLabel")
            label_widget.setFixedWidth(76)
            label_widget.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
        self.provider_action_status = ttk.Label(
            inner,
            text="就绪",
            name="providerActionStatus",
        )
        self.provider_action_status.setObjectName("providerActionStatus")
        self.provider_action_status.setStyleSheet(f"color: {theme.COLORS['muted']};")
        self.provider_action_status.pack(fill="x", pady=(4, 0))
        form.columnconfigure(1, weight=1)
        self.refresh_provider_selector()
        self.after(250, lambda: self.refresh_selected_ollama_models(False))

    def _build_box_tab(self, parent=None) -> None:
        tab = parent if parent is not None else ttk.Frame(self)
        container = ttk.Frame(tab, padding=0 if parent is not None else theme.SPACING["sm"])
        container.pack(fill="both", expand=True)
        if parent is None:
            section = self._create_section_title(container, "操作框管理", "#3498DB")
            section.pack(fill="x", pady=(0, theme.SPACING["sm"]))
        add_all = theme.icon_button(container, "add", "一键添加", color="#FFFFFF", bootstyle=PRIMARY, command=self.add_all_boxes)
        add_all.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        add_all.pack(fill="x", pady=(0, 6))
        rows = [
            ("答题卡框", "recognition", DANGER, "#FFFFFF"),
            ("分值输入框", "score", SUCCESS, "#FFFFFF"),
            ("提交按钮框", "submit", PRIMARY, "#FFFFFF"),
        ]
        for label, kind, style, color in rows:
            row = ttk.Frame(container)
            row.pack(fill="x", pady=3)
            name_chip = ttk.Frame(row)
            name_chip.setObjectName("fieldChip")
            name_chip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            name_chip.setMinimumHeight(30)
            ttk.Label(name_chip, text=label).pack(side="left", padx=10, pady=6)
            name_chip.pack(side="left", fill="x", expand=True, padx=(0, 6))
            btn = theme.icon_button(row, "add", "添加标记", color=color, bootstyle=style, command=lambda k=kind: self.add_box(k))
            btn.setMinimumWidth(96)
            btn.pack(side="right")
        tools = ttk.Frame(container)
        tool_grid = QGridLayout(tools)
        tools.pack(fill="x", pady=(6, 4))
        tool_grid.setContentsMargins(0, 0, 0, 0)
        tool_grid.setHorizontalSpacing(4)
        show_btn = theme.icon_button(tools, "eye", "显示框", color="#FFFFFF", bootstyle=INFO, command=self.toggle_floating_boxes)
        remove_btn = theme.icon_button(tools, "delete", "移除", color="#FFFFFF", bootstyle=DANGER, command=self.delete_selected_box)
        for col, btn in enumerate((show_btn, remove_btn)):
            btn.setProperty("compact", True)
            btn.setMinimumWidth(0)
            btn.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
            tool_grid.addWidget(btn, 0, col)
            tool_grid.setColumnStretch(col, 1)
        self.boxes_visible = tk.BooleanVar(value=True)
        self.toggle_boxes_button = show_btn
        columns = ("name", "kind", "x", "y", "w", "h")
        self.box_tree = ttk.Treeview(container, columns=columns, show="headings", height=5)
        for c, title in zip(columns, ["名称", "类型", "X", "Y", "宽", "高"]):
            self.box_tree.heading(c, text=title)
            self.box_tree.column(c, width=80)
        self.box_tree.pack(fill="both", expand=True)
        self.refresh_boxes()
    def _build_history_tab(self, parent=None) -> None:
        if parent is None:
            return
        container = ttk.Frame(parent, padding=theme.SPACING["sm"])
        container.pack(fill="both", expand=True)

        # ┃ 历史记录
        section = self._create_section_title(container, "历史记录", "#3498DB")
        section.pack(fill="x", pady=(0, theme.SPACING["sm"]))

        bar = ttk.Frame(container)
        bar.pack(fill="x", pady=(0, theme.SPACING["sm"]))

        theme.icon_button(bar, "refresh", "刷新", color="#FFFFFF", bootstyle=INFO, command=self.refresh_history).pack(side="left", padx=1)

        # 导出格式下拉选择
        ttk.Label(bar, text="导出格式", font=(theme.FONT_FAMILY, 9)).pack(side="left", padx=(8, 4))
        self.export_format_var = tk.StringVar(value="JSON")
        export_combo = ttk.Combobox(bar, textvariable=self.export_format_var,
                                    values=["JSON", "CSV", "HTML", "Word", "Excel", "PDF"],
                                    state="readonly", width=8)
        export_combo.pack(side="left", padx=1)

        theme.icon_button(bar, "export", "导出", color="#FFFFFF", bootstyle=SUCCESS, command=self.export_history_selected_format).pack(side="left", padx=(4, 8))
        theme.icon_button(bar, "delete", "清空", color="#FFFFFF", bootstyle=DANGER, command=self.clear_history_records).pack(side="left", padx=1)

        self.history_text = self._register_text(tk.Text(container, wrap="word"), mono=True)
        self.history_text.pack(fill="both", expand=True)
        self.refresh_history()

    def _build_preset_tab(self, parent=None) -> None:
        if parent is None:
            return
        container = ttk.Frame(parent, padding=theme.SPACING["sm"])
        container.pack(fill="both", expand=True)

        # ┃ 选择方案（下拉选择）
        section = self._create_section_title(container, "选择方案", "#3498DB")
        section.pack(fill="x", pady=(0, theme.SPACING["sm"]))

        select_frame = ttk.Frame(container)
        select_frame.pack(fill="x", pady=(0, theme.SPACING["md"]))

        # 方案下拉选择框
        self.preset_selector_var = tk.StringVar()
        ttk.Label(select_frame, text="当前方案", font=(theme.FONT_FAMILY, 9)).pack(side="left", padx=(0, 4))
        self.preset_selector = ttk.Combobox(select_frame, textvariable=self.preset_selector_var,
                                            state="readonly", width=20)
        self.preset_selector.pack(side="left", fill="x", expand=True)
        self.preset_selector.bind("<<ComboboxSelected>>", self.on_preset_selector_changed)

        # 操作按钮（紧凑）
        btn_frame = ttk.Frame(container)
        btn_frame.setObjectName("providerToolbar")
        btn_frame.pack(fill="x", pady=(0, theme.SPACING["md"]))
        theme.icon_button(btn_frame, "open", "载入", color="#FFFFFF", bootstyle=PRIMARY, command=self.load_selected_preset).pack(side="left", padx=1)
        theme.icon_button(btn_frame, "save", "保存", color="#FFFFFF", bootstyle=SUCCESS, command=self.save_current_preset).pack(side="left", padx=1)
        theme.icon_button(btn_frame, "save_as", "另存", color="#FFFFFF", bootstyle=INFO, command=self.save_as_preset).pack(side="left", padx=1)
        theme.icon_button(btn_frame, "delete", "删除", color="#FFFFFF", bootstyle=DANGER, command=self.delete_selected_preset).pack(side="left", padx=1)
        theme.icon_button(btn_frame, "export", "导出", color="#FFFFFF", bootstyle=SECONDARY, command=self.export_settings).pack(side="left", padx=1)
        theme.icon_button(btn_frame, "import", "导入", color="#FFFFFF", bootstyle=SECONDARY, command=self.import_settings).pack(side="left", padx=1)

        # ┃ 方案信息
        section = self._create_section_title(container, "方案信息", "#9B59B6")
        section.pack(fill="x", pady=(theme.SPACING["md"], theme.SPACING["sm"]))

        self.preset_name_var = tk.StringVar(value=self.config_data.active_preset)

        name_frame = ttk.Frame(container)
        name_frame.pack(fill="x", pady=(0, theme.SPACING["sm"]))
        ttk.Label(name_frame, text="方案名称", font=(theme.FONT_FAMILY, 9)).pack(side="left", padx=(0, 4))
        ttk.Entry(name_frame, textvariable=self.preset_name_var, width=20).pack(side="left", fill="x", expand=True)

        ttk.Label(container, text="方案说明", font=(theme.FONT_FAMILY, 9)).pack(anchor="w", pady=(theme.SPACING["sm"], theme.SPACING["xs"]))
        self.preset_info = self._register_text(tk.Text(container, height=8, wrap="word"))
        self.preset_info.pack(fill="both", expand=True)

        self.refresh_presets()

    def _entry(self, parent, row: int, label: str, var: tk.Variable, show: str | None = None) -> int:
        ttk.Label(parent, text=label, font=(theme.FONT_FAMILY, 9)).grid(row=row, column=0, sticky="w", pady=3)
        ttk.Entry(parent, textvariable=var, show=show).grid(row=row, column=1, sticky="ew", pady=3)
        return row + 1

    def _shared_grading_provider_row(self, parent, row: int) -> int:
        # 服务商只出现一次，主评/副评/仲裁/OCR 共用它的 Key、端点和模型。
        ttk.Label(parent, text="当前服务商").grid(row=row, column=0, sticky="w", pady=6)
        combo = ttk.Combobox(parent, textvariable=self.primary_provider, values=self.provider_names(), state="readonly")
        combo.grid(row=row, column=1, sticky="ew", pady=6)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.on_shared_grading_provider_changed())
        self.shared_provider_combo = combo
        return row + 1

    def _model_only_row(self, parent, row: int, label: str, model_var: tk.StringVar) -> int:
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=6)
        combo = ttk.Combobox(parent, textvariable=model_var, values=self.model_names(self.primary_provider.get()), width=28)
        combo.grid(row=row, column=1, sticky="ew", pady=6)
        combo.bind("<<ComboboxSelected>>", lambda _e: self.on_shared_model_changed())
        combo.bind("<FocusOut>", lambda _e: self.on_shared_model_changed())
        if not hasattr(self, "shared_model_combos"):
            self.shared_model_combos = []
        self.shared_model_combos.append((model_var, combo))
        return row + 1

    def _labeled_text(self, parent, label: str, value: str, height: int) -> tk.Text:
        if label:
            ttk.Label(parent, text=label).pack(anchor="w")
        text = self._register_text(tk.Text(parent, height=height, wrap="word"))
        text.pack(fill="both", expand=True, pady=(4, 10))
        text.insert("1.0", value)
        return text
    def _sync_progress_bar(self, *_args) -> None:
        text = str(self.progress_var.get() or "0/0")
        current, _, total = text.partition("/")
        try:
            cur = int(str(current).strip())
        except Exception:
            cur = 0
        try:
            tot = int(str(total).strip())
        except Exception:
            tot = 0
        if tot <= 0:
            self.progress_bar.setRange(0, 0 if cur else 1)
            self.progress_bar.setValue(0)
            if hasattr(self, "graded_count"):
                self.graded_count.set(str(max(0, cur)))
            return
        self.progress_bar.setRange(0, tot)
        self.progress_bar.setValue(max(0, min(cur, tot)))
        if hasattr(self, "graded_count"):
            self.graded_count.set(str(max(0, cur)))

    def set_status(self, text: str) -> None:
        self.status_var.set(text)
        self.update_idletasks()

    def on_close(self) -> None:
        # 关窗时先停批改线程，避免窗口销毁后还在截屏或点鼠标。
        if getattr(self, "_closed", False):
            return
        self.running = False
        self.continuous = False
        self.paused = False
        watcher = getattr(self, "pause_hotkey_watcher", None)
        if watcher:
            watcher.stop()
        floating = getattr(self, "floating_boxes", None)
        if floating:
            floating.destroy()
        if not getattr(self, "_closed", False):
            self.destroy()

    def _finish_provider_action(self, status: str | None = None) -> None:
        """恢复服务商后台操作的按钮，避免请求结束后页面保持禁用。"""
        if getattr(self, "_closed", False):
            return
        self._provider_action_busy = False
        for button in self._provider_fetch_buttons + self._provider_test_buttons:
            button.setEnabled(True)
        if status is not None:
            self.provider_action_status.configure(text=status)

    def change_theme(self, _event=None) -> None:
        """切换主题 - 实时生效"""
        selected_display_name = self.theme_var.get()

        # 从中文名称找到英文主题名
        selected_theme = None
        for theme_key, theme_name in theme.AVAILABLE_THEMES.items():
            if theme_name == selected_display_name:
                selected_theme = theme_key
                break

        if not selected_theme:
            self.set_status("未知主题")
            return

        try:
            # 直接更改当前窗口的主题
            self.style.theme_use(selected_theme)
            theme.THEME_NAME = selected_theme
            self.set_status(f"主题已切换为 {selected_display_name}")
        except Exception as e:
            self.set_status(f"主题切换失败：{str(e)}")
            messagebox.showerror("错误", f"无法切换到该主题：{str(e)}")

    def save_all(self) -> None:
        # 保存时把主评/副评/仲裁/OCR 压回同一家供应商和同一个模型。
        shared_name = self.primary_provider.get() or self.config_data.active_provider
        shared_model = self.primary_model.get().strip()
        self.primary_provider.set(shared_name)
        self.secondary_provider.set(shared_name)
        self.arbitration_provider.set(shared_name)
        self.ocr_provider.set(shared_name)
        self.secondary_model.set(shared_model)
        self.arbitration_model.set(shared_model)
        self.ocr_model.set(shared_model)
        self._apply_role_models_to_providers()
        self.config_data.active_provider = shared_name
        self.config_data.workflow.primary_enabled = self.primary_enabled.get()
        self.config_data.workflow.dual_enabled = self.secondary_enabled.get()
        self.config_data.workflow.arbitration_enabled = self.arbitration_enabled.get()
        self.config_data.workflow.primary_provider_name = shared_name
        self.config_data.workflow.secondary_provider_name = shared_name
        self.config_data.workflow.arbitration_provider_name = shared_name
        self.config_data.workflow.ocr_provider_name = shared_name
        self.config_data.workflow.primary_model = shared_model
        self.config_data.workflow.secondary_model = shared_model
        self.config_data.workflow.arbitration_model = shared_model
        self.config_data.workflow.ocr_provider = provider_for_role(self.config_data, "ocr")
        self.config_data.workflow.secondary_provider = provider_for_role(self.config_data, "secondary")
        self.config_data.workflow.arbitration_provider = provider_for_role(self.config_data, "arbitration")
        self.config_data.workflow.mode = self._choice_value(self.GRADE_MODE_CHOICES, self.mode.get(), "normal")
        self.config_data.workflow.recognition_mode = "direct"
        self.config_data.workflow.dual_threshold = float(self.dual_threshold.get() or 2)
        self.config_data.workflow.capture_delay = float(self.capture_delay.get() or 0)
        self.config_data.workflow.scoring_delay = float(self.scoring_delay.get() or 0)
        self.config_data.workflow.next_paper_delay = float(self.next_paper_delay.get() or 0)
        self.config_data.workflow.score_switch_mode = "single"
        target_count = max(0, self._safe_int(self.target_count.get(), 0))
        self.config_data.workflow.target_count = target_count
        self.config_data.workflow.target_count_enabled = target_count > 0
        self.config_data.workflow.pause_hotkey = normalize_hotkey(self.pause_hotkey.get())
        self.pause_hotkey.set(self.config_data.workflow.pause_hotkey)
        self.config_data.workflow.retry_limit = max(1, self._safe_int(self.retry_limit.get(), 5))
        self.retry_limit.set(str(self.config_data.workflow.retry_limit))
        self.config_data.workflow.enable_abnormal_termination = bool(self.enable_abnormal_termination.get())
        self.config_data.workflow.abnormal_termination_count = max(1, self._safe_int(self.abnormal_termination_count.get(), 10))
        self.abnormal_termination_count.set(str(self.config_data.workflow.abnormal_termination_count))
        self.config_data.workflow.enable_page_refresh = bool(self.enable_page_refresh.get())
        self.config_data.workflow.page_refresh_frequency = max(1, self._safe_int(self.page_refresh_frequency.get(), 20))
        self.page_refresh_frequency.set(str(self.config_data.workflow.page_refresh_frequency))
        self.config_data.workflow.page_refresh_hotkey = normalize_hotkey(self.page_refresh_hotkey.get(), default="F5")
        self.page_refresh_hotkey.set(self.config_data.workflow.page_refresh_hotkey)
        try:
            self.config_data.workflow.page_refresh_wait_seconds = float(self.page_refresh_wait_seconds.get())
        except (TypeError, ValueError):
            self.config_data.workflow.page_refresh_wait_seconds = 5.0
        self.page_refresh_wait_seconds.set(str(self.config_data.workflow.page_refresh_wait_seconds))
        self.config_data.scoring.max_score = float(self.max_score.get() or 0)
        self.config_data.scoring.round_step = 1.0
        self.config_data.scoring.round_method = "round"
        self.config_data.scoring.diligence_enabled = False
        # 删除分小题评分功能
        self.config_data.preprocess_level = 1
        self.preprocess.set(1)
        self.config_data.recognition_margin = int(float(self.recognition_margin.get() or 0))
        self.config_data.blank_detection_enabled = self.blank_enabled.get()
        self.config_data.save_images = self.save_images.get()
        self.config_data.grade_level = "高中"
        self.config_data.subject = "生物"
        self.config_data.question_type = "填空"
        # 题目内容已删除，不再保存
        self.config_data.answer = self.answer.get("1.0", "end").strip()
        self.config_data.rubric = self.rubric.get("1.0", "end").strip()
        unify_grading_roles(self.config_data)
        save_config(self.config_data)
        self.refresh_boxes()
        self.set_status("配置已保存")

    def show_about(self) -> None:
        """显示关于对话框"""
        show_about_dialog(self)

    def show_history_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("历史记录")
        dialog.geometry("520x640")
        dialog.transient(self)
        theme.apply_window_icon(dialog)
        self._build_history_tab(dialog)
        dialog.wait_window()

    def show_preset_dialog(self) -> None:
        dialog = tk.Toplevel(self)
        dialog.title("方案管理")
        dialog.geometry("520x640")
        dialog.transient(self)
        theme.apply_window_icon(dialog)
        self._build_preset_tab(dialog)
        dialog.wait_window()

    def _safe_int(self, value: str, default: int = 0) -> int:
        try:
            return int(float(value or default))
        except (TypeError, ValueError):
            return default

    def apply_config_to_ui(self) -> None:
        self.active_provider.set(self.config_data.active_provider)
        self.primary_enabled.set(self.config_data.workflow.primary_enabled)
        self.secondary_enabled.set(self.config_data.workflow.dual_enabled)
        self.arbitration_enabled.set(self.config_data.workflow.arbitration_enabled)
        shared_name = self.config_data.workflow.primary_provider_name
        shared_model = self.config_data.workflow.primary_model or self._provider_model_name(shared_name)
        self.primary_provider.set(shared_name)
        self.secondary_provider.set(shared_name)
        self.arbitration_provider.set(shared_name)
        self.ocr_provider.set(shared_name)
        self.primary_model.set(shared_model)
        self.secondary_model.set(shared_model)
        self.arbitration_model.set(shared_model)
        self.ocr_model.set(shared_model)
        self.mode.set(self._choice_label(self.GRADE_MODE_CHOICES, self.config_data.workflow.mode))
        self.config_data.workflow.recognition_mode = "direct"
        self.recognition_mode.set(self._choice_label(self.RECOGNITION_MODE_CHOICES, "direct"))
        self.config_data.grade_level = "高中"
        self.config_data.subject = "生物"
        self.grade_level.set("高中")
        self.subject.set("生物")
        self.config_data.question_type = "填空"
        self.question_type.set("填空")
        self.max_score.set(str(self.config_data.scoring.max_score))
        self.config_data.scoring.round_step = 1.0
        self.config_data.scoring.round_method = "round"
        self.round_step.set("1")
        self.round_method.set(self._choice_label(self.ROUND_METHOD_CHOICES, "round"))
        self.refresh_shared_model_combos()
        self.save_images.set(self.config_data.save_images)
        self.config_data.preprocess_level = 1
        self.preprocess.set(1)
        self._refresh_preprocess_label()
        self.recognition_margin.set(str(self.config_data.recognition_margin))
        self.blank_enabled.set(self.config_data.blank_detection_enabled)
        self.dual_threshold.set(str(self.config_data.workflow.dual_threshold))
        self.capture_delay.set(str(self.config_data.workflow.capture_delay))
        self.scoring_delay.set(str(self.config_data.workflow.scoring_delay))
        self.next_paper_delay.set(str(self.config_data.workflow.next_paper_delay))
        self.config_data.workflow.score_switch_mode = "single"
        self.score_switch_mode.set(self._choice_label(self.SCORE_SWITCH_CHOICES, "single"))
        self.target_count.set(str(self.config_data.workflow.target_count))
        self.pause_hotkey.set(self.config_data.workflow.pause_hotkey)
        self.retry_limit.set(str(self.config_data.workflow.retry_limit))
        self.enable_abnormal_termination.set(self.config_data.workflow.enable_abnormal_termination)
        self.abnormal_termination_count.set(str(self.config_data.workflow.abnormal_termination_count))
        self.enable_page_refresh.set(self.config_data.workflow.enable_page_refresh)
        self.page_refresh_frequency.set(str(self.config_data.workflow.page_refresh_frequency))
        self.page_refresh_hotkey.set(self.config_data.workflow.page_refresh_hotkey)
        self.page_refresh_wait_seconds.set(str(self.config_data.workflow.page_refresh_wait_seconds))
        # 题目内容已删除
        self.answer.delete("1.0", "end")
        self.answer.insert("1.0", self.config_data.answer)
        self.rubric.delete("1.0", "end")
        self.rubric.insert("1.0", self.config_data.rubric)
        # 删除分小题评分功能
        self.refresh_boxes()
        self.refresh_provider_tree()
        self.refresh_provider_combos()
        self.refresh_material_images()

    def refresh_material_images(self) -> None:
        if not hasattr(self, "material_list"):
            return
        self.material_list.delete(0, "end")
        for path in self.config_data.material_images:
            self.material_list.insert("end", path)

    def add_material_images(self) -> None:
        paths = filedialog.askopenfilenames(filetypes=[("图片文件", "*.png;*.jpg;*.jpeg;*.bmp;*.webp"), ("所有文件", "*.*")])
        if not paths:
            return
        existing = set(self.config_data.material_images)
        for path in paths:
            if path not in existing:
                self.config_data.material_images.append(path)
        self.refresh_material_images()
        self.set_status(f"已添加评分材料图片：{len(paths)}张")

    def remove_material_image(self) -> None:
        if not hasattr(self, "material_list"):
            return
        selected = list(self.material_list.curselection())
        for index in reversed(selected):
            if 0 <= index < len(self.config_data.material_images):
                self.config_data.material_images.pop(index)
        self.refresh_material_images()

    def open_material_image(self) -> None:
        if not hasattr(self, "material_list"):
            return
        selected = self.material_list.curselection()
        if not selected:
            return
        path = self.config_data.material_images[selected[0]]
        os.startfile(path)

    def get_box(self, kind: str) -> RegionBox | None:
        self.config_data.boxes = normalize_operation_boxes(self.config_data.boxes)
        return next((b for b in self.config_data.boxes if b.kind == kind and b.enabled), None)

    @staticmethod
    def _box_too_small(box: RegionBox, kind: str) -> bool:
        min_w, min_h = theme.BOX_MIN_SIZE[kind]
        return box.width < min_w or box.height < min_h

    def add_box(self, kind: str) -> None:
        self.config_data.boxes = normalize_operation_boxes(self.config_data.boxes)
        existing_index = next((i for i, box in enumerate(self.config_data.boxes) if box.kind == kind), None)
        if existing_index is not None:
            self.refresh_boxes()
            if hasattr(self, "box_tree"):
                self.box_tree.selection_set(str(existing_index))
                self.box_tree.see(str(existing_index))
            floating = getattr(self, "floating_boxes", None)
            if floating:
                self.show_floating_boxes()
                floating.raise_kind(kind)
            self.set_status("该类型操作框已存在，可直接拖拽调整")
            return

        meta = theme.BOX_META[kind]
        w, h = meta["size"]
        self.config_data.boxes.append(RegionBox(meta["name"], kind, 180 + len(self.config_data.boxes) * 30, 180, w, h, meta["color"]))
        self.config_data.boxes = normalize_operation_boxes(self.config_data.boxes)
        self._save_boxes()
        self.refresh_boxes()
        floating = getattr(self, "floating_boxes", None)
        if floating:
            self.show_floating_boxes()
            floating.raise_kind(kind)
        self.set_status("操作框已添加，可直接在桌面拖拽调整")

    def add_all_boxes(self) -> None:
        for kind in ("recognition", "score", "submit"):
            self.add_box(kind)

    def refresh_boxes(self) -> None:
        self.config_data.boxes = normalize_operation_boxes(self.config_data.boxes)
        if hasattr(self, "score_box_count"):
            self.score_box_count.set(str(sum(1 for box in self.config_data.boxes if box.kind == "score")))
        if not hasattr(self, "box_tree"):
            return
        self.box_tree.delete(*self.box_tree.get_children())
        for i, b in enumerate(self.config_data.boxes):
            self.box_tree.insert("", "end", iid=str(i), values=(b.name, b.kind, b.x, b.y, b.width, b.height))
        floating = getattr(self, "floating_boxes", None)
        if floating:
            floating.sync(self.config_data.boxes)

    def open_overlay(self) -> None:
        self.show_floating_boxes()

    def _ensure_floating_boxes(self) -> None:
        if getattr(self, "floating_boxes", None) is None:
            self.floating_boxes = FloatingBoxManager(
                self,
                self.config_data.boxes,
                self.refresh_boxes,
                self._save_boxes,
            )
        else:
            self.floating_boxes.sync(self.config_data.boxes)

    def _save_boxes(self) -> None:
        self.config_data.boxes = normalize_operation_boxes(self.config_data.boxes)
        save_config(self.config_data)

    def show_floating_boxes(self) -> None:
        self._ensure_floating_boxes()
        self.floating_boxes.show()
        if hasattr(self, "toggle_boxes_button"):
            theme.set_icon_button(self.toggle_boxes_button, "hide", "隐藏调整框")
        self.set_status("调整框已显示，可直接拖拽修改位置")

    def toggle_floating_boxes(self) -> None:
        self._ensure_floating_boxes()
        visible = self.floating_boxes.toggle()
        if hasattr(self, "toggle_boxes_button"):
            theme.set_icon_button(self.toggle_boxes_button, "hide" if visible else "eye", "隐藏调整框" if visible else "显示调整框")
        self.set_status("调整框已显示" if visible else "调整框已隐藏")

    def _hide_floating_boxes_temporarily(self) -> bool:
        floating = getattr(self, "floating_boxes", None)
        if not floating:
            return False
        floating.hide()
        if hasattr(self, "toggle_boxes_button"):
            theme.set_icon_button(self.toggle_boxes_button, "eye", "显示调整框")
        self.update_idletasks()
        return False

    def _restore_floating_boxes(self, was_visible: bool) -> None:
        return

    def delete_selected_box(self) -> None:
        if not hasattr(self, "box_tree"):
            return
        selected = list(self.box_tree.selection())
        if not selected:
            self.set_status("请先选择要删除的操作框")
            return
        for iid in sorted((int(item) for item in selected), reverse=True):
            if 0 <= iid < len(self.config_data.boxes):
                self.config_data.boxes.pop(iid)
        self.config_data.boxes = normalize_operation_boxes(self.config_data.boxes)
        self._save_boxes()
        self.refresh_boxes()
        floating = getattr(self, "floating_boxes", None)
        if floating:
            floating.sync(self.config_data.boxes)
        self.set_status("已删除选中的操作框")

    def preview_capture(self) -> None:
        box = self.get_box("recognition")
        if not box:
            messagebox.showerror("缺少识别框", "请先添加识别框")
            return
        was_visible = self._hide_floating_boxes_temporarily()
        try:
            img = preprocess_image(capture_region(box, self.config_data.recognition_margin), self.config_data.preprocess_level)
        finally:
            self._restore_floating_boxes(was_visible)
        report = image_quality_report(img)
        path = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG 图片", "*.png")])
        if path:
            img.save(path)
            self.set_status(f"截图已保存：{path}；质量：{report['level']}，尺寸 {report['width']}x{report['height']}")

    def start_grading(self) -> None:
        """执行全量配置检查后，开启连续批改。"""
        self.save_all()
        ollama_errors = self._refresh_ollama_before_grading()
        if ollama_errors:
            messagebox.showerror("Ollama 未就绪", "\n".join(ollama_errors))
            return
        
        # 第一步：全量配置检查
        problems = self._validate_ready_to_grade()
        if problems:
            messagebox.showerror("准备不足，无法启动批改", "\n\n".join(problems))
            return
        
        # 第二步：快速预检（截一张图验证质量）
        was_visible = self._hide_floating_boxes_temporarily()
        preview_ok = self._preview_before_grading()
        if not preview_ok:
            self._restore_floating_boxes(was_visible)
            return
        
        # 第三步：确认开始
        target = self.config_data.workflow.target_count if self.config_data.workflow.target_count_enabled else 0
        msg = f"即将开始连续批改，目标份数：{target if target > 0 else '无限'}\n\n各项配置均已检查无误，点击确认开始自动批改。"
        if messagebox.askokcancel("准备开始", msg):
            self._start_continuous_grading()
        else:
            self._restore_floating_boxes(was_visible)
    
    def _validate_ready_to_grade(self) -> list[str]:
        """全量检查，确保所有批改必要条件都满足。返回问题列表。"""
        problems = []
        self.config_data.boxes = normalize_operation_boxes(self.config_data.boxes)
        
        # 检查三个操作框
        recog_box = self.get_box("recognition")
        score_box = self.get_box("score")
        submit_box = self.get_box("submit")
        
        if not recog_box:
            problems.append("❌ 识别框缺失\n请在主界面添加识别框，用于截取答题区域。")
        elif self._box_too_small(recog_box, "recognition"):
            problems.append("❌ 识别框过小\n识别框尺寸应至少 50×50px，请调整大小。")

        if not score_box:
            problems.append("❌ 打分框缺失\n请添加打分框，AI 分数需要填入此区域。")
        elif self._box_too_small(score_box, "score"):
            problems.append("❌ 打分框过小\n打分框应能容纳分数，请调整大小。")

        if not submit_box:
            problems.append("❌ 提交框缺失\n请添加提交框，用于自动点击提交。")
        elif self._box_too_small(submit_box, "submit"):
            problems.append("❌ 提交框过小\n提交框应能正常点击，请调整大小。")
        
        # 检查 AI 参数
        if not self.config_data.workflow.primary_enabled:
            problems.append('❌ 主评未启用\n请在配置面板勾选"启用主评"。')
        else:
            provider = self.get_active_provider()
            if not provider.endpoint:
                problems.append("❌ 主评 API 端点缺失\n请填写 API Endpoint。")
            if provider.requires_api_key and not provider.api_key:
                problems.append("❌ 主评 API Key 缺失\n请填写 API Key。")
            if not provider.model:
                problems.append("❌ 模型名称缺失\n请选择或填写模型名称。")
        
        # 检查评分依据
        if not (self.config_data.question or self.config_data.answer or self.config_data.rubric or self.config_data.material_images):
            problems.append("❌ 评分依据不足\n请至少填写题目、参考答案或评分标准之一。")
        
        # 检查批改份数
        if self.config_data.workflow.target_count_enabled:
            if self.config_data.workflow.target_count <= 0:
                problems.append("❌ 目标份数设置错误\n启用限制时，份数应大于 0。")
        
        return problems
    
    def _preview_before_grading(self) -> bool:
        """截一张图并检查质量，确保识别框位置和大小合适。"""
        try:
            recog_box = self.get_box("recognition")
            if not recog_box:
                messagebox.showerror("预检失败", "无法找到识别框")
                return False
            
            # 截图
            img = preprocess_image(
                capture_region(recog_box, self.config_data.recognition_margin),
                self.config_data.preprocess_level
            )
            quality = image_quality_report(img)
            
            # 检查图像质量
            issues = []
            if quality['width'] < 50 or quality['height'] < 50:
                issues.append(f"图像尺寸过小：{quality['width']}×{quality['height']}px")
            
            if quality["dark_ratio"] > 0.95:
                issues.append("图像过暗（暗像素占比 >95%），可能无法识别")
            if quality["level"] in {"识别框偏小", "画面偏暗", "对比度偏低"}:
                issues.append(f"图像质量评估：{quality['level']}，建议检查截图框位置、光线和对焦")
            if quality["level"] == "可能为空白" and not self.config_data.blank_detection_enabled:
                issues.append("当前截图很像空白答题卡，建议确认识别框是否框住学生答案")
            
            if issues:
                msg = "识别框预检发现问题：\n\n" + "\n".join(f"• {i}" for i in issues)
                msg += "\n\n是否继续？（建议先调整截图框位置或光线）"
                if not messagebox.askokcancel("预检警告", msg):
                    return False
            else:
                messagebox.showinfo("预检通过", f"识别框质量良好\n尺寸：{quality['width']}×{quality['height']}px，质量：{quality['level']}\n准备好了，点确认开始")
            
            return True
        except Exception as e:
            messagebox.showerror("预检出错", f"截图或质量检查失败：{str(e)}")
            return False
    
    def _start_continuous_grading(self) -> None:
        """开启连续批改模式，直接自动填分和提交。"""
        self.save_all()
        problems = self.validate_config(require_submit=True)
        if problems:
            messagebox.showerror("配置未就绪", "\n".join(problems))
            return
        self.running = True
        self.continuous = True
        self.paused = False
        self.skip_blank_once = False
        self.loop_count = 0
        self._refresh_pause_button()
        target = self.config_data.workflow.target_count if self.config_data.workflow.target_count_enabled else 0
        self.progress_var.set(f"0/{target or '不限'}")
        hotkey = self.config_data.workflow.pause_hotkey or "F8"
        self.set_status(f"连续批改中，按 {hotkey} 可暂停")
        # 自动填分提交，不需要确认窗口
        threading.Thread(target=self._loop_worker, daemon=True).start()
    
    def start_once(self) -> None:
        """调试专用：单份批改，不自动提交。"""
        self.save_all()
        ollama_errors = self._refresh_ollama_before_grading()
        if ollama_errors:
            messagebox.showerror("Ollama 未就绪", "\n".join(ollama_errors))
            return
        problems = self.validate_config(require_submit=False)
        if problems:
            messagebox.showerror("配置未就绪", "\n".join(problems))
            return
        self._restore_boxes_after_worker = self._hide_floating_boxes_temporarily()
        self.running = True
        self.continuous = False
        self.paused = False
        self.skip_blank_once = False
        self._refresh_pause_button()
        threading.Thread(target=self._grade_once_worker, kwargs={"auto_submit": False}, daemon=True).start()

    def debug_once(self) -> None:
        self.save_all()
        ollama_errors = self._refresh_ollama_before_grading()
        if ollama_errors:
            messagebox.showerror("Ollama 未就绪", "\n".join(ollama_errors))
            return
        problems = self.validate_config(require_submit=False)
        if problems:
            messagebox.showerror("调试批改不可用", "\n".join(problems))
            return
        self._restore_boxes_after_worker = self._hide_floating_boxes_temporarily()
        self.running = True
        self.continuous = False
        self.paused = False
        self.skip_blank_once = False
        self._refresh_pause_button()
        self.set_status("调试批改：仅处理一份，不自动提交")
        threading.Thread(target=self._grade_once_worker, kwargs={"auto_submit": False}, daemon=True).start()

    def stop(self) -> None:
        self.running = False
        self.continuous = False
        self.paused = False
        self._refresh_pause_button()
        target = self.config_data.workflow.target_count if self.config_data.workflow.target_count_enabled else 0
        if self.loop_count:
            self.progress_var.set(f"{self.loop_count}/{target or '不限'}")
        self.set_status("已停止")

    def validate_config(self, require_submit: bool) -> list[str]:
        problems: list[str] = []
        if not self.get_box("recognition"):
            problems.append("缺少识别框。")
        if require_submit:
            if not self.get_box("score"):
                problems.append("连续自动提交需要打分框。")
            if not self.get_box("submit"):
                problems.append("连续自动提交需要提交框。")
        if not self.config_data.workflow.primary_enabled:
            problems.append("主评未启用。")
        provider = self.get_active_provider()
        if not provider.endpoint:
            problems.append("主评服务商缺少 API 端点。")
        if provider.requires_api_key and not provider.api_key:
            problems.append("主评服务商缺少 API Key。")
        if not provider.model:
            problems.append("服务商缺少模型名称。")
        if not (self.config_data.question or self.config_data.answer or self.config_data.rubric or self.config_data.material_images):
            problems.append("题目、参考答案、评分标准或评分材料图片至少填写一项。")
        return problems

    def check_readiness(self) -> None:
        self.save_all()
        problems = self.validate_config(require_submit=False)
        if problems:
            messagebox.showwarning("配置未就绪", "\n".join(problems))
            self.set_status("配置未就绪")
            return
        messagebox.showinfo("配置检查", "基础配置已就绪。调试批改不会要求打分框和提交框；连续自动提交前请确认操作框位置。")
        self.set_status("配置已就绪")

    def _wait_if_paused(self) -> None:
        """连续批改被手动暂停时在这里等，停止后立刻退出。"""
        while getattr(self, "paused", False) and self.running:
            time.sleep(0.05)

    def _interruptible_sleep(self, seconds: float) -> None:
        deadline = time.monotonic() + max(0.0, float(seconds or 0))
        while self.running and time.monotonic() < deadline:
            self._wait_if_paused()
            if not self.running:
                return
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.05, remaining))

    def _on_pause_hotkey(self) -> None:
        # 热键来自后台线程，丢进 UI 队列，避免直接碰 Tk。
        self.work_queue.put(("pause_toggle", None))

    def toggle_pause(self) -> None:
        """只有连续批改进行中才响应暂停/继续。"""
        if not (self.running and self.continuous):
            return
        self.paused = not bool(self.paused)
        hotkey = getattr(getattr(self.config_data, "workflow", None), "pause_hotkey", "F8") or "F8"
        if self.paused:
            self.set_status(f"已暂停，按 {hotkey} 继续")
        else:
            self.set_status("继续批改")
        self._refresh_pause_button()

    def _refresh_pause_button(self) -> None:
        button = getattr(self, "pause_button", None)
        if button is None:
            return
        active = bool(self.running and self.continuous)
        text = "继续" if self.paused and active else "暂停"
        state = "normal" if active else "disabled"
        icon = "play" if self.paused and active else "pause"
        try:
            theme.set_icon_button(button, icon, text, color="#FFFFFF", state=state)
        except Exception:
            button.configure(text=text, state=state)

    def _make_grading_session(self, stream_callback=None) -> GradingSession:
        return GradingSession(
            pipeline_config_from_app_config(self.config_data),
            AppGradingHooks(self, stream_callback=stream_callback),
        )

    def _send_page_refresh_hotkey(self, spec: str) -> bool:
        try:
            parsed = parse_hotkey(spec)
            keys: list[str] = []
            if parsed.ctrl:
                keys.append("ctrl")
            if parsed.alt:
                keys.append("alt")
            if parsed.shift:
                keys.append("shift")
            keys.append(parsed.display.split("+")[-1].lower())
            import pyautogui
            pyautogui.hotkey(*keys)
            return True
        except Exception:
            return False

    def _loop_worker(self) -> None:
        self._wait_if_paused()
        if not self.running:
            return
        # next_paper_delay is consumed inside GradingSession.run_loop
        _ = max(0, self.config_data.workflow.next_paper_delay)
        try:
            self._make_grading_session(stream_callback=None).run_loop()
        except Exception as exc:
            self.running = False
            self.continuous = False
            self.paused = False
            self.work_queue.put(("error", str(exc)))
            return
        still_running = bool(self.running)
        self.running = False
        self.continuous = False
        self.paused = False
        if still_running:
            self.work_queue.put(("history", None))

    def _grade_once_worker(self, auto_submit: bool = False) -> None:
        try:
            self._wait_if_paused()
            if not self.running:
                return
            callback = None if self.continuous else (lambda text: self.work_queue.put(("output", text)))
            card_index = -1 if not auto_submit else max(0, int(self.loop_count or 0))
            self._make_grading_session(stream_callback=callback).process_one(
                card_index=card_index,
                auto_submit=auto_submit,
            )
        except GradingNetworkRecoverable as exc:
            self.running = False
            self.continuous = False
            self.paused = False
            self.work_queue.put(("error", str(exc)))
        except Exception as exc:
            self.running = False
            self.continuous = False
            self.paused = False
            self.work_queue.put(("error", str(exc)))
        finally:
            self.running = False
            self.continuous = False
            self.paused = False

    def _poll_queue(self) -> None:
        if getattr(self, "_closed", False):
            return
        try:
            while True:
                kind, payload = self.work_queue.get_nowait()
                if kind == "status":
                    if self._provider_action_busy and "连接成功" in str(payload):
                        self._finish_provider_action("服务商测试完成")
                    self.set_status(payload)
                    self._refresh_pause_button()
                elif kind == "pause_toggle":
                    self.toggle_pause()
                elif kind == "progress":
                    self.progress_var.set(payload)
                elif kind == "output":
                    # 连续批改时跳过AI输出更新，减少UI刷新
                    if not self.continuous:
                        self.output.insert("end", payload)
                elif kind == "history":
                    self.refresh_history()
                    self._refresh_pause_button()
                elif kind == "result":
                    if isinstance(payload, tuple):
                        result, image, auto_submit = payload
                    else:
                        result, image, auto_submit = payload, None, False
                    self._show_result(result, image, auto_submit)
                    if not self.continuous and self._restore_boxes_after_worker:
                        self._restore_floating_boxes(True)
                        self._restore_boxes_after_worker = False
                elif kind == "models":
                    self._finish_provider_action("模型获取完成")
                    models = list(payload.get("models") or [])
                    self._apply_fetched_models(models, index=payload.get("index"))
                    name = payload.get("name") or "当前服务商"
                    current = self.provider_model_var.get() or (models[0] if models else "")
                    self.set_status(f"{name} 已获取 {len(models)} 个模型，当前可选：{current}")
                elif kind == "error":
                    self._finish_provider_action("操作失败")
                    if self._restore_boxes_after_worker:
                        self._restore_floating_boxes(True)
                        self._restore_boxes_after_worker = False
                    self.set_status("出错")
                    self._refresh_pause_button()
                    title = "获取模型失败" if "获取模型失败" in str(payload) else "批改失败"
                    messagebox.showerror(title, payload)
        except queue.Empty:
            pass
        if not getattr(self, "_closed", False):
            self.after(150, self._poll_queue)

    def _update_process_views(self, result: dict[str, Any]) -> None:
        """把最新批改结果同步到评分过程页的所有结果控件。"""
        self.current_result = result
        # 1. 更新识别答案区域（最重要）
        self.answer_view.delete("1.0", "end")
        student_answer = result.get("student_answer", "")
        self.answer_view.insert("1.0", student_answer)
        self.answer_view.tag_add("highlight", "1.0", "end")

        # 2. 更新参考答案对比区域
        self.reference_view.configure(state="normal")
        self.reference_view.delete("1.0", "end")
        self.reference_view.insert("1.0", self.config_data.answer or "（未设置参考答案）")
        self.reference_view.tag_add("ref", "1.0", "end")
        self.reference_view.configure(state="disabled")

        # 3. 更新评分结果（醒目显示）
        final_score = result.get("final_score")
        max_score = result.get("max_score", self._max_score())
        ai_score = result.get("ai_score")

        # 最终得分大号显示
        if final_score is not None:
            score_text = f"{final_score:.1f}" if isinstance(final_score, (int, float)) else str(final_score)
            self.final_score_label.configure(text=score_text)

            # 根据得分率改变颜色 - 使用主题色
            if max_score > 0:
                score_rate = final_score / max_score
                if score_rate >= 0.9:
                    self.final_score_label.configure(bootstyle=SUCCESS, foreground=theme.COLORS["success"])
                elif score_rate >= 0.6:
                    self.final_score_label.configure(bootstyle=WARNING, foreground=theme.COLORS["warning"])
                else:
                    self.final_score_label.configure(bootstyle=DANGER, foreground=theme.COLORS["danger"])
        else:
            self.final_score_label.configure(text="--", bootstyle=SECONDARY)

        # 更新详细分数信息 - 使用独立标签
        self.ai_score_value.configure(text=f"{ai_score:.1f}" if ai_score is not None else "--")
        self.max_score_value.configure(text=f"{max_score:.1f}" if max_score else "--")

        # 4. 更新评分说明
        self.comment_view.delete("1.0", "end")
        comment = result.get("comment", "")
        basis = result.get("basis", "")

        if comment:
            self.comment_view.insert("end", comment + "\n")
            self.comment_view.tag_add("comment", "1.0", "end")

        if basis:
            self.comment_view.insert("end", f"\n{'='*40}\n评分依据:\n{basis}")
            basis_start = self.comment_view.index("end-1c linestart-3l")
            self.comment_view.tag_add("basis", basis_start, "end")

        # 5. 更新AI详细输出
        self.output.delete("1.0", "end")
        self.output.insert("end", f"\n\n{'='*50}\n")
        self.output.insert("end", f"✓ 批改完成时间: {time.strftime('%H:%M:%S')}\n")
        self.output.insert("end", f"✓ 最终得分: {final_score}\n")

        if result.get("sub_scores"):
            sub_scores_text = ", ".join([f"{s.get('label', '')}:{s.get('score', 0):.1f}" for s in result.get("sub_scores", [])])
            self.output.insert("end", f"✓ 小题得分: {sub_scores_text}\n")

        if result.get("dual_eval"):
            dual = result.get("dual_eval")
            self.output.insert("end", f"✓ 双评信息: 主评{dual.get('primary_score')} | 副评{dual.get('secondary_score')} | 差值{dual.get('diff')}\n")

        if result.get("quality"):
            quality = result.get("quality")
            self.output.insert("end", f"✓ 图像质量: {quality.get('level')} ({quality.get('width')}×{quality.get('height')})\n")

    def _show_result(self, result: dict[str, Any], image=None, auto_submit: bool = False) -> None:
        """展示最新批改结果，单次和连续批改共用同一套结果视图。"""
        self.current_image = image
        self._update_process_views(result)
        self._save_history_record(result)

        # 连续批改不频繁重绘历史列表，但评分过程页始终显示最新结果。
        if self.continuous:
            status = "✓ 批改完成，已自动提交"
        else:
            self.refresh_history()
            self.work_canvas.yview_moveto(0)
            status = "✓ 批改完成"

        self.set_status(status)

    def _score_values_for_fill(self, result: dict[str, Any]) -> list[float | int | str]:
        if self.config_data.workflow.score_switch_mode == "single":
            return [result.get("final_score", 0)]
        values = [item.get("score") for item in result.get("sub_scores", []) if item.get("score") is not None]
        return values or [result.get("final_score", 0)]

    def _save_history_record(self, result: dict[str, Any], corrected: bool = False) -> None:
        add_history({
            "preset": self.config_data.active_preset,
            "mode": self.config_data.workflow.mode,
            "student_answer": result.get("student_answer", ""),
            "ai_score": result.get("ai_score"),
            "final_score": result.get("final_score"),
            "comment": result.get("comment", ""),
            "corrected": corrected,
            "sub_scores": result.get("sub_scores", []),
            "bonus": result.get("bonus", 0),
            "dual_eval": result.get("dual_eval"),
            "image_base64": result.get("image_base64", ""),
        })

    def capture_blank_reference(self) -> None:
        box = self.get_box("recognition")
        if not box:
            messagebox.showerror("缺少识别框", "请先添加识别框")
            return
        was_visible = self._hide_floating_boxes_temporarily()
        try:
            img = preprocess_image(capture_region(box, self.config_data.recognition_margin), self.config_data.preprocess_level)
        finally:
            self._restore_floating_boxes(was_visible)
        data = black_pixel_ratio(img)
        save_blank_reference(data)
        self.set_status(f"空白卡范本已保存，占比 {data['ratio'] * 100:.2f}%")

    def _max_score(self) -> float:
        return sum(u.max_score for u in self.config_data.scoring.units) if self.config_data.scoring.units else self.config_data.scoring.max_score

    def _refresh_ollama_before_grading(self) -> list[str]:
        provider = self.get_provider_by_name(self.primary_provider.get())
        if not provider or provider.protocol != "ollama":
            return []
        errors = refresh_ollama_providers([provider])
        if errors:
            return errors
        models = provider.available_models()
        if self.primary_model.get() not in models:
            self.primary_model.set(provider.model)
        self.secondary_model.set(self.primary_model.get())
        self.arbitration_model.set(self.primary_model.get())
        self.ocr_model.set(self.primary_model.get())
        self.refresh_provider_combos()
        return []

    def _provider_from_form(self, base: Provider | None = None) -> Provider:
        from dataclasses import replace
        provider = Provider() if base is None else replace(base)
        provider.name = self.provider_name_var.get().strip() or provider.name
        provider.endpoint = self.provider_endpoint_var.get().strip()
        provider.api_key = self.provider_key_var.get().strip()
        provider.model = self.provider_model_var.get().strip()
        provider.source = self._choice_value(self.PROVIDER_SOURCE_CHOICES, self.provider_source_var.get().strip(), "network")
        provider.protocol = self._choice_value(self.PROVIDER_PROTOCOL_CHOICES, self.provider_protocol_var.get().strip(), "openai_compatible")
        provider.api_format = self._choice_value(self.API_FORMAT_CHOICES, self.provider_api_format_var.get().strip(), "")
        provider.reasoning_effort = self._choice_value(self.REASONING_CHOICES, self.provider_reasoning_var.get().strip(), "medium")
        models = [x.strip() for x in self.provider_models_var.get().replace("\n", ",").split(",") if x.strip()]
        if provider.model and provider.model not in models:
            models.insert(0, provider.model)
        provider.models = models
        return provider

    def _apply_fetched_models(self, models: list[str], keep_current: bool = True, index: int | None = None) -> None:
        current = self.provider_model_var.get().strip()
        models = [item for item in models if item]
        if keep_current and current and current not in models:
            models = [current] + models
        elif not current and models:
            current = models[0]
        if current not in models and models:
            current = models[0]
        self.provider_models_var.set(", ".join(models))
        self.provider_model_combo.configure(values=models)
        if current:
            self.provider_model_var.set(current)
        if index is None:
            index = self._selected_provider_index()
        if isinstance(index, int) and 0 <= index < len(self.config_data.providers):
            provider = self.config_data.providers[index]
            provider.models = list(models)
            if current:
                provider.model = current
        self.refresh_provider_combos()

    def fetch_provider_models(self) -> None:
        index = self._selected_provider_index()
        if index is None:
            messagebox.showinfo("未选择服务商", "请先选择一个服务商")
            return
        snapshot = self._provider_from_form(self.config_data.providers[index])
        self._provider_action_busy = True
        for button in self._provider_fetch_buttons + self._provider_test_buttons:
            button.setEnabled(False)
        self.provider_action_status.configure(text=f"正在获取模型：{snapshot.name}")
        self.set_status(f"正在获取模型：{snapshot.name}")

        def worker() -> None:
            try:
                models = list_provider_models(snapshot)
                self.work_queue.put(("models", {"index": index, "models": models, "name": snapshot.name}))
            except Exception as exc:
                self.work_queue.put(("error", f"{snapshot.name} 获取模型失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_selected_ollama_models(self, show_warning: bool = True) -> None:
        if show_warning:
            self.fetch_provider_models()
            return
        index = self._selected_provider_index()
        if index is None or index >= len(self.config_data.providers):
            return
        provider = self.config_data.providers[index]
        if provider.protocol != "ollama":
            return
        try:
            models = list_provider_models(provider)
        except Exception:
            return
        if models:
            provider.models = models
            if provider.model not in models:
                provider.model = models[0]
            self._apply_fetched_models(models)
            self.set_status(f"已发现 {len(models)} 个模型，当前：{self.provider_model_var.get()}")

    def provider_names(self) -> list[str]:
        return [p.name for p in self.config_data.providers]

    def model_names(self, provider_name: str) -> list[str]:
        provider = self.get_provider_by_name(provider_name)
        return provider.available_models() if provider else []

    def on_shared_model_changed(self) -> None:
        # 模型下拉框改完后，四个角色立刻同步成同一个模型。
        shared_model = self.primary_model.get().strip()
        self.secondary_model.set(shared_model)
        self.arbitration_model.set(shared_model)
        self.ocr_model.set(shared_model)

    def on_shared_grading_provider_changed(self) -> None:
        # 切换服务商后，四个角色都使用这家供应商的当前模型。
        shared_name = self.primary_provider.get()
        self.secondary_provider.set(shared_name)
        self.arbitration_provider.set(shared_name)
        self.ocr_provider.set(shared_name)
        models = self.model_names(shared_name)
        current = self.primary_model.get()
        if models and current not in models:
            current = models[0]
            self.primary_model.set(current)
        self.secondary_model.set(self.primary_model.get())
        self.arbitration_model.set(self.primary_model.get())
        self.ocr_model.set(self.primary_model.get())
        for model_var, combo in getattr(self, "shared_model_combos", []):
            combo.configure(values=models)
            if models and model_var.get() not in models:
                model_var.set(self.primary_model.get())

    def refresh_shared_model_combos(self) -> None:
        models = self.model_names(self.primary_provider.get())
        current = self.primary_model.get()
        if models and current not in models:
            current = models[0]
            self.primary_model.set(current)
        self.secondary_model.set(self.primary_model.get())
        self.arbitration_model.set(self.primary_model.get())
        self.ocr_model.set(self.primary_model.get())
        for model_var, combo in getattr(self, "shared_model_combos", []):
            combo.configure(values=models)
            if models and model_var.get() not in models:
                model_var.set(self.primary_model.get())

    def _apply_role_models_to_providers(self) -> None:
        # 四个角色共用同一个模型，写回当前服务商。
        shared = self.get_provider_by_name(self.primary_provider.get())
        if shared and self.primary_model.get():
            shared.model = self.primary_model.get()
            if shared.model not in shared.models:
                shared.models.insert(0, shared.model)

    def get_provider_by_name(self, name: str) -> Provider | None:
        return next((p for p in self.config_data.providers if p.name == name), None)

    def get_active_provider(self) -> Provider:
        provider_name = self.config_data.workflow.primary_provider_name or self.config_data.active_provider
        provider = self.get_provider_by_name(provider_name) or (self.config_data.providers[0] if self.config_data.providers else Provider())
        self.config_data.active_provider = provider.name
        return provider

    def refresh_provider_combos(self) -> None:
        names = self.provider_names()
        if hasattr(self, "shared_provider_combo"):
            self.shared_provider_combo.configure(values=names)
            if self.primary_provider.get() not in names and names:
                self.primary_provider.set(names[0])
            self.secondary_provider.set(self.primary_provider.get())
            self.arbitration_provider.set(self.primary_provider.get())
            self.ocr_provider.set(self.primary_provider.get())
            self.refresh_shared_model_combos()

    def refresh_provider_selector(self) -> None:
        """刷新服务商下拉选择器"""
        if not hasattr(self, "provider_selector"):
            return

        # 获取所有服务商名称
        provider_names = [p.name for p in self.config_data.providers]
        self.provider_selector.configure(values=provider_names)

        # 设置当前选中的服务商
        if provider_names:
            current = self.config_data.active_provider
            if current in provider_names:
                self.provider_selector_var.set(current)
            else:
                self.provider_selector_var.set(provider_names[0])
                # 加载第一个服务商的配置
                self._load_provider_by_name(provider_names[0])

        self.refresh_provider_combos()

    def _load_provider_by_name(self, name: str) -> None:
        """根据名称加载服务商配置到表单"""
        provider = next((p for p in self.config_data.providers if p.name == name), None)
        if not provider:
            return

        self.provider_name_var.set(provider.name)
        self.provider_endpoint_var.set(provider.endpoint)
        self.provider_key_var.set(provider.api_key)
        self.provider_model_var.set(provider.model)
        self.provider_models_var.set(", ".join(provider.available_models()))
        if hasattr(self, "provider_model_combo"):
            self.provider_model_combo.configure(values=provider.available_models())
        self.provider_reasoning_var.set(self._choice_label(self.REASONING_CHOICES, provider.reasoning_effort or "medium"))
        self.provider_source_var.set(self._choice_label(self.PROVIDER_SOURCE_CHOICES, provider.source))
        self.provider_protocol_var.set(self._choice_label(self.PROVIDER_PROTOCOL_CHOICES, provider.protocol))
        self.provider_api_format_var.set(self._choice_label(self.API_FORMAT_CHOICES, getattr(provider, "api_format", "") or ""))

    def on_provider_selector_changed(self, _event=None) -> None:
        """下拉选择器改变时"""
        selected_name = self.provider_selector_var.get()
        if selected_name:
            self._load_provider_by_name(selected_name)

    def refresh_provider_tree(self) -> None:
        # 新版：使用下拉选择器
        if hasattr(self, "provider_selector"):
            self.refresh_provider_selector()
            return

        # 旧版：兼容Treeview（如果还存在）
        if not hasattr(self, "provider_tree"):
            return
        self.provider_tree.delete(*self.provider_tree.get_children())
        for index, provider in enumerate(self.config_data.providers):
            marker = " *" if provider.name == self.config_data.active_provider else ""
            self.provider_tree.insert("", "end", iid=str(index), values=(provider.name + marker, provider.model))
        self.refresh_provider_combos()

    def _selected_provider_index(self) -> int | None:
        # 新版：从下拉选择器获取
        if hasattr(self, "provider_selector"):
            selected_name = self.provider_selector_var.get()
            if not selected_name:
                return None
            for index, provider in enumerate(self.config_data.providers):
                if provider.name == selected_name:
                    return index
            return None

        # 旧版：从Treeview获取
        if not hasattr(self, "provider_tree"):
            return None
        selected = self.provider_tree.selection()
        if not selected:
            return None
        return int(selected[0])

    def on_provider_select(self, _event=None) -> None:
        index = self._selected_provider_index()
        if index is None or index >= len(self.config_data.providers):
            return
        provider = self.config_data.providers[index]
        self.provider_name_var.set(provider.name)
        self.provider_endpoint_var.set(provider.endpoint)
        self.provider_key_var.set(provider.api_key)
        self.provider_model_var.set(provider.model)
        self.provider_models_var.set(", ".join(provider.available_models()))
        if hasattr(self, "provider_model_combo"):
            self.provider_model_combo.configure(values=provider.available_models())
        self.provider_reasoning_var.set(self._choice_label(self.REASONING_CHOICES, provider.reasoning_effort or "medium"))
        self.provider_source_var.set(self._choice_label(self.PROVIDER_SOURCE_CHOICES, provider.source))
        self.provider_protocol_var.set(self._choice_label(self.PROVIDER_PROTOCOL_CHOICES, provider.protocol))
        self.provider_api_format_var.set(self._choice_label(self.API_FORMAT_CHOICES, getattr(provider, "api_format", "") or ""))

    def add_provider(self) -> None:
        base = "自定义服务商"
        names = set(self.provider_names())
        name = base
        i = 2
        while name in names:
            name = f"{base}{i}"
            i += 1
        self.config_data.providers.append(Provider(name=name))
        self.refresh_provider_tree()
        self.provider_tree.selection_set(str(len(self.config_data.providers) - 1))
        self.on_provider_select()

    def copy_provider(self) -> None:
        index = self._selected_provider_index()
        if index is None:
            return
        src = self.config_data.providers[index]
        names = set(self.provider_names())
        name = f"{src.name}副本"
        i = 2
        while name in names:
            name = f"{src.name}副本{i}"
            i += 1
        self.config_data.providers.append(Provider(
            name=name,
            endpoint=src.endpoint,
            api_key=src.api_key,
            model=src.model,
            reasoning_effort=src.reasoning_effort,
            models=list(src.models),
            source=src.source,
            custom_headers=dict(src.custom_headers),
            api_key_location=src.api_key_location,
            api_key_field=src.api_key_field,
            api_key_prefix=src.api_key_prefix,
            timeout=src.timeout,
            retry_enabled=src.retry_enabled,
            retry_count=src.retry_count,
            retry_delay=src.retry_delay,
            extra_body_params=dict(src.extra_body_params),
            gateway_type=src.gateway_type,
            protocol=src.protocol,
            api_format=getattr(src, "api_format", "") or "",
        ))
        self.refresh_provider_tree()

    def delete_provider(self) -> None:
        index = self._selected_provider_index()
        if index is None:
            return
        if len(self.config_data.providers) <= 1:
            messagebox.showinfo("不能删除", "至少保留一个服务商")
            return
        removed = self.config_data.providers.pop(index)
        if self.config_data.active_provider == removed.name:
            self.config_data.active_provider = self.config_data.providers[0].name
            self.active_provider.set(self.config_data.active_provider)
        fallback = self.config_data.providers[0].name
        if self.primary_provider.get() == removed.name:
            self.primary_provider.set(fallback)
            self.secondary_provider.set(fallback)
            self.arbitration_provider.set(fallback)
            self.ocr_provider.set(fallback)
        self.refresh_provider_combos()
        self.refresh_provider_tree()
        self.set_status(f"已删除服务商：{removed.name}")

    def save_provider_from_form(self) -> None:
        index = self._selected_provider_index()
        if index is None:
            messagebox.showinfo("未选择服务商", "请先选择一个服务商")
            return
        old_name = self.config_data.providers[index].name
        new_name = self.provider_name_var.get().strip()
        if not new_name:
            messagebox.showerror("名称错误", "服务商名称不能为空")
            return
        for i, provider in enumerate(self.config_data.providers):
            if i != index and provider.name == new_name:
                messagebox.showerror("名称重复", "服务商名称不能重复")
                return
        provider = self.config_data.providers[index]
        provider.name = new_name
        provider.endpoint = self.provider_endpoint_var.get().strip()
        provider.api_key = self.provider_key_var.get().strip()
        provider.model = self.provider_model_var.get().strip()
        provider.source = self._choice_value(self.PROVIDER_SOURCE_CHOICES, self.provider_source_var.get().strip(), "network")
        models = [x.strip() for x in self.provider_models_var.get().replace("\n", ",").split(",") if x.strip()]
        if provider.model and provider.model not in models:
            models.insert(0, provider.model)
        provider.models = models
        provider.reasoning_effort = self._choice_value(self.REASONING_CHOICES, self.provider_reasoning_var.get().strip(), "medium")
        provider.protocol = self._choice_value(self.PROVIDER_PROTOCOL_CHOICES, self.provider_protocol_var.get().strip(), "openai_compatible")
        provider.api_format = self._choice_value(self.API_FORMAT_CHOICES, self.provider_api_format_var.get().strip(), "")
        if self.config_data.active_provider == old_name:
            self.config_data.active_provider = new_name
            self.active_provider.set(new_name)
        if self.primary_provider.get() == old_name:
            self.primary_provider.set(new_name)
            self.secondary_provider.set(new_name)
            self.arbitration_provider.set(new_name)
            self.ocr_provider.set(new_name)
        self.refresh_provider_combos()
        save_config(self.config_data)
        self.refresh_provider_tree()
        self.set_status(f"服务商已保存：{new_name}")

    def set_selected_as_primary(self) -> None:
        index = self._selected_provider_index()
        if index is None:
            return
        provider = self.config_data.providers[index]
        self.config_data.active_provider = provider.name
        self.active_provider.set(provider.name)
        self.primary_provider.set(provider.name)
        self.secondary_provider.set(provider.name)
        self.arbitration_provider.set(provider.name)
        self.ocr_provider.set(provider.name)
        self.refresh_provider_combos()
        self.refresh_provider_tree()
        self.set_status(f"服务商：{provider.name}")

    def test_selected_provider(self) -> None:
        index = self._selected_provider_index()
        if index is None:
            messagebox.showinfo("未选择服务商", "请先选择一个服务商")
            return
        self.save_provider_from_form()
        provider = self.config_data.providers[index]
        self._provider_action_busy = True
        for button in self._provider_fetch_buttons + self._provider_test_buttons:
            button.setEnabled(False)
        self.provider_action_status.configure(text=f"正在测试服务商：{provider.name}")
        self.set_status(f"正在测试服务商：{provider.name}")

        def worker() -> None:
            try:
                text = test_provider(provider, self.provider_test_prompt_var.get().strip() or "请只回复：连接成功")
                self.work_queue.put(("status", f"{provider.name} 连接成功：{text[:40]}"))
            except Exception as exc:
                self.work_queue.put(("error", f"{provider.name} 测试失败：{exc}"))

        threading.Thread(target=worker, daemon=True).start()

    def refresh_preset_selector(self) -> None:
        """刷新方案下拉选择器"""
        if not hasattr(self, "preset_selector"):
            return

        # 获取所有方案名称
        presets = load_presets()
        preset_names = list(presets.keys())
        self.preset_selector.configure(values=preset_names)

        # 设置当前选中的方案
        if preset_names:
            current = self.config_data.active_preset
            if current in preset_names:
                self.preset_selector_var.set(current)
            else:
                self.preset_selector_var.set(preset_names[0])
                self._load_preset_info_by_name(preset_names[0])

        # 更新方案信息
        self._update_preset_info()

    def _load_preset_info_by_name(self, name: str) -> None:
        """根据名称加载方案信息到界面"""
        if not name:
            return

        self.preset_name_var.set(name)
        self._update_preset_info()

    def on_preset_selector_changed(self, _event=None) -> None:
        """下拉选择器改变时"""
        selected_name = self.preset_selector_var.get()
        if selected_name:
            self._load_preset_info_by_name(selected_name)

    def refresh_presets(self) -> None:
        # 新版：使用下拉选择器
        if hasattr(self, "preset_selector"):
            self.refresh_preset_selector()
            return

        # 旧版：兼容Listbox
        if not hasattr(self, "preset_list"):
            return
        self.preset_list.delete(0, "end")
        presets = load_presets()
        for name in presets:
            self.preset_list.insert("end", name)
        self._update_preset_info()

    def _on_preset_select(self, _event=None) -> None:
        self._update_preset_info()

    def _selected_preset_name(self) -> str | None:
        # 新版：从下拉选择器获取
        if hasattr(self, "preset_selector"):
            return self.preset_selector_var.get() or None

        # 旧版：从Listbox获取
        if not hasattr(self, "preset_list"):
            return None
        selected = self.preset_list.curselection()
        if not selected:
            return None
        return self.preset_list.get(selected[0])

    def _update_preset_info(self) -> None:
        if not hasattr(self, "preset_info"):
            return
        name = self._selected_preset_name() or self.config_data.active_preset
        presets = load_presets()
        data = presets.get(name, {})
        self.preset_info.delete("1.0", "end")
        if data:
            scoring = data.get("scoring", {})
            workflow = data.get("workflow", {})
            primary_name = workflow.get("primary_provider_name") or data.get("active_provider", "")
            self.preset_info.insert("1.0", f"当前方案：{name}\n主评服务商：{primary_name}\n副评：{'开启' if workflow.get('dual_enabled') else '关闭'}\n仲裁：{'开启' if workflow.get('arbitration_enabled', True) else '关闭'}\n满分：{scoring.get('max_score', '')}\n小题数：{len(scoring.get('units', []) or [])}\n模式：{workflow.get('mode', '')}\n空白检测：{'开启' if data.get('blank_detection_enabled') else '关闭'}")

    def load_selected_preset(self) -> None:
        name = self._selected_preset_name()
        if not name:
            messagebox.showinfo("未选择方案", "请先选择一个配置方案")
            return
        data = load_presets().get(name)
        if not data:
            return
        self.config_data = config_from_dict(data)
        self.config_data.active_preset = name
        self.preset_name_var.set(name)
        self.apply_config_to_ui()
        save_config(self.config_data)
        self.set_status(f"已载入方案：{name}")

    def save_current_preset(self) -> None:
        self.save_all()
        name = self.preset_name_var.get().strip() or self.config_data.active_preset
        self.config_data.active_preset = name
        presets = load_presets()
        presets[name] = self.config_data.to_dict()
        save_presets(presets)
        save_config(self.config_data)
        self.refresh_presets()
        self.set_status(f"方案已保存：{name}")

    def save_as_preset(self) -> None:
        self.save_all()
        name = self.preset_name_var.get().strip()
        if not name:
            messagebox.showerror("缺少名称", "请输入方案名称")
            return
        self.config_data.active_preset = name
        presets = load_presets()
        presets[name] = self.config_data.to_dict()
        save_presets(presets)
        self.refresh_presets()
        self.set_status(f"已另存方案：{name}")

    def delete_selected_preset(self) -> None:
        name = self._selected_preset_name()
        if not name:
            return
        presets = load_presets()
        if len(presets) <= 1:
            messagebox.showinfo("不能删除", "至少保留一个方案")
            return
        presets.pop(name, None)
        save_presets(presets)
        self.refresh_presets()
        self.set_status(f"已删除方案：{name}")

    def ensure_ten_presets(self) -> None:
        self.save_all()
        presets = load_presets()
        base = self.config_data.to_dict()
        for index in range(1, 11):
            name = f"评分标准{index}"
            presets.setdefault(name, {**base, "active_preset": name})
        save_presets(presets)
        self.refresh_presets()
        self.set_status("已补足10套评分标准方案")

    def refresh_history(self) -> None:
        """刷新历史记录 - 连续批改时跳过以提升性能"""
        from storage import load_history
        if not hasattr(self, "history_text"):
            return
        if self.continuous:
            return  # 连续批改时不刷新，避免卡顿
        self.history_text.delete("1.0", "end")
        for r in load_history()[:100]:
            tm = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(r.get("timestamp", 0)))
            self.history_text.insert("end", f"{tm} | {r.get('final_score')}分 | {r.get('student_answer', '')[:80]}\n")

    def export_history_selected_format(self) -> None:
        """根据选中的格式导出历史记录"""
        format_map = {
            "JSON": export_json,
            "CSV": export_csv,
            "HTML": export_html,
            "Word": export_docx,
            "Excel": export_xlsx,
            "PDF": export_pdf,
        }
        selected_format = self.export_format_var.get()
        export_func = format_map.get(selected_format)
        if export_func:
            self._export(export_func)
        else:
            self.set_status(f"未知导出格式：{selected_format}")

    def _export(self, func) -> None:
        path = func()
        self.set_status(f"已导出：{path}")

    def clear_history_records(self) -> None:
        if messagebox.askyesno("清空历史", "确定要清空所有评阅历史吗？"):
            clear_history()
            self.refresh_history()
            self.set_status("历史记录已清空")

    def export_settings(self) -> None:
        self.save_all()
        path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON 文件", "*.json")], initialfile="AI阅卷配置备份.json")
        if not path:
            return
        payload = {"config": self.config_data.to_dict(), "presets": load_presets()}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self.set_status(f"配置已导出：{path}")

    def import_settings(self) -> None:
        path = filedialog.askopenfilename(filetypes=[("JSON 文件", "*.json")])
        if not path:
            return
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        if "presets" in payload:
            save_presets(payload["presets"])
        if "config" in payload:
            self.config_data = config_from_dict(payload["config"])
            save_config(self.config_data)
            self.apply_config_to_ui()
        elif CONFIG_FILE.exists():
            self.config_data = load_config()
            self.apply_config_to_ui()
        if PRESETS_FILE.exists():
            self.refresh_presets()
        self.set_status("配置已导入")

    def toggle_comment(self) -> None:
        """折叠/展开评分说明"""
        if self.comment_expanded:
            self.comment_view.pack_forget()
            theme.set_icon_button(self.comment_toggle_btn, "chevron_down", "展开查看详细说明")
            self.comment_expanded = False
        else:
            self.comment_view.pack(fill="both", pady=(theme.SPACING["sm"], 0))
            theme.set_icon_button(self.comment_toggle_btn, "chevron_up", "收起说明")
            self.comment_expanded = True
        # scrollregion会自动更新，无需手动调用

    def toggle_output(self) -> None:
        """折叠/展开AI详细输出"""
        if self.output_expanded:
            self.output.pack_forget()
            theme.set_icon_button(self.output_toggle_btn, "chevron_down", "展开查看技术日志")
            self.output_expanded = False
        else:
            self.output.pack(fill="both", pady=(theme.SPACING["sm"], 0))
            theme.set_icon_button(self.output_toggle_btn, "chevron_up", "收起日志")
            self.output_expanded = True
        # scrollregion会自动更新，无需手动调用


def run_app() -> None:
    tk.ensure_app()
    app = AIMarkerApp()
    app.mainloop()



