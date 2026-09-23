#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Teacher-tool chrome must look like the original C# shell, not native Win32."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import QApplication, QComboBox, QGridLayout, QLabel, QLineEdit, QProgressBar, QPushButton, QTabBar, QTabWidget, QWidget


ROOT = Path(__file__).resolve().parent


def _close(app) -> None:
    app.update()
    app.after(200, app.destroy)
    app.update()
    if app.winfo_exists():
        app.destroy()


def _mapped_rect(widget, root):
    top_left = widget.mapTo(root, widget.rect().topLeft())
    bottom_right = widget.mapTo(root, widget.rect().bottomRight())
    return top_left, bottom_right


def test_theme_exposes_app_stylesheet() -> None:
    import theme

    sheet = theme.APP_STYLESHEET
    assert "QPushButton" in sheet
    assert "QTabBar::tab" in sheet
    assert "QLineEdit" in sheet
    assert "border-radius" in sheet
    assert theme.COLORS["primary"] in sheet
    assert theme.COLORS["light"] in sheet


def test_pack_fill_x_does_not_eat_vertical_space() -> None:
    import qtcompat as tk

    win = tk.Window()
    try:
        outer = tk.Frame(win)
        outer.pack(fill="both", expand=True)
        header = tk.Frame(outer)
        header.pack(fill="x")
        tk.Label(header, text="H").pack(side="left")
        body = tk.Frame(outer)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="B").pack()
        footer = tk.Frame(outer)
        footer.pack(fill="x")
        tk.Label(footer, text="F").pack(side="left")
        win.resize(420, 780)
        win.show()
        win.update()
        assert header.height() < 80
        assert footer.height() < 80
        assert body.height() > 400
    finally:
        _close(win)


def test_pack_pady_keeps_gap_without_crashing() -> None:
    import qtcompat as tk

    win = tk.Window()
    try:
        outer = tk.Frame(win)
        outer.pack(fill="both", expand=True)
        header = tk.Frame(outer)
        header.pack(fill="x", pady=(0, 6))
        tk.Label(header, text="H").pack(side="left")
        body = tk.Frame(outer)
        body.pack(fill="both", expand=True)
        tk.Label(body, text="B").pack()
        win.resize(420, 780)
        win.show()
        win.update()
        header_bottom = header.mapTo(outer, header.rect().bottomLeft()).y()
        body_top = body.mapTo(outer, body.rect().topLeft()).y()
        assert body_top - header_bottom >= 5, (header_bottom, body_top)
        assert header.height() < 80
    finally:
        _close(win)


def test_pack_fill_x_expand_stays_horizontal() -> None:
    import qtcompat as tk
    from PySide6.QtWidgets import QSizePolicy

    win = tk.Window()
    try:
        row = tk.Frame(win)
        row.pack(fill="x")
        chip = tk.Frame(row)
        chip.pack(side="left", fill="x", expand=True, padx=(0, 6))
        btn = tk.Button(row, text="Go")
        btn.pack(side="right")
        win.resize(420, 200)
        win.show()
        win.update()
        assert chip.sizePolicy().horizontalPolicy() == QSizePolicy.Expanding
        assert chip.sizePolicy().verticalPolicy() != QSizePolicy.Expanding
        assert chip.height() < 80
    finally:
        _close(win)


def test_pack_then_grid_does_not_hang() -> None:
    import qtcompat as tk

    win = tk.Window()
    try:
        tools = tk.Frame(win)
        tools.pack(fill="x")
        ghost = tk.Button(tools, text="ghost")
        ghost.pack(side="left", fill="x", expand=True)
        grid = QGridLayout(tools)
        grid.setContentsMargins(0, 0, 0, 0)
        btn = tk.Button(tools, text="Show")
        grid.addWidget(btn, 0, 0)
        win.resize(420, 200)
        win.show()
        win.update()
        assert tools.height() < 120, tools.height()
        assert btn.height() < 80, btn.height()
        assert ghost.height() < 80, ghost.height()
    finally:
        _close(win)


def test_qt_theme_stylesheet_is_applied() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.update()
        sheet = QApplication.instance().styleSheet()
        assert "QPushButton" in sheet
        assert "QTabBar::tab" in sheet
        assert "QLineEdit" in sheet
        assert "border-radius" in sheet
    finally:
        _close(app)


