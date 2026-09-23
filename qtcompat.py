from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import Qt, QEvent, QPoint, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QPixmap, QTextCharFormat, QTextCursor
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QTextEdit,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


_APP: QApplication | None = None
os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")


_FUSION_READY = False
_FUSION_LOCK = False


def ensure_app() -> QApplication:
    global _APP
    os.environ.setdefault("QT_STYLE_OVERRIDE", "Fusion")
    app = QApplication.instance()
    if app is None:
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QStyleFactory
        QApplication.setHighDpiScaleFactorRoundingPolicy(
            Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
        )
        fusion = QStyleFactory.create("Fusion")
        if fusion is not None:
            QApplication.setStyle(fusion)
        _APP = QApplication([])
        app = _APP
    _force_fusion(app)
    return app


def _force_fusion(app: QApplication) -> None:
    global _FUSION_READY, _FUSION_LOCK
    if _FUSION_READY or _FUSION_LOCK:
        return
    _FUSION_LOCK = True
    from PySide6.QtGui import QPalette
    from PySide6.QtWidgets import QStyleFactory

    style = QStyleFactory.create("Fusion")
    if style is not None:
        app.setStyle(style)
    pal = QPalette()
    pal.setColor(QPalette.Window, QColor("#F4F7FC"))
    pal.setColor(QPalette.WindowText, QColor("#0F172A"))
    pal.setColor(QPalette.Base, QColor("#FFFFFF"))
    pal.setColor(QPalette.AlternateBase, QColor("#F8FAFC"))
    pal.setColor(QPalette.Text, QColor("#0F172A"))
    pal.setColor(QPalette.Button, QColor("#FFFFFF"))
    pal.setColor(QPalette.ButtonText, QColor("#0F172A"))
    pal.setColor(QPalette.BrightText, QColor("#FFFFFF"))
    pal.setColor(QPalette.Highlight, QColor("#3B82F6"))
    pal.setColor(QPalette.HighlightedText, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipBase, QColor("#FFFFFF"))
    pal.setColor(QPalette.ToolTipText, QColor("#0F172A"))
    pal.setColor(QPalette.PlaceholderText, QColor("#94A3B8"))
    pal.setColor(QPalette.Light, QColor("#FFFFFF"))
    pal.setColor(QPalette.Midlight, QColor("#E8EEF8"))
    pal.setColor(QPalette.Mid, QColor("#C9D4E8"))
    pal.setColor(QPalette.Dark, QColor("#64748B"))
    pal.setColor(QPalette.Shadow, QColor("#94A3B8"))
    app.setPalette(pal)
    try:
        import theme as _theme
        sheet = getattr(_theme, "APP_STYLESHEET", "")
        if sheet and app.styleSheet() != sheet:
            app.setStyleSheet(sheet)
    except Exception:
        pass
    finally:
        _FUSION_READY = True
        _FUSION_LOCK = False


def _qfont(spec) -> QFont:
    if isinstance(spec, QFont):
        return spec
    if isinstance(spec, str):
        return QFont(spec, 11)
    family = spec[0] if spec else "Segoe UI"
    size = 11
    weight = QFont.Normal
    if len(spec) > 1 and isinstance(spec[1], int):
        size = spec[1]
    if len(spec) > 2 and str(spec[2]).lower() == "bold":
        weight = QFont.Bold
    font = QFont(family, size)
    font.setWeight(weight)
    return font


class Var:
    def __init__(self, value: Any = "") -> None:
        self._value = value
        self._callbacks: list[Callable] = []
        self._widgets: list[Any] = []

    def get(self):
        return self._value

    def set(self, value) -> None:
        self._value = value
        for widget in list(self._widgets):
            try:
                widget._sync_from_var()
            except Exception:
                pass
        for cb in list(self._callbacks):
            try:
                cb()
            except TypeError:
                try:
                    cb("", "", "")
                except Exception:
                    pass
            except Exception:
                pass

    def trace_add(self, _mode, cb) -> None:
        self._callbacks.append(cb)


class StringVar(Var):
    def __init__(self, value: str = "") -> None:
        super().__init__("" if value is None else str(value))

    def set(self, value) -> None:
        super().set("" if value is None else str(value))


class BooleanVar(Var):
    def __init__(self, value: bool = False) -> None:
        super().__init__(bool(value))

    def set(self, value) -> None:
        super().set(bool(value))

    def get(self) -> bool:
        return bool(self._value)


class IntVar(Var):
    def __init__(self, value: int = 0) -> None:
        try:
            super().__init__(int(value))
        except Exception:
            super().__init__(0)

    def set(self, value) -> None:
        try:
            super().set(int(float(value)))
        except Exception:
            super().set(0)

    def get(self) -> int:
        return int(self._value)


def _pack_stretch(layout, fill, expand) -> int:
    if expand or fill == "both":
        return 1
    if fill == "x" and isinstance(layout, QHBoxLayout):
        return 1
    if fill == "y" and isinstance(layout, QVBoxLayout):
        return 1
    return 0


def _layout_has_flex_space(layout) -> bool:
    for i in range(layout.count()):
        item = layout.itemAt(i)
        if item is None:
            continue
        if layout.stretch(i) > 0:
            return True
        spacer = item.spacerItem()
        if spacer is not None:
            directions = spacer.expandingDirections()
            if directions & Qt.Horizontal or directions & Qt.Vertical:
                return True
    return False


def _apply_pack_margins(widget, kwargs) -> None:
    padx = kwargs.get("padx", 0)
    pady = kwargs.get("pady", 0)
    if not padx and not pady:
        return
    if isinstance(padx, (tuple, list)):
        left, right = int(padx[0]), int(padx[1] if len(padx) > 1 else padx[0])
    else:
        left = right = int(padx or 0)
    if isinstance(pady, (tuple, list)):
        top, bottom = int(pady[0]), int(pady[1] if len(pady) > 1 else pady[0])
    else:
        top = bottom = int(pady or 0)
    parent = widget.parent()
    layout = parent.layout() if parent is not None else None
    if layout is None:
        return
    idx = layout.indexOf(widget)
    if idx < 0:
        return
    if isinstance(layout, QVBoxLayout):
        if top:
            layout.insertSpacing(idx, top)
            idx += 1
        if bottom:
            layout.insertSpacing(idx + 1, bottom)
        if left or right:
            margins = widget.contentsMargins()
            widget.setContentsMargins(left, margins.top(), right, margins.bottom())
    elif isinstance(layout, QHBoxLayout):
        if left:
            layout.insertSpacing(idx, left)
            idx += 1
        if right:
            layout.insertSpacing(idx + 1, right)
        if top or bottom:
            margins = widget.contentsMargins()
            widget.setContentsMargins(margins.left(), top, margins.right(), bottom)


