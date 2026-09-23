#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""C# 阅卷流程移植：截图等待、分值约束重试、同页网络恢复、异常终止、翻页刷新。"""

from __future__ import annotations

from pathlib import Path

from grading_pipeline import (
    CardOutcome,
    GradingHooks,
    GradingNetworkRecoverable,
    GradingSession,
    PipelineConfig,
    apply_retry_spacing_seconds,
    is_transient_network_error,
    network_recovery_wait_seconds,
    pipeline_config_from_app_config,
    score_signature,
    scores_meet_grading_constraints,
    should_refresh_page,
    update_same_score_streak,
)
from models import AppConfig, ScoringSettings, ScoringUnit, Workflow, config_from_dict


ROOT = Path(__file__).resolve().parent


class FakeHooks(GradingHooks):
    def __init__(self, captures=None, grade_impl=None, blank_impl=None):
        self.captures = list(captures or [b"card-a"])
        self._capture_i = 0
        self.grade_impl = grade_impl or (lambda _image: {"scores": [8.0], "result": {"final_score": 8.0}})
        self.blank_impl = blank_impl or (lambda _image: False)
        self.grade_calls = 0
        self.fill_calls: list[float] = []
        self.sleeps: list[float] = []
        self.hotkeys: list[str] = []
        self.logs: list[str] = []
        self.statuses: list[str] = []
        self.results: list[dict] = []
        self.errors: list[str] = []
        self.history_emits = 0
        self.running = True

    def capture(self) -> bytes:
        if self._capture_i < len(self.captures):
            data = self.captures[self._capture_i]
            self._capture_i += 1
            return data
        return self.captures[-1] if self.captures else b""

    def is_blank(self, image: bytes) -> bool:
        return bool(self.blank_impl(image))

    def grade(self, image: bytes) -> dict:
        self.grade_calls += 1
        return self.grade_impl(image)

    def fill_and_submit(self, score, values=None) -> None:
        self.fill_calls.append(float(score))

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(float(seconds))

    def is_running(self) -> bool:
        return self.running

    def wait_if_paused(self) -> None:
        return None

    def send_hotkey(self, spec: str) -> bool:
        self.hotkeys.append(spec)
        return True

    def log(self, message: str) -> None:
        self.logs.append(str(message))

    def emit_status(self, text: str) -> None:
        self.statuses.append(str(text))

    def emit_result(self, result, image=None) -> None:
        self.results.append(result)

    def emit_progress(self, text: str) -> None:
        return None

    def emit_history(self) -> None:
        self.history_emits += 1

    def emit_error(self, text: str) -> None:
        self.errors.append(str(text))


def test_scores_meet_grading_constraints() -> None:
    assert scores_meet_grading_constraints([4, 6], max_score=10, min_score=0, step=1, expected=2) is True
    assert scores_meet_grading_constraints([4], max_score=10, min_score=0, step=1, expected=2) is False
    assert scores_meet_grading_constraints([4.2, 6], max_score=10, min_score=0, step=1, expected=2) is False
    assert scores_meet_grading_constraints([6, 6], max_score=10, min_score=0, step=1, expected=2) is False
    assert scores_meet_grading_constraints([8.5], max_score=10, min_score=0, step=0.5, expected=1) is True
    assert scores_meet_grading_constraints([-1], max_score=10, min_score=0, step=1, expected=1) is False
    assert scores_meet_grading_constraints([11], max_score=10, min_score=0, step=1, expected=1) is False


def test_score_signature_matches_csharp() -> None:
    assert score_signature([8.0, 1.5]) == "8|1.5"
    assert score_signature([8]) == "8"
    assert score_signature([]) == ""


def test_update_same_score_streak_aborts_after_threshold() -> None:
    signature, streak, abort = update_same_score_streak("", 0, [8.0], enabled=True, threshold=3)
    assert signature == "8"
    assert streak == 1
    assert abort is False
    signature, streak, abort = update_same_score_streak(signature, streak, [8.0], enabled=True, threshold=3)
    assert streak == 2
    assert abort is False
    signature, streak, abort = update_same_score_streak(signature, streak, [8.0], enabled=True, threshold=3)
    assert streak == 3
    assert abort is True
    signature, streak, abort = update_same_score_streak("8", 3, [7.0], enabled=True, threshold=3)
    assert signature == "7"
    assert streak == 1
    assert abort is False
    signature, streak, abort = update_same_score_streak("8", 2, [8.0], enabled=False, threshold=3)
    assert signature == ""
    assert streak == 0
    assert abort is False