def test_header_is_compact() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        title = next(label for label in app.findChildren(QLabel) if label.text() == "AI智阅小助手")
        bottom = title.mapTo(app, title.rect().bottomLeft()).y()
        assert title.height() <= 28
        assert bottom <= 56
    finally:
        _close(app)


def test_primary_actions_sit_in_visible_bottom_bar() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        wanted = ("开始批改", "暂停", "停止", "调试")
        found = {}
        for button in app.findChildren(QPushButton):
            for label in wanted:
                if label in button.text():
                    found[label] = button
        missing = [label for label in wanted if label not in found]
        assert not missing, missing
        for label, button in found.items():
            assert button.isVisible(), label
            top = button.mapTo(app, button.rect().topLeft()).y()
            assert top > app.height() * 0.62, f"{label} y={top}"
            _assert_widget_fits(button, app)
    finally:
        _close(app)


def test_footer_chrome_fits_inside_window() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        clipped = []
        for button in app.findChildren(QPushButton):
            if not button.isVisible() or not button.text().strip():
                continue
            if not _widget_fits(button, app):
                clipped.append(button.text())
        assert not clipped, clipped
        progress = next(label for label in app.findChildren(QLabel) if "/" in label.text())
        assert _widget_fits(progress, app)
        bars = [bar for bar in app.findChildren(QProgressBar) if bar.isVisible()]
        assert bars, "missing visible progress bar"
        bar = bars[0]
        assert bar.height() <= 16
        assert bar.width() >= 40
        assert progress.width() >= 39
    finally:
        _close(app)


def test_inputs_and_tabs_use_rounded_qss() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.update()
        sheet = QApplication.instance().styleSheet()
        assert "QTabBar::tab:selected" in sheet
        assert "QComboBox" in sheet
        entries = [widget for widget in app.findChildren(QLineEdit) if widget.isVisible()]
        assert entries
        tabs = app.findChildren(QTabBar)
        assert tabs
        assert tabs[0].drawBase() is False
    finally:
        _close(app)




def test_notebook_stays_above_command_dock() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        dock = app.findChild(QWidget, "commandDock")
        notebook = app.findChildren(QTabWidget)[0]
        assert dock is not None
        dock_top = dock.mapTo(app, dock.rect().topLeft()).y()
        dock_bottom = dock.mapTo(app, dock.rect().bottomRight()).y()
        notebook_bottom = notebook.mapTo(app, notebook.rect().bottomRight()).y()
        assert notebook_bottom <= dock_top + 2, (notebook_bottom, dock_top)
        assert dock_bottom <= app.height() + 1, (dock_bottom, app.height())
        assert dock.height() <= 120
        assert dock_top >= app.height() - 150
    finally:
        _close(app)


def test_visible_tab_labels_match_teacher_chrome() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        bar = app.findChildren(QTabBar)[0]
        texts = [bar.tabText(i) for i in range(bar.count())]
        expected = [
            "".join(chr(c) for c in [0x41, 0x49, 0x914d, 0x7f6e]),
            "".join(chr(c) for c in [0x6539, 0x5377, 0x53c2, 0x6570]),
            "".join(chr(c) for c in [0x8bc4, 0x5206, 0x6807, 0x51c6]),
            "".join(chr(c) for c in [0x8bc4, 0x5206, 0x8fc7, 0x7a0b]),
        ]
        assert texts == expected, texts
        for i in range(bar.count()):
            rect = bar.tabRect(i)
            assert rect.width() >= 48
            assert rect.right() <= bar.width() + 1
    finally:
        _close(app)