class TkGeom:
    def pack(self, **kwargs):
        parent = self.parent()
        if parent is None:
            return self
        side = kwargs.get("side", "top")
        fill = kwargs.get("fill")
        expand = bool(kwargs.get("expand"))
        layout = parent.layout()
        if layout is None:
            layout = QHBoxLayout(parent) if side in {"left", "right"} else QVBoxLayout(parent)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
        if layout.indexOf(self) < 0 and hasattr(layout, "addWidget"):
            stretch = _pack_stretch(layout, fill, expand)
            if isinstance(layout, QHBoxLayout) and side == "right":
                if not _layout_has_flex_space(layout):
                    layout.addStretch(1)
                layout.addWidget(self, stretch)
            else:
                layout.addWidget(self, stretch)
            if fill == "both":
                self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            elif fill == "x":
                self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            elif fill == "y":
                self.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Expanding)
            elif expand and isinstance(layout, QHBoxLayout):
                self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Maximum)
            elif expand:
                self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            _apply_pack_margins(self, kwargs)
        self.show()
        return self

    def grid(self, **kwargs):
        parent = self.parent()
        if parent is None:
            return self
        from PySide6.QtWidgets import QGridLayout
        layout = parent.layout()
        if layout is None:
            layout = QGridLayout(parent)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
        elif not isinstance(layout, QGridLayout):
            layout = QGridLayout(parent)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(4)
        r = int(kwargs.get("row", 0))
        c = int(kwargs.get("column", 0))
        rs = int(kwargs.get("rowspan", 1))
        cs = int(kwargs.get("columnspan", 1))
        sticky = str(kwargs.get("sticky") or "")
        layout.addWidget(self, r, c, rs, cs)
        if hasattr(layout, "setAlignment"):
            align = Qt.Alignment(0)
            if "n" in sticky:
                align |= Qt.AlignTop
            if "s" in sticky:
                align |= Qt.AlignBottom
            if "w" in sticky:
                align |= Qt.AlignLeft
            if "e" in sticky:
                align |= Qt.AlignRight
            if "e" in sticky and "w" in sticky:
                self.setSizePolicy(QSizePolicy.Expanding, self.sizePolicy().verticalPolicy())
                layout.setAlignment(self, Qt.Alignment(0))
            elif align:
                layout.setAlignment(self, align)
            else:
                layout.setAlignment(self, Qt.AlignLeft | Qt.AlignVCenter)
        if "n" in sticky and "s" in sticky:
            self.setSizePolicy(self.sizePolicy().horizontalPolicy(), QSizePolicy.Expanding)
        self.show()
        return self

    def pack_forget(self):
        self.hide()
        return self

    def grid_forget(self):
        self.hide()
        return self

    def place_forget(self):
        self.hide()
        return self


class Frame(QFrame, TkGeom):
    def __init__(self, parent=None, **kwargs):
        super().__init__(parent)
        padding = kwargs.get("padding")
        if padding is not None:
            if isinstance(padding, int):
                self.setContentsMargins(padding, padding, padding, padding)
            elif isinstance(padding, (tuple, list)):
                vals = list(padding) + [0, 0, 0, 0]
                self.setContentsMargins(vals[0], vals[1], vals[2], vals[3])


class Label(QLabel, TkGeom):
    def __init__(self, parent=None, text="", textvariable=None, image=None, font=None, foreground=None, **kwargs):
        super().__init__(parent)
        self._var = textvariable
        if font:
            self.setFont(_qfont(font))
        if foreground:
            self.setStyleSheet(f"color: {foreground};")
        if image is not None:
            self.setPixmap(image if isinstance(image, QPixmap) else QPixmap(image))
        if textvariable is not None:
            textvariable._widgets.append(self)
            self.setText(str(textvariable.get()))
        elif text:
            self.setText(str(text))
        wrap = kwargs.get("wraplength")
        if wrap:
            self.setWordWrap(True)
            self.setMaximumWidth(int(wrap))

    def _sync_from_var(self):
        if self._var is not None:
            self.setText(str(self._var.get()))

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.setText(str(kwargs["text"]))
        if "foreground" in kwargs:
            extra = self.styleSheet()
            self.setStyleSheet(f"{extra} color: {kwargs['foreground']};")
        if "image" in kwargs and kwargs["image"] is not None:
            image = kwargs["image"]
            self.setPixmap(image if isinstance(image, QPixmap) else QPixmap(image))
        if "font" in kwargs:
            self.setFont(_qfont(kwargs["font"]))
        if "bootstyle" in kwargs:
            pass
        return self


def _bootstyle_name(bootstyle) -> str:
    if not bootstyle:
        return ""
    parts = bootstyle if isinstance(bootstyle, (tuple, list)) else (bootstyle,)
    names = [str(p).lower() for p in parts if p]
    if "outline" in names:
        return "btnGhost"
    if "success" in names:
        return "btnSuccess"
    if "danger" in names:
        return "btnDanger"
    if "warning" in names:
        return "btnWarning"
    if "info" in names:
        return "btnInfo"
    if "primary" in names:
        return "btnPrimary"
    if "secondary" in names:
        return "btnGhost"
    return ""


class Button(QPushButton, TkGeom):
    def __init__(self, parent=None, text="", command=None, state="normal", image=None, **kwargs):
        super().__init__(str(text), parent)
        self._command = command
        if command:
            self.clicked.connect(command)
        if image is not None:
            if isinstance(image, QIcon):
                self.setIcon(image)
            elif isinstance(image, QPixmap):
                self.setIcon(QIcon(image))
        name = _bootstyle_name(kwargs.get("bootstyle"))
        if name:
            self.setObjectName(name)
        self.setSizePolicy(QSizePolicy.Minimum, QSizePolicy.Fixed)
        self.setCursor(Qt.PointingHandCursor)
        self.configure(state=state, **{k: v for k, v in kwargs.items() if k in {"text", "image"}})

    def configure(self, **kwargs):
        if "text" in kwargs:
            self.setText(str(kwargs["text"]))
        if "state" in kwargs:
            enabled = str(kwargs["state"]) not in {"disabled", "0"}
            self.setEnabled(enabled)
        if "command" in kwargs:
            if self._command:
                try:
                    self.clicked.disconnect(self._command)
                except Exception:
                    pass
            self._command = kwargs["command"]
            if self._command:
                self.clicked.connect(self._command)
        if "image" in kwargs and kwargs["image"] is not None:
            image = kwargs["image"]
            if isinstance(image, QIcon):
                self.setIcon(image)
            elif isinstance(image, QPixmap):
                self.setIcon(QIcon(image))
        return self


