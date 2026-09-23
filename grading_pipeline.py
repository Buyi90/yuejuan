#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""C# 阅卷循环的 Python 实现：截图等待、分值重试、同页网络恢复、异常终止、翻页刷新。"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from models import AppConfig


_STEP_EPS = 1e-08
_SUM_EPS = 1e-06
_FATAL_NETWORK_MARKERS = (
    "401",
    "403",
    "unauthorized",
    "forbidden",
    "invalid api key",
    "invalid key",
    "quota",
)
_TRANSIENT_NETWORK_MARKERS = (
    "timed out",
    "timeout",
    "connection",
    "network",
    "503",
    "502",
    "504",
    "reset",
    "refused",
    "unreachable",
    "ssl",
    "broken pipe",
    "forcibly closed",
)


class GradingNetworkRecoverable(Exception):
    """Transient network failure: wait and retry the same card."""


@dataclass
class PipelineConfig:
    capture_delay: float = 0.15
    scoring_delay: float = 0.0
    next_paper_delay: float = 0.2
    delay_seconds: float = 0.2
    retry_limit: int = 5
    max_score: float = 10.0
    min_score: float = 0.0
    step: float = 1.0
    score_points: int = 1
    enable_abnormal_termination: bool = False
    abnormal_termination_count: int = 10
    enable_page_refresh: bool = False
    page_refresh_frequency: int = 20
    page_refresh_hotkey: str = "F5"
    page_refresh_wait_seconds: float = 5.0
    target_count: int = 0
    blank_detection_enabled: bool = False


@dataclass
class CardOutcome:
    status: str
    result: dict[str, Any] = field(default_factory=dict)
    scores: list[float] = field(default_factory=list)


class GradingHooks:
    def capture(self) -> Any:
        raise NotImplementedError

    def is_blank(self, image: Any) -> bool:
        return False

    def grade(self, image: Any) -> dict[str, Any]:
        raise NotImplementedError

    def fill_and_submit(self, score, values=None) -> None:
        return None

    def sleep(self, seconds: float) -> None:
        return None

    def is_running(self) -> bool:
        return True

    def wait_if_paused(self) -> None:
        return None

    def send_hotkey(self, spec: str) -> bool:
        return False

    def log(self, message: str) -> None:
        return None

    def emit_status(self, text: str) -> None:
        return None

    def emit_result(self, result, image=None) -> None:
        return None

    def emit_progress(self, text: str) -> None:
        return None

    def emit_history(self) -> None:
        return None

    def emit_error(self, text: str) -> None:
        return None


def _as_float_list(scores: Any) -> list[float]:
    if not scores:
        return []
    values: list[float] = []
    for item in scores:
        values.append(float(item))
    return values


def _capture_key(image: Any) -> bytes | str:
    if image is None:
        return b""
    if isinstance(image, (bytes, bytearray, memoryview)):
        return bytes(image)
    tobytes = getattr(image, "tobytes", None)
    if callable(tobytes):
        mode = str(getattr(image, "mode", "") or "")
        size = str(getattr(image, "size", "") or "")
        return f"{mode}:{size}:".encode("ascii", "ignore") + tobytes()
    return image


def is_on_score_step(value: float, step: float) -> bool:
    if step <= 0:
        return True
    scaled = value / step
    return abs(scaled - round(scaled)) <= _STEP_EPS


def scores_meet_grading_constraints(
    scores: list[float] | None,
    max_score: float = 10.0,
    min_score: float = 0.0,
    step: float = 1.0,
    expected: int = 1,
) -> bool:
    if scores is None:
        return False
    expected_count = max(1, int(expected or 1))
    values = _as_float_list(scores)
    if len(values) != expected_count:
        return False
    for value in values:
        if value < min_score - _STEP_EPS or value > max_score + _STEP_EPS:
            return False
        if step > 0 and not is_on_score_step(value, step):
            return False
    if max_score > 0 and sum(values) > max_score + _SUM_EPS:
        return False
    return True