def test_should_refresh_page() -> None:
    assert should_refresh_page(20, enabled=True, frequency=20) is True
    assert should_refresh_page(19, enabled=True, frequency=20) is False
    assert should_refresh_page(20, enabled=False, frequency=20) is False
    assert should_refresh_page(0, enabled=True, frequency=20) is False
    assert should_refresh_page(4, enabled=True, frequency=2) is True


def test_retry_spacing_and_network_wait_match_csharp() -> None:
    assert apply_retry_spacing_seconds(1) == 0
    assert apply_retry_spacing_seconds(2) == 0.2
    assert apply_retry_spacing_seconds(3) == 0.35
    assert apply_retry_spacing_seconds(2, aggressive=True) == 0.6
    assert network_recovery_wait_seconds(1, 0.2) == 3.0
    assert network_recovery_wait_seconds(2, 0.2) == 5.25


def test_transient_network_errors_are_retryable() -> None:
    assert is_transient_network_error(TimeoutError("timed out")) is True
    assert is_transient_network_error(ConnectionError("connection refused")) is True
    assert is_transient_network_error(RuntimeError("API 调用失败: connection reset")) is True
    assert is_transient_network_error(RuntimeError("503 Service Unavailable")) is True
    assert is_transient_network_error(RuntimeError("502 bad gateway")) is True
    assert is_transient_network_error(RuntimeError("504 gateway timeout")) is True
    assert is_transient_network_error(RuntimeError("network unreachable")) is True
    assert is_transient_network_error(RuntimeError("SSL: CERTIFICATE_VERIFY_FAILED")) is True
    assert is_transient_network_error(RuntimeError("forcibly closed")) is True
    assert is_transient_network_error(RuntimeError("broken pipe")) is True
    assert is_transient_network_error(RuntimeError("401 unauthorized")) is False
    assert is_transient_network_error(RuntimeError("403 forbidden")) is False
    assert is_transient_network_error(RuntimeError("invalid api key")) is False
    assert is_transient_network_error(RuntimeError("quota exceeded")) is False


def test_identical_capture_retries_until_image_changes() -> None:
    hooks = FakeHooks(captures=[b"same", b"same", b"fresh"])
    session = GradingSession(PipelineConfig(capture_delay=0), hooks)
    session.previous_capture = b"same"
    image = session.capture_for_grading(card_index=1, attempt=1)
    assert image == b"fresh"
    assert 1.0 in hooks.sleeps
    assert session.previous_capture == b"fresh"


def test_first_card_does_not_wait_for_different_capture() -> None:
    hooks = FakeHooks(captures=[b"first"])
    session = GradingSession(PipelineConfig(capture_delay=0), hooks)
    image = session.capture_for_grading(card_index=0, attempt=1)
    assert image == b"first"
    assert 1.0 not in hooks.sleeps


def test_score_constraint_failure_retries_then_fills() -> None:
    state = {"n": 0}

    def grade_impl(_image):
        state["n"] += 1
        if state["n"] == 1:
            return {"scores": [3.3], "result": {"final_score": 3.3}}
        return {"scores": [8.0], "result": {"final_score": 8.0}}

    hooks = FakeHooks(captures=[b"card-a", b"card-b"], grade_impl=grade_impl)
    config = PipelineConfig(
        capture_delay=0.15,
        retry_limit=5,
        max_score=10,
        min_score=0,
        step=1,
        score_points=1,
        next_paper_delay=0,
    )
    outcome = GradingSession(config, hooks).process_one(card_index=0, auto_submit=True)
    assert isinstance(outcome, CardOutcome)
    assert hooks.grade_calls == 2
    assert hooks.fill_calls == [8.0]
    assert 0.15 in hooks.sleeps
    assert 0.2 in hooks.sleeps