class Entry(QLineEdit, TkGeom):
    def __init__(self, parent=None, textvariable=None, show=None, width=None, **kwargs):
        super().__init__(parent)
        self._var = textvariable
        if show:
            self.setEchoMode(QLineEdit.Password)
        if width:
            self.setMaximumWidth(max(48, int(width) * 8))
        if textvariable is not None:
            self.setText(str(textvariable.get()))
            textvariable._widgets.append(self)
            self.textChanged.connect(lambda text: textvariable.set(text) if textvariable.get() != text else None)

    def _sync_from_var(self):
        if self._var is not None and self.text() != str(self._var.get()):
            self.setText(str(self._var.get()))


class Checkbutton(QCheckBox, TkGeom):
    def __init__(self, parent=None, text="", variable=None, **kwargs):
        super().__init__(str(text), parent)
        self._var = variable
        if variable is not None:
            self.setChecked(bool(variable.get()))
            variable._widgets.append(self)
            self.toggled.connect(lambda checked: variable.set(checked) if bool(variable.get()) != bool(checked) else None)

    def _sync_from_var(self):
        if self._var is not None and bool(self.isChecked()) != bool(self._var.get()):
            self.setChecked(bool(self._var.get()))


class Combobox(QComboBox, TkGeom):
    def __init__(self, parent=None, textvariable=None, values=None, state=None, width=None, **kwargs):
        super().__init__(parent)
        self._var = textvariable
        self._updating = False
        if width:
            self.setMinimumWidth(max(48, min(180, int(width) * 7)))
        if values:
            self.addItems([str(v) for v in values])
        if state == "readonly":
            self.setEditable(False)
        if textvariable is not None:
            current = str(textvariable.get())
            if current:
                idx = self.findText(current)
                if idx >= 0:
                    self.setCurrentIndex(idx)
                else:
                    self.setEditText(current) if self.isEditable() else None
                    if idx < 0 and current:
                        self.setCurrentText(current)
            textvariable._widgets.append(self)
            self.currentTextChanged.connect(self._on_changed)

    def _on_changed(self, text: str) -> None:
        if self._updating or self._var is None:
            return
        if self._var.get() != text:
            self._var.set(text)

    def _sync_from_var(self):
        if self._var is None:
            return
        text = str(self._var.get())
        if self.currentText() != text:
            self._updating = True
            idx = self.findText(text)
            if idx >= 0:
                self.setCurrentIndex(idx)
            elif self.isEditable():
                self.setEditText(text)
            else:
                self.setCurrentText(text)
            self._updating = False

    def configure(self, **kwargs):
        if "values" in kwargs:
            values = [str(v) for v in (kwargs["values"] or [])]
            current = self.currentText() if self._var is None else str(self._var.get())
            self._updating = True
            self.clear()
            self.addItems(values)
            if current:
                idx = self.findText(current)
                if idx >= 0:
                    self.setCurrentIndex(idx)
                elif self.isEditable():
                    self.setEditText(current)
            self._updating = False
        if "state" in kwargs:
            self.setEnabled(str(kwargs["state"]) != "disabled")
            if kwargs["state"] == "readonly":
                self.setEditable(False)
        if "textvariable" in kwargs:
            self._var = kwargs["textvariable"]
        return self

    def bind(self, event, callback):
        if event == "<<ComboboxSelected>>":
            self.currentIndexChanged.connect(lambda *_a: callback(None))
        return self


class Scale(QSlider, TkGeom):
    def __init__(self, parent=None, from_=0, to=3, variable=None, orient="horizontal", command=None, **kwargs):
        orientation = Qt.Horizontal if orient != "vertical" else Qt.Vertical
        super().__init__(orientation, parent)
        self.setRange(int(from_), int(to))
        self._var = variable
        self._command = command
        if variable is not None:
            self.setValue(int(variable.get()))
            variable._widgets.append(self)
            self.valueChanged.connect(self._on_changed)

    def _on_changed(self, value: int) -> None:
        if self._var is not None and int(self._var.get()) != int(value):
            self._var.set(int(value))
        if self._command:
            self._command(value)

    def _sync_from_var(self):
        if self._var is not None and int(self.value()) != int(self._var.get()):
            self.setValue(int(self._var.get()))


class Text(QTextEdit, TkGeom):
    def __init__(self, parent=None, height=None, wrap="word", font=None, **kwargs):
        super().__init__(parent)
        self._tags: dict[str, dict] = {}
        self._mono = False
        if height:
            self.setMinimumHeight(int(height) * 18)
        if wrap == "word":
            self.setLineWrapMode(QTextEdit.WidgetWidth)
        if font:
            self.setFont(_qfont(font))

    def get(self, start="1.0", end="end"):
        text = self.toPlainText()
        if start in {"1.0", "0.0"} and end in {"end", "end-1c"}:
            return text
        return text

    def insert(self, index, text):
        if index in {"1.0", "0.0"}:
            cursor = self.textCursor()
            cursor.movePosition(QTextCursor.Start)
            cursor.insertText(str(text))
            return
        self.moveCursor(QTextCursor.End)
        self.insertPlainText(str(text))

    def delete(self, start="1.0", end="end"):
        if start in {"1.0", "0.0"} and end in {"end", "end-1c"}:
            self.clear()
            return
        self.clear()

    def tag_config(self, name, **kwargs):
        self._tags[name] = kwargs

    def tag_add(self, name, start, end):
        cfg = self._tags.get(name, {})
        fmt = QTextCharFormat()
        if "foreground" in cfg:
            fmt.setForeground(QColor(cfg["foreground"]))
        if "font" in cfg:
            fmt.setFont(_qfont(cfg["font"]))
        cursor = self.textCursor()
        cursor.select(QTextCursor.Document)
        cursor.mergeCharFormat(fmt)

    def configure(self, **kwargs):
        if "state" in kwargs:
            self.setReadOnly(str(kwargs["state"]) in {"disabled", "readonly"})
        if "font" in kwargs:
            self.setFont(_qfont(kwargs["font"]))
        if "foreground" in kwargs:
            self.setStyleSheet(f"color: {kwargs['foreground']};")
        return self

    def yview(self, *args):
        return (0.0, 1.0)

    def yview_moveto(self, _value):
        self.verticalScrollBar().setValue(0)

    def index(self, spec):
        return "1.0"

    def see(self, _index):
        self.moveCursor(QTextCursor.End)


