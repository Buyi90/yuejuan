from __future__ import annotations

from typing import Any, Callable

from PIL import Image

import qtcompat as tk
from qtcompat import ttk

import theme


class SubmitDialog(tk.Toplevel):
    def __init__(
        self,
        master,
        result: dict[str, Any],
        image: Image.Image | None,
        mode: str,
        countdown: int,
        on_submit: Callable[[], None],
        on_cancel: Callable[[], None],
        on_correct: Callable[[], None],
        on_mark_blank: Callable[[], None],
        on_not_blank: Callable[[], None],
    ):
        super().__init__(master)
        self.result = result
        self.mode = mode
        self.remaining = max(0, int(countdown or 0))
        self.on_submit = on_submit
        self.on_cancel = on_cancel
        self.on_correct = on_correct
        self.on_mark_blank = on_mark_blank
        self.on_not_blank = on_not_blank
        self.paused = mode == "trial"
        self._timer_id = None
        self.preview_ref = None
        self.title("批改完成")
        self.geometry("900x620")
        self.minsize(760, 520)
        self.transient(master)
        theme.apply_window_icon(self)
        self._build(image)
        self.protocol("WM_DELETE_WINDOW", self.cancel)
        if not self.paused and self.remaining > 0:
            self._tick()

    def _build(self, image: Image.Image | None) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)
        header = ttk.Frame(root)
        header.pack(fill="x", pady=(0, 10))
        title = "试改确认" if self.mode == "trial" else "批改完成"
        if self.result.get("is_blank_card"):
            title += " / 空白卡"
        ttk.Label(header, text=title, font=(theme.FONT_FAMILY, 14, "bold")).pack(side="left")
        self.countdown_var = tk.StringVar(value=self._countdown_text())
        ttk.Label(header, textvariable=self.countdown_var).pack(side="right")

        body = ttk.PanedWindow(root, orient="horizontal")
        body.pack(fill="both", expand=True)
        img_panel = ttk.Frame(body, padding=(0, 0, 10, 0))
        result_panel = ttk.Frame(body)
        body.add(img_panel, weight=3)
        body.add(result_panel, weight=2)

        ttk.Label(img_panel, text="识别框截图").pack(anchor="w")
        self.canvas = tk.Canvas(img_panel, bg="#f3f6fa", highlightthickness=1, highlightbackground="#d8dee8")
        self.canvas.pack(fill="both", expand=True, pady=(4, 0))
        if image is not None:
            self.after(80, lambda: self._draw_image(image))

        score = self.result.get("final_score", "")
        max_score = self.result.get("max_score", "")
        ttk.Label(result_panel, text="最终得分").pack(anchor="w")
        ttk.Label(result_panel, text=("%s / %s" % (score, max_score)) if max_score != "" else str(score), font=(theme.FONT_FAMILY, 30, "bold")).pack(anchor="w", pady=(0, 8))

        if self.result.get("sub_scores"):
            ttk.Label(result_panel, text="各小题得分").pack(anchor="w")
            sub = tk.Text(result_panel, height=5, wrap="word")
            sub.pack(fill="x", pady=(4, 8))
            for item in self.result["sub_scores"]:
                sub.insert("end", "%s: %s/%s %s\n" % (item.get("label", ""), item.get("score", ""), item.get("maxScore", ""), item.get("comment", "")))
            sub.configure(state="disabled")

        ttk.Label(result_panel, text="识别答案").pack(anchor="w")
        answer = tk.Text(result_panel, height=7, wrap="word")
        answer.pack(fill="both", expand=True, pady=(4, 8))
        answer.insert("1.0", self.result.get("student_answer", ""))
        answer.configure(state="disabled")

        ttk.Label(result_panel, text="评分依据").pack(anchor="w")
        comment = tk.Text(result_panel, height=7, wrap="word")
        comment.pack(fill="both", expand=True, pady=(4, 0))
        comment.insert("1.0", self.result.get("comment", ""))
        comment.configure(state="disabled")

        btns = ttk.Frame(root)
        btns.pack(fill="x", pady=(12, 0))
        if self.result.get("is_blank_card"):
            theme.icon_button(btns, "refresh", "这不是空白卡，重新批改", command=self.not_blank).pack(side="left", padx=4)
        else:
            theme.icon_button(btns, "warning", "标记为空白卡", command=self.mark_blank).pack(side="left", padx=4)
        theme.icon_button(btns, "edit", "分数有误", command=self.correct).pack(side="left", padx=4)
        self.pause_btn = theme.icon_button(
            btns,
            "play" if self.paused else "pause",
            "暂停倒计时" if not self.paused else "继续倒计时",
            command=self.toggle_pause,
        )
        if self.mode != "trial":
            self.pause_btn.pack(side="left", padx=4)
        theme.icon_button(btns, "stop", "取消", command=self.cancel).pack(side="right", padx=4)
        theme.icon_button(btns, "check", "提交并下一份", color="#FFFFFF", command=self.submit).pack(side="right", padx=4)

    def _draw_image(self, image: Image.Image) -> None:
        from PySide6.QtGui import QImage, QPixmap

        w = max(self.canvas.winfo_width() - 20, 50)
        h = max(self.canvas.winfo_height() - 20, 50)
        preview = image.copy()
        preview.thumbnail((w, h))
        data = preview.convert("RGBA").tobytes("raw", "RGBA")
        qimage = QImage(data, preview.width, preview.height, QImage.Format_RGBA8888)
        self.preview_ref = QPixmap.fromImage(qimage.copy())
        self.canvas.delete("all")
        self.canvas.create_image(10, 10, image=self.preview_ref, anchor="nw")

    def _countdown_text(self) -> str:
        if self.mode == "trial":
            return "等待教师确认"
        if self.paused:
            return "已暂停"
        return "%s 秒后自动提交" % self.remaining if self.remaining > 0 else "准备提交"

    def _tick(self) -> None:
        self.countdown_var.set(self._countdown_text())
        if self.paused:
            return
        if self.remaining <= 0:
            self.submit()
            return
        self.remaining -= 1
        self._timer_id = self.after(1000, self._tick)

    def _close_timer(self) -> None:
        if self._timer_id:
            self.after_cancel(self._timer_id)
            self._timer_id = None

    def toggle_pause(self) -> None:
        self.paused = not self.paused
        try:
            theme.set_icon_button(
                self.pause_btn,
                "play" if self.paused else "pause",
                "继续倒计时" if self.paused else "暂停倒计时",
            )
        except Exception:
            self.pause_btn.configure(text="继续倒计时" if self.paused else "暂停倒计时")
        self.countdown_var.set(self._countdown_text())
        if not self.paused and not self._timer_id:
            self._tick()

    def submit(self) -> None:
        self._close_timer()
        self.destroy()
        self.on_submit()

    def cancel(self) -> None:
        self._close_timer()
        self.destroy()
        self.on_cancel()

    def correct(self) -> None:
        self._close_timer()
        self.destroy()
        self.on_correct()

    def mark_blank(self) -> None:
        self._close_timer()
        self.destroy()
        self.on_mark_blank()

    def not_blank(self) -> None:
        self._close_timer()
        self.destroy()
        self.on_not_blank()
