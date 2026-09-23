"""
关于对话框

显示软件信息、版本号和风险提示
"""

import qtcompat as tk
from qtcompat import ttk

import theme


def show_about_dialog(parent):
    """显示关于对话框"""
    dialog = tk.Toplevel(parent)
    dialog.title("关于 AI智阅小助手")
    dialog.geometry("500x450")
    dialog.resizable(False, False)
    dialog.transient(parent)
    dialog.grab_set()
    theme.apply_window_icon(dialog)

    dialog.update_idletasks()
    x = (dialog.winfo_screenwidth() // 2) - (500 // 2)
    y = (dialog.winfo_screenheight() // 2) - (450 // 2)
    dialog.geometry("+%s+%s" % (x, y))

    container = ttk.Frame(dialog, padding=20)
    container.pack(fill="both", expand=True)

    logo = ttk.Label(container, image=theme.logo_photo(dialog, 48))
    logo.pack(pady=(0, 8))

    name_label = ttk.Label(
        container,
        text="AI智阅小助手",
        font=theme.FONT_TITLE,
    )
    name_label.pack(pady=(0, 5))

    version_label = ttk.Label(
        container,
        text="版本 v2.1",
        font=theme.FONT_SMALL,
    )
    version_label.pack(pady=(0, 15))

    intro_label = ttk.Label(
        container,
        text="AI辅助阅卷工具，适合教师进行批量初评、自动填分和阅卷流程提效。购买后即可使用完整功能，无需激活码。",
        font=theme.FONT_SMALL,
        wraplength=450,
        justify="center"
    )
    intro_label.pack(pady=(0, 20))

    separator = ttk.Separator(container, orient="horizontal")
    separator.pack(fill="x", pady=10)

    warning_title = ttk.Label(
        container,
        text="重要提示",
        font=(theme.FONT_FAMILY, 11, "bold"),
        foreground="#d32f2f"
    )
    warning_title.pack(pady=(5, 10))

    warning_text = """当前版本仍处于早期优化阶段。

• 对学生手写答案的 OCR 识别仍不精准
• 模糊扫描、连笔、涂改会影响识别和评分
• 本软件适合作为 AI 辅助阅卷工具
• 不承诺完全替代人工阅卷

正式使用前请先进行小批量试批。
重要考试和最终成绩请务必人工复核。"""

    warning_label = ttk.Label(
        container,
        text=warning_text,
        font=theme.FONT_SMALL,
        wraplength=450,
        justify="left",
        foreground="#666666"
    )
    warning_label.pack(pady=(0, 15))

    separator2 = ttk.Separator(container, orient="horizontal")
    separator2.pack(fill="x", pady=10)

    contact_label = ttk.Label(
        container,
        text="如有问题或建议，请联系管理员",
        font=theme.FONT_SMALL,
    )
    contact_label.pack(pady=(5, 15))

    close_btn = theme.icon_button(
        container,
        "check",
        "我知道了",
        command=dialog.destroy,
    )
    close_btn.pack()

    dialog.bind("<Escape>", lambda e: dialog.destroy())
    dialog.wait_window()
