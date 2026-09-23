#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""全局暂停快捷键：用 Windows GetAsyncKeyState 轮询，不额外装依赖。"""

from __future__ import annotations

from dataclasses import dataclass
import re
import threading
from collections.abc import Callable


VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12  # Alt
KEY_DOWN = 0x8000
DEFAULT_HOTKEY = "F8"

# 常用功能键，方便用户自己绑定。
_NAMED_KEYS = {
    "space": ("Space", 0x20),
    "tab": ("Tab", 0x09),
    "enter": ("Enter", 0x0D),
    "return": ("Enter", 0x0D),
    "esc": ("Esc", 0x1B),
    "escape": ("Esc", 0x1B),
    "pause": ("Pause", 0x13),
    "ins": ("Insert", 0x2D),
    "insert": ("Insert", 0x2D),
    "del": ("Delete", 0x2E),
    "delete": ("Delete", 0x2E),
    "home": ("Home", 0x24),
    "end": ("End", 0x23),
    "pageup": ("PageUp", 0x21),
    "pgup": ("PageUp", 0x21),
    "pagedown": ("PageDown", 0x22),
    "pgdn": ("PageDown", 0x22),
    "up": ("Up", 0x26),
    "down": ("Down", 0x28),
    "left": ("Left", 0x25),
    "right": ("Right", 0x27),
}
_MODIFIER_ALIASES = {
    "ctrl": "ctrl",
    "control": "ctrl",
    "ctl": "ctrl",
    "shift": "shift",
    "alt": "alt",
    "option": "alt",
}


@dataclass(frozen=True)
class HotkeySpec:
    """解析后的快捷键：显示名、虚拟键码和修饰键。"""

    display: str
    vk: int
    ctrl: bool = False
    shift: bool = False
    alt: bool = False


def _win_get_async_key_state(vk: int) -> int:
    import ctypes

    return int(ctypes.windll.user32.GetAsyncKeyState(vk))


def _parse_main_key(token: str) -> tuple[str, int]:
    name = token.strip()
    if not name:
        raise ValueError("empty key")
    lowered = name.lower()
    function_key = re.fullmatch(r"f(\d{1,2})", lowered)
    if function_key:
        index = int(function_key.group(1))
        if 1 <= index <= 24:
            return f"F{index}", 0x70 + index - 1
        raise ValueError(f"unsupported function key: {name}")
    if lowered in _NAMED_KEYS:
        return _NAMED_KEYS[lowered]
    if re.fullmatch(r"[a-z]", lowered):
        letter = lowered.upper()
        return letter, ord(letter)
    if re.fullmatch(r"[0-9]", lowered):
        return lowered, ord(lowered)
    raise ValueError(f"unsupported key: {name}")


def parse_hotkey(spec: str) -> HotkeySpec:
    """把 'ctrl + shift + p' 这类文本解析成规范化快捷键。"""
    raw = str(spec or "").strip()
    if not raw:
        raise ValueError("empty hotkey")
    tokens = [item.strip() for item in re.split(r"[+\s]+", raw) if item.strip()]
    if not tokens:
        raise ValueError("empty hotkey")

    ctrl = shift = alt = False
    main: tuple[str, int] | None = None
    for token in tokens:
        modifier = _MODIFIER_ALIASES.get(token.lower())
        if modifier == "ctrl":
            ctrl = True
            continue
        if modifier == "shift":
            shift = True
            continue
        if modifier == "alt":
            alt = True
            continue
        if main is not None:
            raise ValueError(f"multiple keys in hotkey: {raw}")
        main = _parse_main_key(token)
    if main is None:
        raise ValueError(f"missing key in hotkey: {raw}")

    parts: list[str] = []
    if ctrl:
        parts.append("Ctrl")
    if alt:
        parts.append("Alt")
    if shift:
        parts.append("Shift")
    parts.append(main[0])
    return HotkeySpec(display="+".join(parts), vk=main[1], ctrl=ctrl, shift=shift, alt=alt)


def normalize_hotkey(spec: str, default: str = DEFAULT_HOTKEY) -> str:
    """配置保存/读取时用：非法快捷键回退到 F8。"""
    try:
        return parse_hotkey(spec).display
    except Exception:
        return parse_hotkey(default).display


class PauseHotkeyWatcher:
    """后台轮询全局按键；未批阅时 is_active 为假，按了也不会触发。"""

    def __init__(
        self,
        get_spec: Callable[[], str],
        on_trigger: Callable[[], None],
        is_active: Callable[[], bool],
        get_async_key_state: Callable[[int], int] | None = None,
        poll_interval: float = 0.05,
    ) -> None:
        self.get_spec = get_spec
        self.on_trigger = on_trigger
        self.is_active = is_active
        self.get_async_key_state = get_async_key_state or _win_get_async_key_state
        self.poll_interval = max(0.01, float(poll_interval))
        self._held = False
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()

    def _combo_pressed(self, spec: HotkeySpec) -> bool:
        if not (self.get_async_key_state(spec.vk) & KEY_DOWN):
            return False
        ctrl = bool(self.get_async_key_state(VK_CONTROL) & KEY_DOWN)
        shift = bool(self.get_async_key_state(VK_SHIFT) & KEY_DOWN)
        alt = bool(self.get_async_key_state(VK_MENU) & KEY_DOWN)
        return ctrl == spec.ctrl and shift == spec.shift and alt == spec.alt

    def poll_once(self) -> None:
        try:
            spec = parse_hotkey(self.get_spec())
        except Exception:
            self._held = False
            return
        pressed = self._combo_pressed(spec)
        if not self.is_active():
            self._held = pressed
            return
        if pressed and not self._held:
            self.on_trigger()
        self._held = pressed

    def start(self) -> None:
        with self._lock:
            if self._thread is not None and self._thread.is_alive():
                return
            self._stop.clear()
            self._held = False
            self._thread = threading.Thread(target=self._run, name="pause-hotkey", daemon=True)
            self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        if thread is not None and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=0.2)
        with self._lock:
            self._thread = None
            self._held = False

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.poll_once()
            except Exception:
                pass
            self._stop.wait(self.poll_interval)
