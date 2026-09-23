#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""针对窗口关闭和后台服务商操作的轻量回归检查。"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")


def test_window_close_state_is_initialized_before_callbacks() -> None:
    init_start = SOURCE.index("class AIMarkerApp")
    init_end = SOURCE.index("    def _create_card", init_start)
    init_block = SOURCE[init_start:init_end]
    assert "self._closed = False" in init_block
    assert "self._destroying = False" in init_block


def test_provider_actions_restore_buttons_on_all_queue_outcomes() -> None:
    poll_start = SOURCE.index("    def _poll_queue")
    poll_end = SOURCE.index("    def _show_result", poll_start)
    poll_block = SOURCE[poll_start:poll_end]
    assert "self._finish_provider_action(\"模型获取完成\")" in poll_block
    assert "self._finish_provider_action(\"操作失败\")" in poll_block
    assert "self._finish_provider_action(\"服务商测试完成\")" in poll_block


def test_provider_busy_guard_is_present() -> None:
    assert "def _finish_provider_action" in SOURCE
    assert "self._provider_action_busy = False" in SOURCE
    assert "button.setEnabled(True)" in SOURCE


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"PASS {name}")
    print("all runtime safety tests passed")