def test_provider_toolbar_buttons_fit() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        wanted = (
            "".join(chr(c) for c in [0x65b0, 0x589e]),
            "".join(chr(c) for c in [0x590d, 0x5236]),
            "".join(chr(c) for c in [0x5220, 0x9664]),
            "".join(chr(c) for c in [0x4fdd, 0x5b58]),
            "".join(chr(c) for c in [0x6d4b, 0x8bd5]),
            "".join(chr(c) for c in [0x83b7, 0x53d6, 0x6a21, 0x578b]),
        )
        found = {}
        for button in app.findChildren(QPushButton):
            if not button.isVisible():
                continue
            for label in wanted:
                if label and label in button.text() and label not in found:
                    found[label] = button
        missing = [label for label in wanted if label not in found]
        assert not missing, missing
        notebook = app.findChildren(QTabWidget)[0]
        nb_left = notebook.mapTo(app, notebook.rect().topLeft())
        nb_right = notebook.mapTo(app, notebook.rect().bottomRight())
        for label, button in found.items():
            assert button.isVisible(), label
            assert _widget_fits(button, app), label
            top_left, bottom_right = _mapped_rect(button, app)
            assert top_left.x() >= nb_left.x() - 2, label
            assert bottom_right.x() <= nb_right.x() + 2, (label, bottom_right.x(), nb_right.x())
    finally:
        _close(app)



def test_config_tab_uses_teacher_cards() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        notebook = app.findChildren(QTabWidget)[0]
        notebook.setCurrentIndex(1)
        app.update()
        titles = [
            ''.join(chr(c) for c in [0x6570, 0x503C, 0x8BBE, 0x7F6E]),
            ''.join(chr(c) for c in [0x9898, 0x76EE, 0x8BBE, 0x7F6E]),
            ''.join(chr(c) for c in [0x6807, 0x8BB0, 0x8BBE, 0x7F6E]),
        ]
        labels = [widget.text() for widget in app.findChildren(QLabel)]
        missing = [title for title in titles if not any(title in text for text in labels)]
        assert not missing, missing
        count_txt = ''.join(chr(c) for c in [0x6539, 0x5377, 0x6570, 0x91CF])
        delay_txt = ''.join(chr(c) for c in [0x53D6, 0x5361, 0x5EF6, 0x65F6])
        count_label = next(widget for widget in app.findChildren(QLabel) if widget.text() == count_txt)
        delay_label = next(widget for widget in app.findChildren(QLabel) if widget.text() == delay_txt)
        count_pos = count_label.mapTo(app, count_label.rect().topLeft())
        delay_pos = delay_label.mapTo(app, delay_label.rect().topLeft())
        assert abs(count_pos.y() - delay_pos.y()) <= 8, (count_pos.y(), delay_pos.y())
        assert delay_pos.x() - count_pos.x() >= 120, (count_pos.x(), delay_pos.x())
    finally:
        _close(app)



def test_config_tab_cards_fit_inside_window() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        notebook = app.findChildren(QTabWidget)[0]
        notebook.setCurrentIndex(1)
        app.update()
        nb_left = notebook.mapTo(app, notebook.rect().topLeft())
        nb_right = notebook.mapTo(app, notebook.rect().bottomRight())
        clipped = []
        for widget in app.findChildren(QWidget):
            name = widget.objectName()
            if name != 'cardPanel' or not widget.isVisible():
                continue
            _tl, br = _mapped_rect(widget, app)
            if br.x() > nb_right.x() + 2 or widget.width() > notebook.width() + 8:
                clipped.append(('card', widget.width(), br.x(), nb_right.x()))
        for widget in list(app.findChildren(QPushButton)) + list(app.findChildren(QLabel)) + list(app.findChildren(QLineEdit)):
            if not widget.isVisible():
                continue
            if widget.width() <= 1 or widget.height() <= 1:
                continue
            top_left, bottom_right = _mapped_rect(widget, app)
            if top_left.y() < 70 or top_left.y() > 670:
                continue
            if bottom_right.x() > nb_right.x() + 2 or top_left.x() < nb_left.x() - 2:
                text = widget.text().strip() if hasattr(widget, 'text') else ''
                clipped.append((text or widget.objectName() or widget.__class__.__name__, bottom_right.x(), nb_right.x()))
        assert not clipped, clipped[:12]
        count_txt = ''.join(chr(c) for c in [0x6539, 0x5377, 0x6570, 0x91CF])
        delay_txt = ''.join(chr(c) for c in [0x53D6, 0x5361, 0x5EF6, 0x65F6])
        count_label = next(widget for widget in app.findChildren(QLabel) if widget.text() == count_txt and widget.isVisible())
        delay_label = next(widget for widget in app.findChildren(QLabel) if widget.text() == delay_txt and widget.isVisible())
        assert count_label.width() <= 90, count_label.width()
        assert delay_label.width() <= 90, delay_label.width()
    finally:
        _close(app)