def test_network_error_retries_same_index_then_fills() -> None:
    state = {"n": 0}

    def grade_impl(_image):
        state["n"] += 1
        if state["n"] == 1:
            raise RuntimeError("API 调用失败: timed out")
        return {"scores": [7.0], "result": {"final_score": 7.0}}

    hooks = FakeHooks(captures=[b"card-a", b"card-a"], grade_impl=grade_impl)
    config = PipelineConfig(
        capture_delay=0,
        retry_limit=5,
        max_score=10,
        step=1,
        score_points=1,
        delay_seconds=0.2,
        next_paper_delay=0,
        target_count=1,
    )
    session = GradingSession(config, hooks)
    try:
        session.process_one(card_index=0, auto_submit=True)
        raise AssertionError("expected GradingNetworkRecoverable")
    except GradingNetworkRecoverable:
        pass
    assert session.wait_after_network_recovery() is True
    assert any(sleep >= 3.0 for sleep in hooks.sleeps)
    session.run_loop(target_count=1)
    assert hooks.fill_calls == [7.0]


def test_same_score_streak_stops_loop() -> None:
    hooks = FakeHooks(captures=[b"a", b"b", b"c", b"d"])
    config = PipelineConfig(
        capture_delay=0,
        next_paper_delay=0,
        retry_limit=5,
        max_score=10,
        step=1,
        score_points=1,
        enable_abnormal_termination=True,
        abnormal_termination_count=3,
        target_count=10,
    )
    GradingSession(config, hooks).run_loop(target_count=10)
    assert hooks.fill_calls == [8.0, 8.0, 8.0]
    joined = "\n".join(hooks.logs + hooks.statuses)
    assert "连续" in joined
    assert "分值" in joined


def test_page_refresh_every_n_cards() -> None:
    hooks = FakeHooks(captures=[b"1", b"2", b"3", b"4"])
    config = PipelineConfig(
        capture_delay=0,
        next_paper_delay=0,
        retry_limit=5,
        max_score=10,
        step=1,
        score_points=1,
        enable_page_refresh=True,
        page_refresh_frequency=2,
        page_refresh_hotkey="F5",
        page_refresh_wait_seconds=0.5,
        target_count=4,
    )
    GradingSession(config, hooks).run_loop(target_count=4)
    assert hooks.hotkeys == ["F5", "F5"]
    assert hooks.sleeps.count(0.5) == 2


def test_debug_once_does_not_fill_or_submit() -> None:
    hooks = FakeHooks(captures=[b"debug"])
    config = PipelineConfig(capture_delay=0, retry_limit=5, max_score=10, step=1, score_points=1)
    outcome = GradingSession(config, hooks).process_one(card_index=-1, auto_submit=False)
    assert outcome.status == "debug"
    assert hooks.fill_calls == []
    assert "debug" in hooks.statuses


def test_blank_card_scores_zero_without_model() -> None:
    hooks = FakeHooks(captures=[b"blank"], blank_impl=lambda _image: True)
    config = PipelineConfig(capture_delay=0, retry_limit=5, max_score=10, step=1, score_points=1)
    outcome = GradingSession(config, hooks).process_one(card_index=0, auto_submit=True)
    assert hooks.grade_calls == 0
    assert outcome.result["final_score"] == 0
    assert hooks.fill_calls == [0.0]


def test_workflow_pipeline_defaults_match_csharp() -> None:
    workflow = Workflow()
    assert workflow.retry_limit == 5
    assert workflow.enable_abnormal_termination is False
    assert workflow.abnormal_termination_count == 10
    assert workflow.enable_page_refresh is False
    assert workflow.page_refresh_frequency == 20
    assert workflow.page_refresh_hotkey == "F5"
    assert workflow.page_refresh_wait_seconds == 5.0
    cfg = config_from_dict({"workflow": {}})
    assert cfg.workflow.retry_limit == 5
    assert cfg.workflow.enable_abnormal_termination is False
    assert cfg.workflow.abnormal_termination_count == 10
    assert cfg.workflow.enable_page_refresh is False
    assert cfg.workflow.page_refresh_frequency == 20
    assert cfg.workflow.page_refresh_hotkey == "F5"
    assert cfg.workflow.page_refresh_wait_seconds == 5.0


