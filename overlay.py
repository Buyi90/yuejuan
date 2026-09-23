from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QEvent
from PySide6.QtGui import QCursor, QMouseEvent
from PySide6.QtWidgets import QWidget

from models import OPERATION_BOX_KINDS, RegionBox, normalize_operation_boxes


EDGE_THICKNESS = 4


class EdgeWindow(QWidget):
    def __init__(self, owner: "FloatingBoxWindow", name: str, color: str) -> None:
        super().__init__(None)
        self.owner = owner
        self.part = name
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.WindowDoesNotAcceptFocus)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setStyleSheet("background-color: %s;" % color)
        self.hide()

    def set_color(self, color: str) -> None:
        self.setStyleSheet("background-color: %s;" % color)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        self.owner.on_down(_cursor_xy(), self.part)
        event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        self.owner.on_move(_cursor_xy())
        event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self.owner.on_up(_cursor_xy())
        event.accept()


def _cursor_xy() -> tuple[int, int]:
    pos = QCursor.pos()
    return int(pos.x()), int(pos.y())


class FloatingBoxWindow:
    def __init__(
        self,
        master,
        box: RegionBox,
        on_change: Callable[[], None],
        on_commit: Callable[[], None],
    ) -> None:
        self.master = master
        self.box = box
        self.on_change = on_change
        self.on_commit = on_commit
        self.mode = "move"
        self.start = (0, 0)
        self.original: RegionBox | None = None
        self.edges = {name: EdgeWindow(self, name, box.color) for name in ("top", "bottom", "left", "right")}
        self.sync()

    def sync(self) -> None:
        x = max(0, self.box.x)
        y = max(0, self.box.y)
        w = max(EDGE_THICKNESS * 2, self.box.width)
        h = max(EDGE_THICKNESS * 2, self.box.height)
        t = EDGE_THICKNESS
        self.box.x, self.box.y, self.box.width, self.box.height = x, y, w, h
        color = self.box.color
        for edge in self.edges.values():
            edge.set_color(color)
        self.edges["top"].setGeometry(x, y, w, t)
        self.edges["bottom"].setGeometry(x, y + h - t, w, t)
        self.edges["left"].setGeometry(x, y, t, h)
        self.edges["right"].setGeometry(x + w - t, y, t, h)

    def show(self) -> None:
        for edge in self.edges.values():
            edge.show()
            edge.raise_()

    def hide(self) -> None:
        for edge in self.edges.values():
            edge.hide()

    def destroy(self) -> None:
        for edge in self.edges.values():
            edge.close()
            edge.deleteLater()
        self.edges.clear()

    def on_down(self, pos: tuple[int, int], part: str) -> None:
        self.start = pos
        self.original = RegionBox(
            self.box.name,
            self.box.kind,
            self.box.x,
            self.box.y,
            self.box.width,
            self.box.height,
            self.box.color,
            self.box.enabled,
        )
        self.mode = "resize" if part in {"bottom", "right"} else "move"

    def on_move(self, pos: tuple[int, int]) -> None:
        if self.original is None:
            return
        dx = pos[0] - self.start[0]
        dy = pos[1] - self.start[1]
        if self.mode == "resize":
            self.box.width = max(30, self.original.width + dx)
            self.box.height = max(20, self.original.height + dy)
        else:
            self.box.x = max(0, self.original.x + dx)
            self.box.y = max(0, self.original.y + dy)
        self.sync()
        self.on_change()

    def on_up(self, _pos: tuple[int, int]) -> None:
        self.original = None
        self.on_commit()


class FloatingBoxManager:
    def __init__(
        self,
        master,
        boxes: list[RegionBox],
        on_change: Callable[[], None],
        on_commit: Callable[[], None],
    ) -> None:
        self.master = master
        self.on_change = on_change
        self.on_commit = on_commit
        self.visible = False
        self.windows: dict[str, FloatingBoxWindow] = {}
        self.sync(boxes)

    def sync(self, boxes: list[RegionBox]) -> None:
        boxes = normalize_operation_boxes(boxes)
        current = {box.kind: box for box in boxes if box.enabled and box.kind in OPERATION_BOX_KINDS}
        for kind in list(self.windows):
            if kind not in current:
                self.windows.pop(kind).destroy()
        for kind, box in current.items():
            if kind in self.windows:
                self.windows[kind].box = box
                self.windows[kind].sync()
            else:
                self.windows[kind] = FloatingBoxWindow(self.master, box, self.on_change, self.on_commit)
        if self.visible:
            self.show()
        else:
            self.hide()

    def show(self) -> None:
        self.visible = True
        for window in self.windows.values():
            window.show()

    def hide(self) -> None:
        self.visible = False
        for window in self.windows.values():
            window.hide()

    def toggle(self) -> bool:
        if self.visible:
            self.hide()
        else:
            self.show()
        return self.visible

    def raise_kind(self, kind: str) -> None:
        window = self.windows.get(kind)
        if window:
            window.show()

    def destroy(self) -> None:
        for window in list(self.windows.values()):
            window.destroy()
        self.windows.clear()


RegionOverlay = FloatingBoxManager