class Listbox(QListWidget, TkGeom):
    def __init__(self, parent=None, height=None, **kwargs):
        parent = _reparent(parent) if "_reparent" in globals() else parent
        super().__init__(parent)
        if height:
            self.setMinimumHeight(int(height) * 18)

    def delete(self, first=0, last=None):
        if last in {"end", None} or (first == 0 and last == "end"):
            self.clear()
            return
        if last is None:
            self.takeItem(int(first))
            return
        self.clear()

    def insert(self, index, text):
        if index in {"end", None}:
            self.addItem(str(text))
            return
        self.insertItem(int(index), str(text))

    def curselection(self):
        return [item.row() for item in self.selectedIndexes()]

    def get(self, index):
        item = self.item(int(index))
        return item.text() if item else ""

    def configure(self, **kwargs):
        return self


class Treeview(QTreeWidget, TkGeom):
    def __init__(self, parent=None, columns=(), show="headings", height=8, **kwargs):
        super().__init__(parent)
        self.setColumnCount(len(columns))
        self.setHeaderLabels(list(columns))
        self.setRootIsDecorated(False)
        self.setSelectionMode(QTreeWidget.SingleSelection)
        self._columns = list(columns)
        if height:
            self.setMinimumHeight(int(height) * 22)

    def heading(self, column, text=""):
        idx = self._columns.index(column) if column in self._columns else 0
        item = self.headerItem()
        item.setText(idx, text)

    def column(self, column, width=80, **kwargs):
        idx = self._columns.index(column) if column in self._columns else 0
        self.setColumnWidth(idx, int(width))

    def selection(self):
        items = self.selectedItems()
        return [item.data(0, Qt.UserRole) or str(self.indexOfTopLevelItem(item)) for item in items]

    def selection_set(self, iid):
        iid = str(iid)
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if str(item.data(0, Qt.UserRole)) == iid or str(i) == iid:
                self.setCurrentItem(item)
                item.setSelected(True)
                return

    def see(self, iid):
        iid = str(iid)
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            if str(item.data(0, Qt.UserRole)) == iid or str(i) == iid:
                self.scrollToItem(item)
                return

    def get_children(self):
        return [str(self.topLevelItem(i).data(0, Qt.UserRole) or i) for i in range(self.topLevelItemCount())]

    def delete(self, *items):
        if not items:
            self.clear()
            return
        current = set(str(x) for x in items)
        keep = []
        for i in range(self.topLevelItemCount()):
            item = self.topLevelItem(i)
            iid = str(item.data(0, Qt.UserRole) or i)
            if iid not in current:
                keep.append((iid, [item.text(c) for c in range(self.columnCount())]))
        self.clear()
        for iid, values in keep:
            self.insert("", "end", iid=iid, values=values)

    def insert(self, _parent, _index, iid="", values=()):
        item = QTreeWidgetItem([str(v) for v in values])
        item.setData(0, Qt.UserRole, str(iid))
        self.addTopLevelItem(item)
        return iid


class Notebook(QTabWidget, TkGeom):
    def add(self, child, text=""):
        self.addTab(child, text)

    def tab(self, index, option=None, **kwargs):
        if option == "text":
            return self.tabText(index)
        if "state" in kwargs:
            self.setTabEnabled(index, kwargs["state"] != "disabled")

    def index(self, current="current"):
        return self.currentIndex()

    def select(self, index):
        self.setCurrentIndex(int(index))


class Labelframe(QFrame, TkGeom):
    def __init__(self, parent=None, text="", **kwargs):
        super().__init__(parent)
        self.setFrameShape(QFrame.StyledPanel)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        self._title = QLabel(text)
        self._title.setStyleSheet("font-weight: 600;")
        layout.addWidget(self._title)


class Scrollable(QScrollArea, TkGeom):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._inner = QWidget()
        self.setWidget(self._inner)
        QVBoxLayout(self._inner)

    def yview_moveto(self, _value):
        self.verticalScrollBar().setValue(0)

    def yview(self, *args):
        return (0.0, 1.0)


class _MessageBox:
    @staticmethod
    def showerror(title, message):
        ensure_app()
        QMessageBox.critical(None, str(title), str(message))

    @staticmethod
    def showinfo(title, message):
        ensure_app()
        QMessageBox.information(None, str(title), str(message))

    @staticmethod
    def showwarning(title, message):
        ensure_app()
        QMessageBox.warning(None, str(title), str(message))

    @staticmethod
    def askokcancel(title, message):
        ensure_app()
        return QMessageBox.question(None, str(title), str(message), QMessageBox.Ok | QMessageBox.Cancel) == QMessageBox.Ok

    @staticmethod
    def askyesno(title, message):
        ensure_app()
        return QMessageBox.question(None, str(title), str(message), QMessageBox.Yes | QMessageBox.No) == QMessageBox.Yes


class _FileDialog:
    @staticmethod
    def askopenfilenames(**kwargs):
        ensure_app()
        files, _ = QFileDialog.getOpenFileNames(None, kwargs.get("title", "Open"), kwargs.get("initialdir", ""), kwargs.get("filetypes", [("All", "*")])[0][1] if kwargs.get("filetypes") else "")
        return files

    @staticmethod
    def askopenfilename(**kwargs):
        ensure_app()
        filt = ""
        if kwargs.get("filetypes"):
            filt = ";;".join(f"{name} ({pat})" for name, pat in kwargs["filetypes"])
        path, _ = QFileDialog.getOpenFileName(None, kwargs.get("title", "Open"), kwargs.get("initialdir", ""), filt)
        return path

    @staticmethod
    def asksaveasfilename(**kwargs):
        ensure_app()
        filt = ""
        if kwargs.get("filetypes"):
            filt = ";;".join(f"{name} ({pat})" for name, pat in kwargs["filetypes"])
        path, _ = QFileDialog.getSaveFileName(None, kwargs.get("title", "Save"), kwargs.get("initialdir", "") or kwargs.get("defaultextension", ""), filt)
        return path


