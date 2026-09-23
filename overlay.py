from __future__ import annotations

import tkinter as tk
from typing import Callable

from models import OPERATION_BOX_KINDS, RegionBox, normalize_operation_boxes


EDGE_THICKNESS = 4
TRANSPARENT_KEY = "#010101"
BORDER_WIDTH = 7
BORDER_DASH = (14, 8)


def _soft_fill(color: str) -> str:
    """Blend a box color heavily toward white for a subtle interior tint."""
    value = color.lstrip("#")
    if len(value) != 6:
        return "#fbe4e6"
    channels = [int(value[index:index + 2], 16) for index in (0, 2, 4)]
    tinted = [round(channel * 0.15 + 255 * 0.85) for channel in channels]
    return "#" + "".join(f"{channel:02x}" for channel in tinted)


def draw_box_visual(canvas, width: int, height: int, color: str) -> None:
    """Draw the translucent-style fill and dashed perimeter on a Tk canvas."""
    canvas.delete("all")
    inset = (BORDER_WIDTH + 1) // 2
    canvas.create_rectangle(
        inset,
        inset,
        max(inset, width - inset),
        max(inset, height - inset),
        fill=_soft_fill(color),
        outline=color,
        width=BORDER_WIDTH,
        dash=BORDER_DASH,
    )


class FloatingBoxWindow:
    def __init__(
        self,
        master: tk.Tk,
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
        self.drag_window = self._make_drag_window()
        self.edges = {name: self._make_edge(name) for name in ("top", "bottom", "left", "right")}
        self.sync()

    def _make_drag_window(self) -> tk.Toplevel:
        drag = tk.Toplevel(self.master)
        drag.overrideredirect(True)
        drag.attributes("-topmost", True)
        drag.attributes("-alpha", 0.92)
        drag.attributes("-transparentcolor", TRANSPARENT_KEY)
        drag.configure(bg=TRANSPARENT_KEY)
        canvas = tk.Canvas(drag, bg=TRANSPARENT_KEY, bd=0, highlightthickness=0)
        canvas.pack(fill="both", expand=True)
        canvas.bind("<ButtonPress-1>", lambda event: self.on_down(event, "body"))
        canvas.bind("<B1-Motion>", self.on_move)
        canvas.bind("<ButtonRelease-1>", self.on_up)
        self.visual_canvas = canvas
        return drag

    def _make_edge(self, name: str) -> tk.Toplevel:
        edge = tk.Toplevel(self.master)
        edge.overrideredirect(True)
        edge.attributes("-topmost", True)
        # Keep the original edge hit targets/resizing, but let the dashed canvas render the border.
        edge.attributes("-alpha", 0.01)
        edge.configure(bg=self.box.color, cursor="bottom_right_corner" if name in {"bottom", "right"} else "fleur")
        edge.bind("<ButtonPress-1>", lambda event, part=name: self.on_down(event, part))
        edge.bind("<B1-Motion>", self.on_move)
        edge.bind("<ButtonRelease-1>", self.on_up)
        return edge

    def sync(self) -> None:
        x = max(0, self.box.x)
        y = max(0, self.box.y)
        w = max(EDGE_THICKNESS * 2, self.box.width)
        h = max(EDGE_THICKNESS * 2, self.box.height)
        t = EDGE_THICKNESS
        self.box.x, self.box.y, self.box.width, self.box.height = x, y, w, h
        color = self.box.color
        self.drag_window.configure(bg=TRANSPARENT_KEY)
        self.drag_window.geometry(f"{w}x{h}+{x}+{y}")
        draw_box_visual(self.visual_canvas, w, h, color)
        for edge in self.edges.values():
            edge.configure(bg=color)
        self.edges["top"].geometry(f"{w}x{t}+{x}+{y}")
        self.edges["bottom"].geometry(f"{w}x{t}+{x}+{y + h - t}")
        self.edges["left"].geometry(f"{t}x{h}+{x}+{y}")
        self.edges["right"].geometry(f"{t}x{h}+{x + w - t}+{y}")

    def show(self) -> None:
        self.drag_window.deiconify()
        self.drag_window.lift()
        for edge in self.edges.values():
            edge.deiconify()
            edge.lift()

    def hide(self) -> None:
        self.drag_window.withdraw()
        for edge in self.edges.values():
            edge.withdraw()

    def destroy(self) -> None:
        self.drag_window.destroy()
        for edge in self.edges.values():
            edge.destroy()

    def on_down(self, event, part: str) -> None:
        self.start = (event.x_root, event.y_root)
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

    def on_move(self, event) -> None:
        if self.original is None:
            return
        dx = event.x_root - self.start[0]
        dy = event.y_root - self.start[1]
        if self.mode == "resize":
            self.box.width = max(30, self.original.width + dx)
            self.box.height = max(20, self.original.height + dy)
        else:
            self.box.x = max(0, self.original.x + dx)
            self.box.y = max(0, self.original.y + dy)
        self.sync()
        self.on_change()

    def on_up(self, _event) -> None:
        self.original = None
        self.on_commit()


class FloatingBoxManager:
    def __init__(
        self,
        master: tk.Tk,
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
