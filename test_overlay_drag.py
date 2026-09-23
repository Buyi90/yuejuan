from pathlib import Path


def test_box_visual_uses_a_soft_tint_and_dashed_high_contrast_border():
    from overlay import draw_box_visual

    class CanvasProbe:
        def __init__(self):
            self.calls = []

        def delete(self, tag):
            self.calls.append(("delete", tag))

        def create_rectangle(self, *args, **kwargs):
            self.calls.append(("rectangle", args, kwargs))

    canvas = CanvasProbe()
    draw_box_visual(canvas, width=520, height=280, color="#e85d68")

    _, bounds, style = canvas.calls[-1]
    assert bounds == (4, 4, 516, 276)
    assert style["fill"] == "#fce7e8"
    assert style["outline"] == "#e85d68"
    assert style["width"] == 7
    assert style["dash"] == (14, 8)


def test_floating_boxes_keep_full_interior_drag_and_edge_resize_targets():
    source = Path(__file__).with_name("overlay.py").read_text(encoding="utf-8")

    assert "self.drag_window = self._make_drag_window()" in source
    assert 'canvas.bind("<ButtonPress-1>", lambda event: self.on_down(event, "body"))' in source
    assert 'drag.attributes("-alpha", 0.92)' in source
    assert 'drag.attributes("-transparentcolor", TRANSPARENT_KEY)' in source
    assert 'self.drag_window.geometry(f"{w}x{h}+{x}+{y}")' in source
    assert 'self.mode = "resize" if part in {"bottom", "right"} else "move"' in source