def test_config_action_buttons_are_filled() -> None:
    from app import AIMarkerApp
    from PySide6.QtGui import QColor

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        notebook = app.findChildren(QTabWidget)[0]
        notebook.setCurrentIndex(1)
        app.update()
        add_all_txt = "".join(chr(c) for c in [0x4E00, 0x952E, 0x6DFB, 0x52A0])
        add_mark_txt = "".join(chr(c) for c in [0x6DFB, 0x52A0, 0x6807, 0x8BB0])
        buttons = [b for b in app.findChildren(QPushButton) if b.isVisible() and b.text().strip()]
        add_all = next(b for b in buttons if add_all_txt in b.text())
        marks = [b for b in buttons if add_mark_txt in b.text()]
        assert marks, add_mark_txt
        for button in [add_all, *marks]:
            pix = button.grab()
            image = pix.toImage()
            color = image.pixelColor(max(8, image.width() // 2), max(6, image.height() // 2))
            assert color.lightness() < 220, (button.text(), color.name(), color.lightness())
            assert color.saturation() > 20, (button.text(), color.name(), color.saturation())
    finally:
        _close(app)


def test_score_tab_hides_duplicate_meta_row() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        notebook = app.findChildren(QTabWidget)[0]
        notebook.setCurrentIndex(2)
        app.update()
        grade = ''.join(chr(c) for c in [0x5E74, 0x7EA7])
        subject = ''.join(chr(c) for c in [0x5B66, 0x79D1])
        qtype = ''.join(chr(c) for c in [0x9898, 0x578B])
        visible = [widget.text() for widget in app.findChildren(QLabel) if widget.isVisible() and widget.text() in {grade, subject, qtype}]
        assert grade not in visible
        assert subject not in visible
        assert qtype not in visible
        add_txt = ''.join(chr(c) for c in [0x6DFB, 0x52A0])
        remove_txt = ''.join(chr(c) for c in [0x79FB, 0x9664])
        view_txt = ''.join(chr(c) for c in [0x67E5, 0x770B])
        found = {}
        for button in app.findChildren(QPushButton):
            if not button.isVisible():
                continue
            for label in (add_txt, remove_txt, view_txt):
                if label in button.text():
                    found[label] = button
        missing = [label for label in (add_txt, remove_txt, view_txt) if label not in found]
        assert not missing, missing
        for label, button in found.items():
            assert _widget_fits(button, app), (label, button.width(), button.text())
    finally:
        _close(app)


def test_status_chip_stays_compact() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        chip = app.findChild(QWidget, "statusChip")
        assert chip is not None
        assert chip.isVisible()
        assert chip.width() <= 90, chip.width()
        title = next(label for label in app.findChildren(QLabel) if label.objectName() == "appTitle")
        title_right = title.mapTo(app, title.rect().bottomRight()).x()
        chip_left = chip.mapTo(app, chip.rect().topLeft()).x()
        assert chip_left - title_right >= 24, (title_right, chip_left, chip.width())
        assert chip_left >= app.width() - 100, (chip_left, app.width(), chip.width())
    finally:
        _close(app)


def test_provider_action_buttons_are_filled() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        add_txt = "".join(chr(c) for c in [0x65B0, 0x589E])
        del_txt = "".join(chr(c) for c in [0x5220, 0x9664])
        buttons = [b for b in app.findChildren(QPushButton) if b.isVisible()]
        add_btn = next(b for b in buttons if add_txt in b.text())
        del_btn = next(b for b in buttons if del_txt in b.text())
        for button in (add_btn, del_btn):
            pix = button.grab()
            image = pix.toImage()
            x = max(12, image.width() // 2)
            y = min(3, max(0, image.height() - 1))
            color = image.pixelColor(x, y)
            assert color.lightness() < 220, (button.text(), button.objectName(), color.name(), color.lightness())
            assert color.saturation() > 20, (button.text(), button.objectName(), color.name(), color.saturation())
            assert button.objectName() in {"btnSuccess", "btnDanger", "btnPrimary", "btnInfo", "btnWarning"}, button.objectName()
    finally:
        _close(app)

def test_fetch_models_toolbar_button_stays_outline() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        fetch_txt = "".join(chr(c) for c in [0x83B7, 0x53D6, 0x6A21, 0x578B])
        test_txt = "".join(chr(c) for c in [0x6D4B, 0x8BD5])
        toolbar = app.findChild(QWidget, "providerToolbar")
        assert toolbar is not None
        buttons = [b for b in toolbar.findChildren(QPushButton) if b.isVisible()]
        fetch_btn = next(b for b in buttons if fetch_txt in b.text())
        test_btn = next(b for b in buttons if test_txt in b.text())
        assert fetch_btn.objectName() == "btnGhost", fetch_btn.objectName()
        assert test_btn.objectName() == "btnGhost", test_btn.objectName()
        for button in (fetch_btn, test_btn):
            pix = button.grab()
            image = pix.toImage()
            x = max(12, image.width() // 2)
            y = min(3, max(0, image.height() - 1))
            color = image.pixelColor(x, y)
            assert color.lightness() >= 220, (button.text(), button.objectName(), color.name(), color.lightness())
            assert color.saturation() < 40, (button.text(), button.objectName(), color.name(), color.saturation())
    finally:
        _close(app)


def test_provider_form_labels_share_a_stable_column() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        labels = [
            widget for widget in app.findChildren(QLabel)
            if widget.isVisible() and widget.objectName() == "providerFieldLabel"
        ]
        assert len(labels) >= 6, len(labels)
        left_edges = {label.mapTo(app, label.rect().topLeft()).x() for label in labels}
        assert len(left_edges) == 1, left_edges
        widths = [label.width() for label in labels]
        assert max(widths) - min(widths) <= 2, widths
    finally:
        _close(app)


def test_provider_selector_aligns_with_provider_form_fields() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        selector = app.findChild(QComboBox, "providerSelector")
        name_field = app.findChild(QLineEdit, "providerNameEntry")
        assert selector is not None
        assert name_field is not None
        selector_left = selector.mapTo(app, selector.rect().topLeft()).x()
        field_left = name_field.mapTo(app, name_field.rect().topLeft()).x()
        assert abs(selector_left - field_left) <= 2, (selector_left, field_left)
    finally:
        _close(app)


def test_provider_actions_have_feedback_label_and_loading_state() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        feedback = app.findChild(QLabel, "providerActionStatus")
        assert feedback is not None
        assert feedback.isVisible()
        fetch_txt = "".join(chr(c) for c in [0x83B7, 0x53D6, 0x6A21, 0x578B])
        fetch_btn = next(
            button for button in app.findChildren(QPushButton)
            if fetch_txt in button.text()
        )
        assert hasattr(app, "_provider_fetch_buttons")
        assert fetch_btn in app._provider_fetch_buttons
        assert getattr(app, "_provider_action_busy", False) is False
    finally:
        _close(app)


def test_command_bar_has_primary_and_quiet_secondary_hierarchy() -> None:
    from app import AIMarkerApp

    app = AIMarkerApp()
    try:
        app.show()
        app.resize(420, 780)
        app.update()
        action_bar = app.findChild(QWidget, "commandActions")
        assert action_bar is not None
        buttons = [button for button in action_bar.findChildren(QPushButton) if button.isVisible()]
        start_txt = "".join(chr(c) for c in [0x5F00, 0x59CB, 0x6279, 0x6539])
        debug_txt = "".join(chr(c) for c in [0x8C03, 0x8BD5])
        start = next(button for button in buttons if start_txt in button.text())
        debug = next(button for button in buttons if debug_txt in button.text())
        assert start.objectName() == "btnPrimary"
        assert debug.objectName() == "btnGhost"
    finally:
        _close(app)


def _widget_fits(widget, root) -> bool:
    if not widget.isVisible():
        return True
    top_left, bottom_right = _mapped_rect(widget, root)
    if top_left.x() < -1 or top_left.y() < -1:
        return False
    if bottom_right.x() > root.width() + 1:
        return False
    if bottom_right.y() > root.height() + 1:
        return False
    text = widget.text().strip() if hasattr(widget, "text") else ""
    if text:
        width = widget.fontMetrics().horizontalAdvance(text)
        if width > max(12, widget.width() - 6):
            return False
    return True


def _assert_widget_fits(widget, root) -> None:
    assert _widget_fits(widget, root), widget.text() if hasattr(widget, "text") else widget


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
