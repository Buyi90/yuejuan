#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""连续批改暂停快捷键：未批阅无效，开始后可暂停/继续。"""

from __future__ import annotations

import inspect
import threading
import time
from pathlib import Path
from types import SimpleNamespace

from hotkeys import PauseHotkeyWatcher, parse_hotkey
from models import Workflow, config_from_dict
from app import AIMarkerApp


ROOT = Path(__file__).resolve().parent
VK_CONTROL = 0x11
VK_SHIFT = 0x10
VK_F8 = 0x77
VK_P = 0x50
KEY_DOWN = 0x8000


def test_default_pause_hotkey_is_f8() -> None:
    assert Workflow().pause_hotkey == "F8"
    cfg = config_from_dict({"workflow": {}})
    assert cfg.workflow.pause_hotkey == "F8"


def test_pause_hotkey_is_normalized_when_loading_config() -> None:
    cfg = config_from_dict({"workflow": {"pause_hotkey": "ctrl + shift + p"}})
    assert cfg.workflow.pause_hotkey == "Ctrl+Shift+P"
    assert cfg.to_dict()["workflow"]["pause_hotkey"] == "Ctrl+Shift+P"


def test_invalid_pause_hotkey_falls_back_to_f8() -> None:
    cfg = config_from_dict({"workflow": {"pause_hotkey": "not-a-key"}})
    assert cfg.workflow.pause_hotkey == "F8"
    cfg = config_from_dict({"workflow": {"pause_hotkey": ""}})
    assert cfg.workflow.pause_hotkey == "F8"


def test_parse_hotkey_f8_and_modifiers() -> None:
    f8 = parse_hotkey("F8")
    assert f8.display == "F8"
    assert f8.vk == VK_F8
    assert f8.ctrl is False
    assert f8.shift is False
    combo = parse_hotkey("ctrl + shift + p")
    assert combo.display == "Ctrl+Shift+P"
    assert combo.vk == VK_P
    assert combo.ctrl is True
    assert combo.shift is True
    assert combo.alt is False


def _watcher(active: bool = True, spec: str = "F8"):
    triggers: list[int] = []
    pressed: dict[int, int] = {}

    def get_async_key_state(vk: int) -> int:
        return pressed.get(vk, 0)

    watcher = PauseHotkeyWatcher(
        get_spec=lambda: spec,
        on_trigger=lambda: triggers.append(1),
        is_active=lambda: active,
        get_async_key_state=get_async_key_state,
        poll_interval=0.01,
    )
    return watcher, triggers, pressed


def test_watcher_triggers_once_on_key_edge_when_active() -> None:
    watcher, triggers, pressed = _watcher(active=True, spec="F8")
    watcher.poll_once()
    assert triggers == []
    pressed[VK_F8] = KEY_DOWN
    watcher.poll_once()
    watcher.poll_once()
    assert triggers == [1]
    pressed[VK_F8] = 0
    watcher.poll_once()
    pressed[VK_F8] = KEY_DOWN
    watcher.poll_once()
    assert triggers == [1, 1]


def test_watcher_ignores_hotkey_when_inactive() -> None:
    watcher, triggers, pressed = _watcher(active=False, spec="Ctrl+Shift+P")
    pressed[VK_CONTROL] = KEY_DOWN
    pressed[VK_SHIFT] = KEY_DOWN
    pressed[VK_P] = KEY_DOWN
    watcher.poll_once()
    watcher.poll_once()
    assert triggers == []


def _pause_app(**kwargs):
    status: list[str] = []
    configs: list[dict] = []
    app = SimpleNamespace(
        running=False,
        continuous=False,
        paused=False,
        loop_count=0,
        status_messages=status,
        config_data=SimpleNamespace(
            workflow=SimpleNamespace(
                pause_hotkey="F8",
                target_count=0,
                target_count_enabled=False,
            )
        ),
        progress_var=SimpleNamespace(set=lambda value: configs.append(value)),
        pause_button=SimpleNamespace(texts=[], configure=lambda **kw: configs.append(kw)),
    )
    app.set_status = status.append
    app._refresh_pause_button = lambda: AIMarkerApp._refresh_pause_button(app)
    for key, value in kwargs.items():
        setattr(app, key, value)
    return app, status


def test_toggle_pause_ignored_before_grading() -> None:
    app, status = _pause_app(running=False, continuous=False, paused=False)
    AIMarkerApp.toggle_pause(app)
    assert app.paused is False
    assert status == []


def test_toggle_pause_switches_during_continuous_grading() -> None:
    app, status = _pause_app(running=True, continuous=True, paused=False)
    AIMarkerApp.toggle_pause(app)
    assert app.paused is True
    assert any("暂停" in text for text in status)
    AIMarkerApp.toggle_pause(app)
    assert app.paused is False
    assert any("继续" in text for text in status)


def test_stop_clears_paused_flag() -> None:
    app, status = _pause_app(running=True, continuous=True, paused=True, loop_count=2)
    AIMarkerApp.stop(app)
    assert app.running is False
    assert app.continuous is False
    assert app.paused is False
    assert "已停止" in status


def test_wait_if_paused_returns_immediately_when_not_paused() -> None:
    app = SimpleNamespace(paused=False, running=True)
    start = time.monotonic()
    AIMarkerApp._wait_if_paused(app)
    assert time.monotonic() - start < 0.05


def test_wait_if_paused_exits_when_stopped() -> None:
    app = SimpleNamespace(paused=True, running=True)

    def stop_soon() -> None:
        time.sleep(0.04)
        app.running = False

    thread = threading.Thread(target=stop_soon)
    thread.start()
    start = time.monotonic()
    AIMarkerApp._wait_if_paused(app)
    thread.join()
    assert time.monotonic() - start < 0.5


def test_loop_and_grade_wait_for_pause() -> None:
    loop_source = inspect.getsource(AIMarkerApp._loop_worker)
    grade_source = inspect.getsource(AIMarkerApp._grade_once_worker)
    stop_source = inspect.getsource(AIMarkerApp.stop)
    start_source = inspect.getsource(AIMarkerApp._start_continuous_grading)
    close_source = inspect.getsource(AIMarkerApp.on_close)
    assert "_wait_if_paused" in loop_source
    assert "_wait_if_paused" in grade_source
    assert "paused" in stop_source
    assert "paused" in start_source
    assert "hotkey" in close_source.lower() or "pause_hotkey_watcher" in close_source


def test_ui_exposes_bindable_pause_hotkey() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "暂停快捷键" in source
    assert "toggle_pause" in source
    assert "pause_hotkey" in source
    assert "PauseHotkeyWatcher" in source
    assert "暂停" in source
    hotkeys = (ROOT / "hotkeys.py").read_text(encoding="utf-8")
    assert "GetAsyncKeyState" in hotkeys or "get_async_key_state" in hotkeys


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"all {len(tests)} tests passed")
