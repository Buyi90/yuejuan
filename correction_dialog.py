from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Callable

import theme
from models import AppConfig


# 校正对话框用于帮助老师复核 AI 打分，并可同步刷新参考答案和评分标准。


class CorrectionDialog(tk.Toplevel):
    def __init__(
        self,
        master: tk.Misc,
        config: AppConfig,
        result: dict[str, Any],
        on_accept: Callable[[float, dict[str, Any]], None],
    ):
        super().__init__(master)
        self.config = config
        self.result = result
        self.on_accept = on_accept
        self.title("得分校正")
        self.geometry("760x560")
        self.transient(master)
        self.grab_set()
        theme.apply_window_icon(self)
        self._build()

    def _build(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        # 顶部展示 AI 的当前得分，方便与人工判断对照。
        ttk.Label(root, text="AI 打分", font=(theme.FONT_FAMILY, 12, "bold")).grid(row=0, column=0, sticky="w")
        ttk.Label(root, text=str(self.result.get("final_score", "")), font=(theme.FONT_FAMILY, 24, "bold")).grid(
            row=1,
            column=0,
            sticky="w",
            pady=(0, 8),
        )

        ttk.Label(root, text="识别答案").grid(row=2, column=0, sticky="w")
        answer = tk.Text(root, height=5, wrap="word")
        answer.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(4, 10))
        answer.insert("1.0", self.result.get("student_answer", ""))
        answer.configure(state="disabled")

        ttk.Label(root, text="人工得分").grid(row=4, column=0, sticky="w")
        self.score_var = tk.StringVar(value=str(self.result.get("final_score", "")))
        ttk.Entry(root, textvariable=self.score_var, width=16).grid(row=5, column=0, sticky="w", pady=(4, 10))

        ttk.Label(root, text="评分说明").grid(row=6, column=0, sticky="w")
        self.reason = tk.Text(root, height=4, wrap="word")
        self.reason.grid(row=7, column=0, columnspan=2, sticky="nsew", pady=(4, 10))

        ttk.Label(root, text="更新参考答案（可选）").grid(row=8, column=0, sticky="w")
        self.answer_update = tk.Text(root, height=5, wrap="word")
        self.answer_update.grid(row=9, column=0, sticky="nsew", pady=(4, 10))
        self.answer_update.insert("1.0", self.config.answer)

        ttk.Label(root, text="更新评分标准（可选）").grid(row=8, column=1, sticky="w")
        self.rubric_update = tk.Text(root, height=5, wrap="word")
        self.rubric_update.grid(row=9, column=1, sticky="nsew", padx=(10, 0), pady=(4, 10))
        self.rubric_update.insert("1.0", self.config.rubric)

        btns = ttk.Frame(root)
        btns.grid(row=10, column=0, columnspan=2, sticky="e")
        theme.icon_button(btns, "stop", "取消", command=self.destroy).pack(side="left", padx=6)
        theme.icon_button(btns, "check", "应用校正", color="#FFFFFF", command=self._accept).pack(side="left")

        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(3, weight=1)
        root.rowconfigure(9, weight=1)

    def _accept(self) -> None:
        try:
            score = float(self.score_var.get())
        except ValueError:
            messagebox.showerror("得分错误", "请输入数字得分")
            return

        info = {
            "reason": self.reason.get("1.0", "end").strip(),
            "new_answer": self.answer_update.get("1.0", "end").strip(),
            "new_rubric": self.rubric_update.get("1.0", "end").strip(),
        }

        self.on_accept(score, info)
        self.destroy()