messagebox = _MessageBox()
filedialog = _FileDialog()


class WindowMixin:
    def after(self, ms, callback=None):
        timer = QTimer(self)
        timer.setSingleShot(True)
        token = {"timer": timer}
        if callback:
            timer.timeout.connect(callback)
        timer.start(int(ms))
        ident = id(timer)
        if not hasattr(self, "_after_timers"):
            self._after_timers = {}
        self._after_timers[ident] = timer
        return ident

    def after_cancel(self, ident):
        timer = getattr(self, "_after_timers", {}).pop(ident, None)
        if timer is not None:
            timer.stop()
            timer.deleteLater()

    def update_idletasks(self):
        ensure_app().processEvents()

    def update(self):
        ensure_app().processEvents()

    def winfo_exists(self):
        try:
            return bool(self.isVisible() or True) and not self._closed
        except Exception:
            return False

    def protocol(self, name, callback):
        if name == "WM_DELETE_WINDOW":
            self._close_callback = callback

    def StringVar(self, value="", **kwargs):
        return StringVar(value)

    def BooleanVar(self, value=False, **kwargs):
        return BooleanVar(bool(value))

    def IntVar(self, value=0, **kwargs):
        try:
            return IntVar(int(value))
        except Exception:
            return IntVar(0)

    def mainloop(self):
        self.show()
        ensure_app().exec()

    def title(self, text=None):
        if text is None:
            return self.windowTitle()
        self.setWindowTitle(str(text))
        return text

    def geometry(self, spec=None):
        if spec is None:
            size = self.size()
            return f"{size.width()}x{size.height()}"
        if "x" in spec and "+" not in spec:
            w, h = spec.lower().split("x")
            self.resize(int(w), int(h))
        return spec

    def minsize(self, w, h):
        self.setMinimumSize(int(w), int(h))

    def destroy(self):
        self._closed = True
        self.close()

    def font(self):
        return self._app_font if hasattr(self, "_app_font") else QFont("Segoe UI", 11)


from PySide6.QtWidgets import QScrollBar, QSplitter, QSizePolicy
from PySide6.QtGui import QCursor, QGuiApplication


DANGER = "danger"
INFO = "info"
OUTLINE = "outline"
PRIMARY = "primary"
SECONDARY = "secondary"
SUCCESS = "success"
WARNING = "warning"
Variable = Var


class _Colors:
    def __init__(self) -> None:
        self.primary = "#3B82F6"
        self.secondary = "#64748B"
        self.success = "#27AE60"
        self.warning = "#F39C12"
        self.danger = "#E74C3C"
        self.info = "#3B82F6"
        self.inputbg = "#FFFFFF"
        self.inputfg = "#0F172A"
        self.selectfg = "#FFFFFF"
        self.border = "#E2E8F0"
        self.light = "#F8FAFC"
        self.dark = "#0F172A"


class DummyStyle:
    def __init__(self) -> None:
        self.colors = _Colors()
        self._theme = "flatly"

    def theme_use(self, name=None):
        if name is None:
            return self._theme
        self._theme = name
        return name

    def configure(self, *args, **kwargs):
        return None


def _reparent(parent):
    if parent is not None and isinstance(parent, QMainWindow):
        return parent.centralWidget() or parent
    return parent


_orig_frame_init = Frame.__init__


def _frame_init(self, parent=None, **kwargs):
    parent = _reparent(parent)
    _orig_frame_init(self, parent, **kwargs)
    bg = kwargs.get("bg") or kwargs.get("background")
    if bg:
        from PySide6.QtGui import QColor, QPalette

        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setAutoFillBackground(True)
        self.setFrameShape(QFrame.NoFrame)
        pal = self.palette()
        pal.setColor(self.backgroundRole(), QColor(bg))
        self.setPalette(pal)
        self.setStyleSheet("background-color: %s; border: none;" % bg)
    if kwargs.get("width"):
        self.setFixedWidth(int(kwargs["width"]))
    if kwargs.get("height"):
        self.setFixedHeight(int(kwargs["height"]))


Frame.__init__ = _frame_init

_orig_label_init = Label.__init__


def _label_init(self, parent=None, text="", textvariable=None, image=None, font=None, foreground=None, **kwargs):
    parent = _reparent(parent)
    _orig_label_init(self, parent, text=text, textvariable=textvariable, image=image, font=font, foreground=foreground, **kwargs)
    name = kwargs.get("name")
    if name:
        self.setObjectName(str(name))
    justify = kwargs.get("justify")
    if justify == "center":
        self.setAlignment(Qt.AlignCenter)
    elif justify == "left":
        self.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)


Label.__init__ = _label_init

_orig_button_init = Button.__init__


def _button_init(self, parent=None, text="", command=None, state="normal", image=None, **kwargs):
    parent = _reparent(parent)
    bootstyle = kwargs.pop("bootstyle", None)
    kwargs.pop("style", None)
    kwargs.pop("color", None)
    kwargs.pop("width", None)
    compound = kwargs.pop("compound", None)
    _orig_button_init(self, parent, text=text, command=command, state=state, image=image, bootstyle=bootstyle, **kwargs)
    if compound == "left":
        self.setLayoutDirection(Qt.LeftToRight)
        self.setIconSize(self.iconSize())
    self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
    self.setMinimumWidth(0)
    name = _bootstyle_name(bootstyle)
    if name:
        self.setObjectName(name)


Button.__init__ = _button_init

_orig_entry_init = Entry.__init__


def _entry_init(self, parent=None, textvariable=None, show=None, width=None, **kwargs):
    parent = _reparent(parent)
    kwargs.pop("bootstyle", None)
    _orig_entry_init(self, parent, textvariable=textvariable, show=show, width=width, **kwargs)


Entry.__init__ = _entry_init

_orig_check_init = Checkbutton.__init__


def _check_init(self, parent=None, text="", variable=None, **kwargs):
    parent = _reparent(parent)
    kwargs.pop("bootstyle", None)
    _orig_check_init(self, parent, text=text, variable=variable, **kwargs)


Checkbutton.__init__ = _check_init

_orig_combo_init = Combobox.__init__


def _combo_init(self, parent=None, textvariable=None, values=None, state=None, width=None, **kwargs):
    parent = _reparent(parent)
    kwargs.pop("bootstyle", None)
    _orig_combo_init(self, parent, textvariable=textvariable, values=values, state=state, width=width, **kwargs)