def score_signature(scores: list[float] | None) -> str:
    values = _as_float_list(scores)
    if not values:
        return ""
    parts: list[str] = []
    for value in values:
        text = f"{round(float(value), 6):.6f}".rstrip("0").rstrip(".")
        parts.append(text or "0")
    return "|".join(parts)


def update_same_score_streak(
    last_signature: str,
    streak: int,
    scores: list[float] | None,
    enabled: bool = True,
    threshold: int = 10,
) -> tuple[str, int, bool]:
    if not enabled:
        return "", 0, False
    limit = max(3, int(threshold or 0))
    signature = score_signature(scores)
    if not signature:
        return "", 0, False
    if last_signature == signature:
        streak = int(streak) + 1
    else:
        streak = 1
    return signature, streak, streak >= limit


def should_refresh_page(completed_count: int, enabled: bool = True, frequency: int = 20) -> bool:
    if not enabled:
        return False
    freq = max(1, int(frequency or 0))
    return completed_count > 0 and completed_count % freq == 0


def apply_retry_spacing_seconds(attempt: int, aggressive: bool = False) -> float:
    if attempt <= 1:
        return 0.0
    if aggressive:
        millis = min(600 + (attempt - 2) * 450, 10000)
    else:
        millis = min(200 + (attempt - 2) * 150, 2000)
    return millis / 1000.0


def network_recovery_wait_seconds(streak: int, delay_seconds: float = 0.5) -> float:
    wait = min(max(3.0, float(delay_seconds or 0.0)) * (1.75 ** max(0, streak - 1)), 120.0)
    return wait


def is_transient_network_error(exc: BaseException) -> bool:
    message = str(exc or "").lower()
    if any(marker in message for marker in _FATAL_NETWORK_MARKERS):
        return False
    if isinstance(exc, (TimeoutError, ConnectionError, ConnectionResetError, ConnectionRefusedError, ConnectionAbortedError, BrokenPipeError)):
        return True
    return any(marker in message for marker in _TRANSIENT_NETWORK_MARKERS)


def pipeline_config_from_app_config(cfg: AppConfig) -> PipelineConfig:
    scoring = cfg.scoring
    workflow = cfg.workflow
    units = list(scoring.units or [])
    max_score = float(scoring.max_score or 0)
    if units:
        max_score = sum(float(unit.max_score or 0) for unit in units) or max_score
    return PipelineConfig(
        capture_delay=float(workflow.capture_delay or 0),
        scoring_delay=float(workflow.scoring_delay or 0),
        next_paper_delay=float(workflow.next_paper_delay or 0),
        delay_seconds=float(workflow.next_paper_delay or 0),
        retry_limit=max(1, int(workflow.retry_limit or 5)),
        max_score=max_score,
        min_score=0.0,
        step=float(scoring.round_step or 0),
        score_points=len(units) if units else 1,
        enable_abnormal_termination=bool(getattr(workflow, "enable_abnormal_termination", False)),
        abnormal_termination_count=int(getattr(workflow, "abnormal_termination_count", 10) or 10),
        enable_page_refresh=bool(getattr(workflow, "enable_page_refresh", False)),
        page_refresh_frequency=int(getattr(workflow, "page_refresh_frequency", 20) or 20),
        page_refresh_hotkey=str(getattr(workflow, "page_refresh_hotkey", "F5") or "F5"),
        page_refresh_wait_seconds=float(getattr(workflow, "page_refresh_wait_seconds", 5.0) or 0),
        target_count=int(workflow.target_count or 0) if workflow.target_count_enabled else 0,
        blank_detection_enabled=bool(cfg.blank_detection_enabled),
    )