def test_workflow_pipeline_fields_persist() -> None:
    cfg = config_from_dict(
        {
            "workflow": {
                "retry_limit": 7,
                "enable_abnormal_termination": True,
                "abnormal_termination_count": 4,
                "enable_page_refresh": True,
                "page_refresh_frequency": 8,
                "page_refresh_hotkey": "f6",
                "page_refresh_wait_seconds": 1.5,
            }
        }
    )
    assert cfg.workflow.retry_limit == 7
    assert cfg.workflow.enable_abnormal_termination is True
    assert cfg.workflow.abnormal_termination_count == 4
    assert cfg.workflow.enable_page_refresh is True
    assert cfg.workflow.page_refresh_frequency == 8
    assert cfg.workflow.page_refresh_hotkey == "F6"
    assert cfg.workflow.page_refresh_wait_seconds == 1.5
    dumped = cfg.to_dict()["workflow"]
    assert dumped["retry_limit"] == 7
    assert dumped["enable_abnormal_termination"] is True
    assert dumped["page_refresh_hotkey"] == "F6"


def test_invalid_page_refresh_hotkey_falls_back_to_f5() -> None:
    cfg = config_from_dict({"workflow": {"page_refresh_hotkey": "not-a-key"}})
    assert cfg.workflow.page_refresh_hotkey == "F5"
    cfg = config_from_dict({"workflow": {"page_refresh_hotkey": ""}})
    assert cfg.workflow.page_refresh_hotkey == "F5"


def test_pipeline_config_from_app_config_maps_units() -> None:
    cfg = AppConfig(
        scoring=ScoringSettings(
            max_score=10,
            round_step=0.5,
            units=[
                ScoringUnit(label="a", max_score=4, round_step=1),
                ScoringUnit(label="b", max_score=6, round_step=1),
            ],
        ),
        workflow=Workflow(retry_limit=5, capture_delay=0.15, next_paper_delay=0.2),
    )
    pipe = pipeline_config_from_app_config(cfg)
    assert pipe.score_points == 2
    assert pipe.max_score == 10
    assert pipe.step == 0.5
    assert pipe.retry_limit == 5
    assert pipe.capture_delay == 0.15
    assert pipe.delay_seconds == 0.2


def test_config_tab_exposes_pipeline_controls() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    assert "retry_limit" in source
    assert "enable_abnormal_termination" in source
    assert "abnormal_termination_count" in source
    assert "enable_page_refresh" in source
    assert "page_refresh_frequency" in source
    assert "page_refresh_hotkey" in source
    assert "page_refresh_wait_seconds" in source
    assert "GradingSession" in source or "grading_pipeline" in source
    assert "if self.continuous" in source
    assert "callback = None" in source


def _app_method_source(name: str) -> str:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    start = source.find(f"    def {name}")
    assert start >= 0, name
    next_def = source.find("\n    def ", start + 1)
    assert next_def > start, name
    return source[start:next_def]


def test_save_all_reads_pipeline_fields_from_ui_before_writing_back() -> None:
    save_src = _app_method_source("save_all")
    fields = [
        "retry_limit",
        "enable_abnormal_termination",
        "abnormal_termination_count",
        "enable_page_refresh",
        "page_refresh_frequency",
        "page_refresh_hotkey",
        "page_refresh_wait_seconds",
    ]
    for field in fields:
        assign = save_src.find(f"workflow.{field} =")
        assert assign >= 0, field
        assert f"self.{field}.get(" in save_src, field
        write_back = save_src.find(f"self.{field}.set(")
        if write_back >= 0:
            assert assign < write_back, field


def test_apply_config_to_ui_restores_pipeline_fields() -> None:
    apply_src = _app_method_source("apply_config_to_ui")
    for field in [
        "retry_limit",
        "enable_abnormal_termination",
        "abnormal_termination_count",
        "enable_page_refresh",
        "page_refresh_frequency",
        "page_refresh_hotkey",
        "page_refresh_wait_seconds",
    ]:
        assert f"self.{field}.set(" in apply_src, field


def test_grade_once_worker_clears_running_after_success() -> None:
    once_src = _app_method_source("_grade_once_worker")
    assert "except GradingNetworkRecoverable" in once_src
    assert "finally:" in once_src
    finally_part = once_src.split("finally:", 1)[1]
    assert "self.running = False" in finally_part
    assert "self.continuous = False" in finally_part
    assert "self.paused = False" in finally_part


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    for test in tests:
        test()
        print(f"PASS {test.__name__}")
    print(f"all {len(tests)} tests passed")