Combobox.__init__ = _combo_init

_orig_combo_bind = Combobox.bind


def _combo_bind(self, event, callback):
    if event == "<FocusOut>":
        self.lineEdit().editingFinished.connect(lambda: callback(None)) if self.isEditable() else None
        self.installEventFilter(self)
        self._focus_out_cb = callback
        return self
    return _orig_combo_bind(self, event, callback)


Combobox.bind = _combo_bind


def _widget_bind(self, event, callback):
    if event == "<MouseWheel>":
        self._wheel_cb = callback
        return self
    if event == "<Configure>":
        self._configure_cb = callback
        return self
    if event == "<Escape>":
        self._escape_cb = callback
        return self
    if event == "<<ComboboxSelected>>" and hasattr(self, "currentIndexChanged"):
        self.currentIndexChanged.connect(lambda *_a: callback(None))
        return self
    if event == "<FocusOut>":
        self._focus_out_cb = callback
        return self
    return self


def _widget_winfo_toplevel(self):
    widget = self
    while widget is not None:
        if isinstance(widget, (QMainWindow, QDialog)):
            return widget
        widget = widget.parent()
    return self.window()


def _widget_winfo_width(self):
    return max(1, int(self.width()))


def _widget_winfo_height(self):
    return max(1, int(self.height()))


def _widget_winfo_screenwidth(self):
    screen = QGuiApplication.primaryScreen()
    return screen.geometry().width() if screen else 1920


def _widget_winfo_screenheight(self):
    screen = QGuiApplication.primaryScreen()
    return screen.geometry().height() if screen else 1080


def _widget_config(self, **kwargs):
    if hasattr(self, "configure"):
        try:
            return self.configure(**kwargs)
        except TypeError:
            pass
    if "text" in kwargs and hasattr(self, "setText"):
        self.setText(str(kwargs["text"]))
    if "state" in kwargs and hasattr(self, "setEnabled"):
        self.setEnabled(str(kwargs["state"]) not in {"disabled", "0"})
    if "foreground" in kwargs:
        extra = self.styleSheet() if hasattr(self, "styleSheet") else ""
        self.setStyleSheet("%s color: %s;" % (extra, kwargs["foreground"]))
    if "bootstyle" in kwargs:
        pass
    return self


TkGeom.bind = _widget_bind
TkGeom.winfo_toplevel = _widget_winfo_toplevel
TkGeom.winfo_width = _widget_winfo_width
TkGeom.winfo_height = _widget_winfo_height
TkGeom.winfo_screenwidth = _widget_winfo_screenwidth
TkGeom.winfo_screenheight = _widget_winfo_screenheight
TkGeom.config = _widget_config
Label.config = Label.configure
Button.config = Button.configure
Combobox.config = Combobox.configure
Text.config = Text.configure
Listbox.config = Listbox.configure


class Scrollbar(QScrollBar, TkGeom):
    def __init__(self, parent=None, orient="vertical", command=None, **kwargs):
        parent = _reparent(parent)
        super().__init__(Qt.Vertical if orient != "horizontal" else Qt.Horizontal, parent)
        self._command = command
        if command:
            self.valueChanged.connect(self._emit)

    def _emit(self, value: int) -> None:
        if not self._command:
            return
        try:
            self._command("moveto", value / max(1, self.maximum()))
        except TypeError:
            try:
                self._command()
            except Exception:
                pass

    def set(self, first=0, last=1):
        return None

    def config(self, **kwargs):
        if "command" in kwargs:
            self._command = kwargs["command"]
        return self

    configure = config


class Separator(QFrame, TkGeom):
    def __init__(self, parent=None, orient="horizontal", **kwargs):
        parent = _reparent(parent)
        super().__init__(parent)
        if orient == "vertical":
            self.setFrameShape(QFrame.VLine)
            self.setFixedWidth(1)
        else:
            self.setFrameShape(QFrame.HLine)
            self.setFixedHeight(1)
        self.setStyleSheet("color: #E2E8F0; background: #E2E8F0;")


class PanedWindow(QSplitter, TkGeom):
    def __init__(self, parent=None, orient="horizontal", **kwargs):
        parent = _reparent(parent)
        super().__init__(Qt.Horizontal if orient != "vertical" else Qt.Vertical, parent)

    def add(self, child, weight=1):
        self.addWidget(child)
        idx = self.indexOf(child)
        if idx >= 0:
            self.setStretchFactor(idx, int(weight or 1))


class Canvas(QScrollArea, TkGeom):
    def __init__(self, parent=None, highlightthickness=0, bg=None, **kwargs):
        parent = _reparent(parent)
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self._inner = QWidget()
        self.setWidget(self._inner)
        self._layout = QVBoxLayout(self._inner)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(0)
        self._window = None
        self._images = []
        self._yscrollcommand = None
        if bg:
            self._apply_background(bg)

    def _apply_background(self, bg) -> None:
        from PySide6.QtGui import QPalette

        color = QColor(str(bg))
        widgets = [self, self._inner]
        viewport = self.viewport()
        if viewport is not None:
            widgets.append(viewport)
        for widget in widgets:
            widget.setAutoFillBackground(True)
            pal = widget.palette()
            pal.setColor(QPalette.Window, color)
            pal.setColor(QPalette.Base, color)
            widget.setPalette(pal)

    def create_window(self, _xy, window=None, anchor="nw", tags=None):
        self._window = window
        if window is not None:
            window.setParent(self._inner)
            window.setMinimumWidth(0)
            window.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            self._inner.setMinimumWidth(0)
            self._inner.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
            if self._layout.indexOf(window) < 0:
                self._layout.addWidget(window, 1)
            window.show()
        return 1

    def bbox(self, _what="all"):
        r = self._inner.childrenRect()
        return (r.x(), r.y(), r.x() + max(1, r.width()), r.y() + max(1, r.height()))

    def configure(self, **kwargs):
        if "bg" in kwargs or "background" in kwargs:
            bg = kwargs.get("bg") or kwargs.get("background")
            self._apply_background(bg)
        if "yscrollcommand" in kwargs:
            self._yscrollcommand = kwargs["yscrollcommand"]
        return self

    config = configure

    def yview(self, *args):
        bar = self.verticalScrollBar()
        if args and args[0] == "moveto":
            bar.setValue(int(float(args[1]) * bar.maximum()))
            return
        if args and args[0] == "scroll":
            bar.setValue(bar.value() + int(args[1]) * 24)
            return
        return (0.0, 1.0)

    def yview_scroll(self, n, _what="units"):
        bar = self.verticalScrollBar()
        bar.setValue(bar.value() - int(n) * 24)

    def yview_moveto(self, value):
        bar = self.verticalScrollBar()
        bar.setValue(int(float(value or 0) * bar.maximum()))

    def create_image(self, x, y, image=None, anchor="nw"):
        lbl = QLabel(self._inner)
        if isinstance(image, QPixmap):
            lbl.setPixmap(image)
        elif isinstance(image, QIcon):
            lbl.setPixmap(image.pixmap(64, 64))
        lbl.move(int(x), int(y))
        lbl.show()
        self._images.append(lbl)
        return len(self._images)

    def delete(self, *args):
        for lbl in self._images:
            lbl.deleteLater()
        self._images.clear()

    def bind(self, event, callback):
        if event == "<MouseWheel>":
            self._wheel_cb = callback
        elif event == "<Configure>":
            self._configure_cb = callback
        return self

    def wheelEvent(self, event):
        cb = getattr(self, "_wheel_cb", None)
        if cb:
            class E:
                delta = int(event.angleDelta().y())
            cb(E())
            event.accept()
            return
        super().wheelEvent(event)


