#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批改速度回归：少一次模型调用、缩短固定等待、压缩连续批改输出。"""

from __future__ import annotations

import inspect
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from ai_client import (
    _openai_request_body,
    build_prompt,
    grade_image,
    grade_with_optional_ocr,
    parse_response,
    scoring_max_tokens,
)
from app import AIMarkerApp
from models import AppConfig, Provider, ScoringSettings, Workflow, config_from_dict


def _provider() -> Provider:
    return Provider(
        name="meme",
        endpoint="https://api.memeapi.top",
        api_key="sk-test",
        model="grok-4.6",
        reasoning_effort="medium",
        api_format="responses",
    )


def _config(**workflow_kwargs) -> AppConfig:
    workflow = Workflow(**workflow_kwargs)
    return AppConfig(workflow=workflow, scoring=ScoringSettings(max_score=10), answer="标准答案")


def test_default_recognition_mode_is_direct() -> None:
    assert Workflow().recognition_mode == "direct"
    cfg = config_from_dict({"workflow": {}})
    assert cfg.workflow.recognition_mode == "direct"


def test_default_paper_delays_are_short() -> None:
    workflow = Workflow()
    assert workflow.capture_delay <= 0.2
    assert workflow.next_paper_delay <= 0.2
    cfg = config_from_dict({"workflow": {}})
    assert cfg.workflow.capture_delay <= 0.2
    assert cfg.workflow.next_paper_delay <= 0.2


def test_next_paper_wait_allows_zero() -> None:
    loop_source = inspect.getsource(AIMarkerApp._loop_worker)
    assert "max(0.1" not in loop_source
    assert "next_paper_delay" in loop_source


def test_ocr_first_calls_api_twice_direct_calls_once() -> None:
    calls: list[tuple] = []

    def fake_call(provider, prompt, image_b64=None, on_stream=None, extra_image_b64s=None, max_tokens=None):
        calls.append((prompt, image_b64, max_tokens))
        if "只输出识别到的学生答案" in prompt:
            return "学生答案"
        return "【答案复述】\n学生答案\n\n【评分依据】\n给分\n\n【得分】\n8"

    image = SimpleNamespace()
    with patch("ai_client.call_openai_compatible", side_effect=fake_call), patch("ai_client.image_to_base64", return_value="img"):
        calls.clear()
        direct = grade_with_optional_ocr(_config(recognition_mode="direct"), image, _provider())
        assert direct.score == 8
        assert len(calls) == 1

        calls.clear()
        ocr = grade_with_optional_ocr(_config(recognition_mode="ocr_first"), image, _provider())
        assert ocr.score == 8
        assert len(calls) == 2


def test_continuous_prompt_is_compact_and_still_parses_score() -> None:
    compact = build_prompt(_config(mode="normal"))
    assert "【得分】" in compact
    assert "逐条列出学生答案要点" not in compact
    parsed = parse_response("【评分依据】\n要点正确\n\n【得分】\n7.5", _config())
    assert parsed.score == 7.5


def test_continuous_scoring_uses_smaller_max_tokens() -> None:
    assert scoring_max_tokens(_config(mode="normal")) <= 512
    assert scoring_max_tokens(_config(mode="unattended")) <= 512
    assert scoring_max_tokens(_config(mode="trial")) <= 512


def test_grade_image_passes_compact_max_tokens() -> None:
    seen: list[int | None] = []

    def fake_call(provider, prompt, image_b64=None, on_stream=None, extra_image_b64s=None, max_tokens=None):
        seen.append(max_tokens)
        return "【得分】\n6"

    with patch("ai_client.call_openai_compatible", side_effect=fake_call), patch("ai_client.image_to_base64", return_value="img"):
        result = grade_image(_config(mode="unattended"), SimpleNamespace(), _provider())
        assert result.score == 6
        assert seen and seen[0] is not None and seen[0] <= 512


def test_continuous_grading_skips_stream_callback() -> None:
    source = inspect.getsource(AIMarkerApp._grade_once_worker)
    assert "if self.continuous" in source
    assert "callback = None" in source


def test_request_body_uses_passed_max_tokens() -> None:
    body = _openai_request_body(_provider(), "prompt", None, None, "responses", max_tokens=256)
    assert body["max_output_tokens"] == 256
    body = _openai_request_body(_provider(), "prompt", None, None, "chat_completions", max_tokens=256)
    assert body["max_tokens"] == 256


def test_speed_keeps_jpeg_upload_and_http_session() -> None:
    image_source = Path(__file__).resolve().parent.joinpath("image_tools.py").read_text(encoding="utf-8")
    client_source = Path(__file__).resolve().parent.joinpath("ai_client.py").read_text(encoding="utf-8")
    assert 'format="JPEG"' in image_source
    assert "quality=92" in image_source
    assert "def http_session" in client_source
    assert "requests.post(" not in client_source
    assert "scoring_max_tokens" in client_source


if __name__ == "__main__":
    test_default_recognition_mode_is_direct()
    test_default_paper_delays_are_short()
    test_next_paper_wait_allows_zero()
    test_ocr_first_calls_api_twice_direct_calls_once()
    test_continuous_prompt_is_compact_and_still_parses_score()
    test_continuous_scoring_uses_smaller_max_tokens()
    test_grade_image_passes_compact_max_tokens()
    test_continuous_grading_skips_stream_callback()
    test_request_body_uses_passed_max_tokens()
    test_speed_keeps_jpeg_upload_and_http_session()
    print("[OK] grading speed checks passed")