class GradingSession:
    def __init__(self, config: PipelineConfig, hooks: GradingHooks) -> None:
        self.config = config
        self.hooks = hooks
        self.previous_capture: Any = b""
        self.last_score_signature = ""
        self.same_score_streak = 0
        self.network_streak = 0
        self._retry_same_card = False

    def capture_for_grading(self, card_index: int, attempt: int) -> Any:
        previous = self.previous_capture
        retry_same_card = self._retry_same_card
        self._retry_same_card = False
        should_wait = (
            card_index >= 0
            and attempt == 1
            and not retry_same_card
            and previous is not None
            and previous != b""
            and previous != ""
        )
        same_count = 0
        while True:
            self.hooks.wait_if_paused()
            if not self.hooks.is_running():
                return b""
            image = self.hooks.capture()
            if (not should_wait) or image is None or image == b"" or image == "":
                self._remember_capture(image)
                return image
            if _capture_key(image) != _capture_key(previous):
                if same_count:
                    self.hooks.log(f"第 {card_index + 1} 份答题卡页面已刷新，继续阅卷。")
                self._remember_capture(image)
                return image
            same_count += 1
            self.hooks.log(f"第 {card_index + 1} 份答题卡截图与上一份完全相同，等待 1 秒再试（第 {same_count} 次）。")
            self.hooks.sleep(1.0)

    def wait_after_network_recovery(self) -> bool:
        self.network_streak += 1
        if self.network_streak > 30:
            self.hooks.log("网络连续等待恢复 30 次仍未成功，已自动停止阅卷。")
            self.hooks.emit_status("网络恢复等待超过上限，已停止")
            return False
        wait = network_recovery_wait_seconds(self.network_streak, self.config.delay_seconds)
        self.hooks.log(
            f"网络恢复等待约 {wait:g} 秒后自动重试当前份（第 {self.network_streak} 次等待，上限 30 次）。"
        )
        self.hooks.emit_status(f"网络波动，等待 {wait:g} 秒后重试当前份")
        self.hooks.sleep(wait)
        return self.hooks.is_running()

    def _remember_capture(self, image: Any) -> None:
        if image is None or image == b"" or image == "":
            return
        self.previous_capture = image

    def _blank_result(self) -> dict[str, Any]:
        return {
            "student_answer": "空白答题卡",
            "ai_score": 0,
            "final_score": 0,
            "comment": "空白答题卡，自动记 0 分",
            "is_blank_card": True,
            "sub_scores": [],
            "bonus": 0,
            "dual_eval": None,
        }

    def _maybe_fill(self, auto_submit: bool, result: dict[str, Any]) -> None:
        if not auto_submit:
            return
        score = result.get("final_score", 0)
        if score is None:
            return
        wait = max(0.0, float(self.config.scoring_delay or 0))
        if wait:
            self.hooks.sleep(wait)
            if not self.hooks.is_running():
                return
        values = [item.get("score") for item in result.get("sub_scores", []) if item.get("score") is not None]
        self.hooks.fill_and_submit(score, values or [score])

    def process_one(self, card_index: int, auto_submit: bool = True) -> CardOutcome:
        debug = card_index < 0 or not auto_submit
        if debug:
            self.hooks.emit_status("debug")
        retry_limit = max(1, int(self.config.retry_limit or 5))
        last_error = "AI 未返回有效分值"
        for attempt in range(1, retry_limit + 1):
            self.hooks.wait_if_paused()
            if not self.hooks.is_running():
                return CardOutcome(status="stopped")
            if attempt > 1:
                spacing = apply_retry_spacing_seconds(attempt)
                if spacing:
                    self.hooks.sleep(spacing)
            capture_wait = max(0.0, float(self.config.capture_delay or 0))
            if capture_wait:
                self.hooks.emit_status(f"等待取卡稳定 {capture_wait:g} 秒")
                self.hooks.sleep(capture_wait)
                if not self.hooks.is_running():
                    return CardOutcome(status="stopped")
            self.hooks.emit_status("正在截取识别区")
            image = self.capture_for_grading(card_index, attempt)
            if self.hooks.is_blank(image):
                result = self._blank_result()
                self._remember_capture(image)
                self.hooks.emit_result(result, image)
                self._maybe_fill(auto_submit, result)
                return CardOutcome(status="blank", result=result, scores=[0.0])
            try:
                payload = self.hooks.grade(image) or {}
            except Exception as exc:
                if is_transient_network_error(exc):
                    self._retry_same_card = True
                    raise GradingNetworkRecoverable(str(exc)) from exc
                last_error = str(exc)
                if attempt >= retry_limit:
                    raise
                continue
            scores = _as_float_list(payload.get("scores"))
            result = dict(payload.get("result") or {})
            if not scores_meet_grading_constraints(
                scores,
                max_score=self.config.max_score,
                min_score=self.config.min_score,
                step=self.config.step,
                expected=self.config.score_points,
            ):
                last_error = "分值不满足约束"
                self.hooks.log(f"第 {attempt}/{retry_limit} 次分值校验未通过，准备重试。")
                continue
            if result.get("final_score") is None:
                result["final_score"] = scores[0] if len(scores) == 1 else sum(scores)
            self._remember_capture(image)
            self.hooks.emit_result(result, image)
            self._maybe_fill(auto_submit, result)
            status = "debug" if debug else "ok"
            return CardOutcome(status=status, result=result, scores=scores)
        raise RuntimeError(last_error)

    def _handle_same_score_abort(self, scores: list[float], completed_count: int, target: int) -> bool:
        signature, streak, abort = update_same_score_streak(
            self.last_score_signature,
            self.same_score_streak,
            scores,
            enabled=self.config.enable_abnormal_termination,
            threshold=self.config.abnormal_termination_count,
        )
        self.last_score_signature = signature
        self.same_score_streak = streak
        if not abort:
            return False
        if target > 0 and completed_count >= target:
            return False
        message = f"触发异常终止：连续 {streak} 份分值一致（{signature}），已自动停止阅卷。"
        self.hooks.log(message)
        self.hooks.emit_status(message)
        return True

    def _refresh_page_if_needed(self, completed_count: int) -> None:
        if not should_refresh_page(
            completed_count,
            enabled=self.config.enable_page_refresh,
            frequency=self.config.page_refresh_frequency,
        ):
            return
        hotkey = self.config.page_refresh_hotkey or "F5"
        if not self.hooks.send_hotkey(hotkey):
            self.hooks.log(f"页面刷新热键无效（{hotkey}），已回退为 F5。")
            hotkey = "F5"
            self.hooks.send_hotkey(hotkey)
        self.hooks.log(f"已阅 {completed_count} 份，发送页面刷新：{hotkey}")
        wait = max(0.0, float(self.config.page_refresh_wait_seconds or 0))
        if wait:
            self.hooks.sleep(wait)

    def run_loop(self, target_count: int | None = None) -> None:
        target = self.config.target_count if target_count is None else int(target_count or 0)
        count = 0
        last_refresh = 0
        while self.hooks.is_running():
            self.hooks.wait_if_paused()
            if not self.hooks.is_running():
                break
            if target and count >= target:
                self.hooks.emit_status("已达到目标数量，自动停止")
                self.hooks.emit_history()
                break
            try:
                outcome = self.process_one(card_index=count, auto_submit=True)
            except GradingNetworkRecoverable as exc:
                self.hooks.log(f"第 {count + 1} 份遇到网络波动未完成（{exc}），等待后自动重试当前份。")
                if not self.wait_after_network_recovery():
                    break
                continue
            except Exception as exc:
                self.hooks.emit_error(str(exc))
                break
            self.network_streak = 0
            count += 1
            self.hooks.emit_progress(f"{count}/{target or '不限'}")
            if count - last_refresh >= 50:
                self.hooks.emit_history()
                last_refresh = count
            if self._handle_same_score_abort(outcome.scores, count, target):
                break
            self._refresh_page_if_needed(count)
            wait = max(0.0, float(self.config.next_paper_delay or 0))
            if wait:
                self.hooks.sleep(wait)