class Window(QMainWindow, WindowMixin):
    def __init__(self, themename=None, **kwargs):
        ensure_app()
        QMainWindow.__init__(self)
        self._closed = False
        self._close_callback = None
        self._brand_icon_applied = False
        self._app_font = QFont("Segoe UI", 11)
        app = ensure_app()
        app.setFont(self._app_font)
        central = QWidget(self)
        self.setCentralWidget(central)
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.style = DummyStyle()
        self._themename = themename
        _force_fusion(app)
        try:
            import theme as _theme
            if hasattr(_theme, "apply_app_stylesheet"):
                _theme.apply_app_stylesheet()
            elif getattr(_theme, "APP_STYLESHEET", ""):
                app.setStyleSheet(_theme.APP_STYLESHEET)
        except Exception:
            pass

    def closeEvent(self, event):
        if getattr(self, "_closed", False):
            event.accept()
            return
        self._destroying = True
        self._closed = True
        for ident in list(getattr(self, "_after_timers", {})):
            self.after_cancel(ident)
        cb = getattr(self, "_close_callback", None)
        self._close_callback = None
        if cb:
            try:
                cb()
            except Exception:
                pass
        event.accept()

    def iconbitmap(self, path):
        try:
            self.setWindowIcon(QIcon(str(path)))
            self._brand_icon_applied = True
        except Exception:
            self._brand_icon_applied = False
        return self

    def winfo_toplevel(self):
        return self

    def bind(self, event, callback):
        if event == "<Escape>":
            self._escape_cb = callback
        return self

    def bind_all(self, event, callback):
        return self

    def attributes(self, *args, **kwargs):
        return self

    def overrideredirect(self, flag=True):
        return self

    def deiconify(self):
        self.show()
        return self

    def withdraw(self):
        self.hide()
        return self

    def lift(self):
        self.raise_()
        self.activateWindow()
        return self

    def resizable(self, w=True, h=True):
        if not w and not h:
            self.setFixedSize(self.size())
        return self

    def grab_set(self):
        return self

    def wait_window(self):
        loop = ensure_app()
        while self.isVisible() and not getattr(self, "_closed", False):
            loop.processEvents()
        return self


class Toplevel(QDialog, WindowMixin):
    def __init__(self, parent=None, **kwargs):
        ensure_app()
        super().__init__(parent)
        self._closed = False
        self._close_callback = None
        self._brand_icon_applied = False
        self._app_font = QFont("Segoe UI", 11)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.style = DummyStyle()
        self.setModal(False)

    def closeEvent(self, event):
        if getattr(self, "_closed", False):
            event.accept()
            return
        self._destroying = True
        self._closed = True
        for ident in list(getattr(self, "_after_timers", {})):
            self.after_cancel(ident)
        cb = getattr(self, "_close_callback", None)
        self._close_callback = None
        if cb:
            try:
                cb()
            except Exception:
                pass
        event.accept()

    def iconbitmap(self, path):
        try:
            self.setWindowIcon(QIcon(str(path)))
            self._brand_icon_applied = True
        except Exception:
            self._brand_icon_applied = False
        return self

    def winfo_toplevel(self):
        return self

    def transient(self, parent=None):
        if parent is not None:
            self.setParent(parent)
            self.setWindowFlag(Qt.Dialog, True)
        return self

    def grab_set(self):
        self.setModal(True)
        return self

    def wait_window(self):
        self.exec()
        return self

    def resizable(self, w=True, h=True):
        if not w and not h:
            self.setFixedSize(self.size())
        return self

    def geometry(self, spec=None):
        if spec is None:
            size = self.size()
            return "%sx%s" % (size.width(), size.height())
        pos = None
        size = None
        body = spec
        if "+" in spec:
            parts = spec.replace("-", "+-").split("+")
            body = parts[0]
            if len(parts) >= 3:
                pos = (int(parts[1] or 0), int(parts[2] or 0))
            elif len(parts) == 2 and not body:
                pos = (int(parts[1] or 0), self.y())
        if "x" in body.lower() and body:
            w, h = body.lower().split("x")
            size = (int(w), int(h))
        if size:
            self.resize(*size)
        if pos:
            self.move(*pos)
        return spec

    def bind(self, event, callback):
        if event == "<Escape>":
            self._escape_cb = callback
        return self

    def deiconify(self):
        self.show()
        return self

    def withdraw(self):
        self.hide()
        return self

    def lift(self):
        self.raise_()
        self.activateWindow()
        return self

    def attributes(self, *args, **kwargs):
        if args and args[0] == "-topmost":
            self.setWindowFlag(Qt.WindowStaysOnTopHint, bool(args[1]) if len(args) > 1 else True)
        return self

    def overrideredirect(self, flag=True):
        self.setWindowFlag(Qt.FramelessWindowHint, bool(flag))
        return self

    def winfo_screenwidth(self):
        screen = QGuiApplication.primaryScreen()
        return screen.geometry().width() if screen else 1920

    def winfo_screenheight(self):
        screen = QGuiApplication.primaryScreen()
        return screen.geometry().height() if screen else 1080

    def winfo_exists(self):
        return not self._closed

    def destroy(self):
        self._closed = True
        self.close()


