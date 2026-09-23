#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Operation box behavior checks."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from app import AIMarkerApp
from models import AppConfig, RegionBox, config_from_dict, normalize_operation_boxes


ROOT = Path(__file__).resolve().parent


class FakeTree:
    def __init__(self, selected: list[str] | None = None) -> None:
        self.selected = selected or []
        self.rows: list[tuple[str, tuple[object, ...]]] = []

    def selection(self) -> list[str]:
        return list(self.selected)

    def selection_set(self, iid: str) -> None:
        self.selected = [iid]

    def see(self, _iid: str) -> None:
        pass

    def delete(self, *_items: object) -> None:
        self.rows.clear()

    def get_children(self) -> list[str]:
        return [iid for iid, _values in self.rows]

    def insert(self, _parent: str, _index: str, iid: str, values: tuple[object, ...]) -> None:
        self.rows.append((iid, values))


class FakeFloatingBoxes:
    def __init__(self) -> None:
        self.synced: list[list[str]] = []
        self.visible = False
        self.raised = 0
        self.hidden = 0

    def sync(self, boxes: list[RegionBox]) -> None:
        self.synced.append([box.kind for box in boxes])

    def show(self) -> None:
        self.visible = True

    def hide(self) -> None:
        self.visible = False
        self.hidden += 1

    def raise_kind(self, _kind: str) -> None:
        self.raised += 1


def box(kind: str, x: int) -> RegionBox:
    return RegionBox(f"{kind}-{x}", kind, x, 20, 100, 40, "#123456")


def fake_app(boxes: list[RegionBox], selected: list[str] | None = None) -> SimpleNamespace:
    app = SimpleNamespace()
    app.config_data = AppConfig(boxes=boxes)
    app.box_tree = FakeTree(selected)
    app.floating_boxes = FakeFloatingBoxes()
    app.status_messages = []
    app.saved = 0
    app.set_status = app.status_messages.append
    app._save_boxes = lambda: setattr(app, "saved", app.saved + 1)
    app.refresh_boxes = lambda: AIMarkerApp.refresh_boxes(app)
    app.show_floating_boxes = lambda: app.floating_boxes.show()
    return app


def test_normalize_operation_boxes_keeps_first_box_per_kind() -> None:
    boxes = [
        box("recognition", 10),
        box("score", 20),
        box("recognition", 30),
        box("submit", 40),
        box("score", 50),
        box("custom", 60),
    ]

    normalized = normalize_operation_boxes(boxes)

    assert [item.kind for item in normalized] == ["recognition", "score", "submit", "custom"]
    assert [item.x for item in normalized] == [10, 20, 40, 60]


def test_config_from_dict_normalizes_duplicate_operation_boxes() -> None:
    config = config_from_dict(
        {
            "boxes": [
                box("recognition", 10).__dict__,
                box("recognition", 30).__dict__,
                box("score", 20).__dict__,
                box("submit", 40).__dict__,
                box("submit", 80).__dict__,
            ]
        }
    )

    assert [item.kind for item in config.boxes] == ["recognition", "score", "submit"]
    assert [item.x for item in config.boxes] == [10, 20, 40]


def test_add_box_reuses_existing_kind_instead_of_appending() -> None:
    existing = box("score", 20)
    app = fake_app([existing])

    AIMarkerApp.add_box(app, "score")

    assert app.config_data.boxes == [existing]
    assert app.box_tree.selection() == ["0"]
    assert app.floating_boxes.visible is True
    assert app.floating_boxes.raised == 1


def test_delete_selected_box_removes_box_and_syncs_floating_boxes() -> None:
    app = fake_app([box("recognition", 10), box("score", 20), box("submit", 30)], ["1"])

    AIMarkerApp.delete_selected_box(app)

    assert [item.kind for item in app.config_data.boxes] == ["recognition", "submit"]
    assert app.saved == 1
    assert app.floating_boxes.synced[-1] == ["recognition", "submit"]


def test_floating_boxes_do_not_draw_opaque_fill_blocks() -> None:
    source = (ROOT / "overlay.py").read_text(encoding="utf-8")

    assert "create_rectangle(6, 6" not in source
    assert "create_rectangle(w - 18" not in source
    assert 'fill="white"' not in source


def test_floating_boxes_are_edges_not_full_panel_windows() -> None:
    source = (ROOT / "overlay.py").read_text(encoding="utf-8")

    assert "self.edges" in source
    assert "tk.Canvas(self.window" not in source
    assert 'geometry(f"{self.box.width}x{self.box.height}' not in source


def test_app_startup_does_not_show_floating_boxes_by_default() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    init_block = source.split("    def _create_section_title", 1)[0]

    assert "self._ensure_floating_boxes()" in init_block
    assert "self.floating_boxes.show()" not in init_block


def test_floating_box_manager_defaults_to_hidden() -> None:
    source = (ROOT / "overlay.py").read_text(encoding="utf-8")

    assert "self.visible = False" in source


def test_hide_floating_boxes_never_requests_auto_restore() -> None:
    app = fake_app([box("recognition", 10)])
    app.floating_boxes.visible = True
    app.update_idletasks = lambda: None

    should_restore = AIMarkerApp._hide_floating_boxes_temporarily(app)

    assert should_restore is False
    assert app.floating_boxes.visible is False
    assert app.floating_boxes.hidden == 1


if __name__ == "__main__":
    test_normalize_operation_boxes_keeps_first_box_per_kind()
    test_config_from_dict_normalizes_duplicate_operation_boxes()
    test_add_box_reuses_existing_kind_instead_of_appending()
    test_delete_selected_box_removes_box_and_syncs_floating_boxes()
    test_floating_boxes_do_not_draw_opaque_fill_blocks()
    test_floating_boxes_are_edges_not_full_panel_windows()
    test_app_startup_does_not_show_floating_boxes_by_default()
    test_floating_box_manager_defaults_to_hidden()
    test_hide_floating_boxes_never_requests_auto_restore()
    print("[OK] operation box checks passed")