Dialog = Toplevel


class ttk:
    Frame = Frame
    Label = Label
    Button = Button
    Entry = Entry
    Checkbutton = Checkbutton
    Combobox = Combobox
    Scale = Scale
    Notebook = Notebook
    Treeview = Treeview
    Labelframe = Labelframe
    Scrollbar = Scrollbar
    Separator = Separator
    PanedWindow = PanedWindow


WindowMixin.iconbitmap = Window.iconbitmap
WindowMixin.winfo_toplevel = Window.winfo_toplevel

def _listbox_init(self, parent=None, height=None, **kwargs):
    parent = _reparent(parent)
    QListWidget.__init__(self, parent)
    if height:
        self.setMinimumHeight(int(height) * 18)


Listbox.__init__ = _listbox_init


def _text_init(self, parent=None, height=None, wrap="word", font=None, **kwargs):
    parent = _reparent(parent)
    QTextEdit.__init__(self, parent)
    self._tags = {}
    self._mono = False
    if height:
        self.setMinimumHeight(int(height) * 18)
    if wrap == "word":
        self.setLineWrapMode(QTextEdit.WidgetWidth)
    if font:
        self.setFont(_qfont(font))


Text.__init__ = _text_init


def _scale_init(self, parent=None, from_=0, to=3, variable=None, orient="horizontal", command=None, **kwargs):
    parent = _reparent(parent)
    orientation = Qt.Horizontal if orient != "vertical" else Qt.Vertical
    QSlider.__init__(self, orientation, parent)
    self.setRange(int(from_), int(to))
    self._var = variable
    self._command = command
    if variable is not None:
        self.setValue(int(variable.get()))
        variable._widgets.append(self)
        self.valueChanged.connect(self._on_changed)


Scale.__init__ = _scale_init


def _tree_init(self, parent=None, columns=(), show="headings", height=8, **kwargs):
    parent = _reparent(parent)
    QTreeWidget.__init__(self, parent)
    self.setColumnCount(len(columns))
    self.setHeaderLabels(list(columns))
    self.setRootIsDecorated(False)
    self.setSelectionMode(QTreeWidget.SingleSelection)
    self._columns = list(columns)
    if height:
        self.setMinimumHeight(int(height) * 22)


Treeview.__init__ = _tree_init


def _notebook_init(self, parent=None, **kwargs):
    parent = _reparent(parent)
    QTabWidget.__init__(self, parent)
    self.setDocumentMode(True)
    self.setElideMode(Qt.ElideNone)
    self.tabBar().setDrawBase(False)
    self.tabBar().setExpanding(True)
    self.setMovable(False)


Notebook.__init__ = _notebook_init


def _labelframe_init(self, parent=None, text="", **kwargs):
    parent = _reparent(parent)
    QFrame.__init__(self, parent)
    self.setObjectName("cardPanel")
    self.setFrameShape(QFrame.NoFrame)
    layout = QVBoxLayout(self)
    layout.setContentsMargins(10, 8, 10, 10)
    layout.setSpacing(6)
    self._title = QLabel(text)
    self._title.setStyleSheet("font-weight: 600; color: #3B82F6; background: transparent;")
    layout.addWidget(self._title)


Labelframe.__init__ = _labelframe_init


def _tkgeom_columnconfigure(self, index, weight=0, **kwargs):
    from PySide6.QtWidgets import QGridLayout
    layout = self.layout()
    if layout is None:
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
    if hasattr(layout, "setColumnStretch"):
        layout.setColumnStretch(int(index), int(weight or 0))
    return self


def _tkgeom_rowconfigure(self, index, weight=0, **kwargs):
    from PySide6.QtWidgets import QGridLayout
    layout = self.layout()
    if layout is None:
        layout = QGridLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
    if hasattr(layout, "setRowStretch"):
        layout.setRowStretch(int(index), int(weight or 0))
    return self


TkGeom.columnconfigure = _tkgeom_columnconfigure
TkGeom.rowconfigure = _tkgeom_rowconfigure


_orig_canvas_configure = Canvas.configure


def _canvas_configure(self, **kwargs):
    kwargs.pop("scrollregion", None)
    kwargs.pop("highlightthickness", None)
    kwargs.pop("highlightbackground", None)
    return _orig_canvas_configure(self, **kwargs)


Canvas.configure = _canvas_configure
Canvas.config = _canvas_configure


def _toplevel_keypress(self, event):
    cb = getattr(self, "_escape_cb", None)
    if cb and event.key() == Qt.Key_Escape:
        cb()
        return
    QDialog.keyPressEvent(self, event)


Toplevel.keyPressEvent = _toplevel_keypress

for _name in (
    "after",
    "after_cancel",
    "update_idletasks",
    "update",
    "winfo_exists",
    "protocol",
    "StringVar",
    "BooleanVar",
    "IntVar",
    "mainloop",
    "title",
    "geometry",
    "minsize",
    "destroy",
    "font",
):
    setattr(Window, _name, getattr(WindowMixin, _name))
    setattr(Toplevel, _name, getattr(Toplevel, _name, getattr(WindowMixin, _name)))


def _tkgeom_master_get(self):
    return self.parent()


TkGeom.master = property(_tkgeom_master_get)


def _after_guarded(self, ms, callback=None):
    timer = QTimer(self)
    timer.setSingleShot(True)

    def _run():
        if getattr(self, "_closed", False):
            return
        if callback:
            callback()

    if callback:
        timer.timeout.connect(_run)
    timer.start(int(ms))
    ident = id(timer)
    if not hasattr(self, "_after_timers"):
        self._after_timers = {}
    self._after_timers[ident] = timer
    return ident


def _destroy_guarded(self):
    if getattr(self, "_closed", False):
        try:
            self.hide()
            self.close()
        except Exception:
            pass
        return
    self._destroying = True
    self._closed = True
    for ident in list(getattr(self, "_after_timers", {})):
        self.after_cancel(ident)
    cb = getattr(self, "_close_callback", None)
    self._close_callback = None
    if cb:
        try:
            cb()
        except Exception:
            pass
    try:
        self.hide()
        self.close()
    except Exception:
        pass


WindowMixin.after = _after_guarded
WindowMixin.destroy = _destroy_guarded
Toplevel.destroy = _destroy_guarded
