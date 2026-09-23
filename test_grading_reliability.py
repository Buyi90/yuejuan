#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""批改可靠性：修线程安全、关窗停跑、嵌套重试，并在不降质量的前提下提速。"""

from __future__ import annotations

import base64
import inspect
import io
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

from PIL import Image

import ai_client
from ai_client import (
    _image_content_from_b64,
    _material_image_b64s,
    _responses_image_content,
    call_openai_compatible,
    grade_dual,
    list_provider_models,
)
from app import AIMarkerApp
from automation import (
    AutomationConfig,
    AutomationError,
    click_box,
    fill_score,
    get_config,
    set_config,
)
from image_tools import black_pixel_ratio, image_to_base64
from models import AppConfig, GradeResult, Provider, RegionBox, ScoringSettings, Workflow


ROOT = Path(__file__).resolve().parent


def test_loop_worker_refreshes_history_via_queue() -> None:
    loop_source = inspect.getsource(AIMarkerApp._loop_worker)
    poll_source = inspect.getsource(AIMarkerApp._poll_queue)
    assert "refresh_history(" not in loop_source
    assert 'work_queue.put(("history"' in loop_source
    assert 'kind == "history"' in poll_source


def test_on_close_stops_running_worker() -> None:
    stopped: list[str] = []
    app = SimpleNamespace(
        running=True,
        continuous=True,
        paused=True,
        pause_hotkey_watcher=SimpleNamespace(stop=lambda: stopped.append("hotkey")),
        floating_boxes=SimpleNamespace(destroy=lambda: stopped.append("float")),
    )
    app.destroy = lambda: stopped.append("destroy")
    AIMarkerApp.on_close(app)
    assert app.running is False
    assert app.continuous is False
    assert app.paused is False
    assert stopped == ["hotkey", "float", "destroy"]
    close_source = inspect.getsource(AIMarkerApp.on_close)
    assert "running = False" in close_source
    assert "pause_hotkey_watcher" in close_source


def test_fill_score_does_not_multiply_click_retries() -> None:
    old = get_config()
    set_config(AutomationConfig(retry_attempts=3, retry_delay=0, click_delay=0, select_delay=0, safe_mode=False))
    clicks = {"n": 0}

    def boom(*_args, **_kwargs):
        clicks["n"] += 1
        raise RuntimeError("click fail")

    try:
        with patch("automation.pyautogui.click", side_effect=boom), patch("automation.time.sleep"):
            try:
                fill_score(RegionBox("score", "score", 10, 10, 20, 20, "#000"), 8)
            except (AutomationError, RuntimeError):
                pass
        assert clicks["n"] == 3
        click_source = (ROOT / "automation.py").read_text(encoding="utf-8")
        assert "@with_retry\ndef click_box" not in click_source.replace("\r\n", "\n")
        assert getattr(click_box, "__wrapped__", None) is None
    finally:
        set_config(old)


def test_image_to_base64_uses_high_quality_jpeg() -> None:
    img = Image.new("RGB", (24, 24), "white")
    raw = base64.b64decode(image_to_base64(img))
    assert raw.startswith(b"\xff\xd8")
    opened = Image.open(io.BytesIO(raw))
    assert opened.format == "JPEG"


def test_request_image_mime_follows_payload() -> None:
    jpeg_b64 = base64.b64encode(b"\xff\xd8\xff" + b"\x00" * 16).decode("ascii")
    png_b64 = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"\x00" * 16).decode("ascii")
    jpeg_chat = _image_content_from_b64(jpeg_b64)["image_url"]["url"]
    png_chat = _image_content_from_b64(png_b64)["image_url"]["url"]
    jpeg_resp = _responses_image_content(jpeg_b64)["image_url"]
    png_resp = _responses_image_content(png_b64)["image_url"]
    assert jpeg_chat.startswith("data:image/jpeg;base64,")
    assert png_chat.startswith("data:image/png;base64,")
    assert jpeg_resp.startswith("data:image/jpeg;base64,")
    assert png_resp.startswith("data:image/png;base64,")


def test_ai_client_reuses_http_session() -> None:
    source = (ROOT / "ai_client.py").read_text(encoding="utf-8")
    assert "def http_session" in source
    assert "requests.Session" in source
    assert "requests.post(" not in source
    assert "requests.get(" not in source

    provider = Provider(
        name="meme",
        endpoint="https://api.memeapi.top/v1/responses",
        api_key="sk-test",
        model="gpt-4o",
        api_format="responses",
        retry_enabled=False,
    )
    response = Mock(status_code=200, text='{"output_text":"ok"}')
    response.json.return_value = {"output_text": "ok"}
    session = Mock()
    session.post.return_value = response
    models_response = Mock(status_code=200, text='{"data":[{"id":"gpt-4o"}]}')
    models_response.json.return_value = {"data": [{"id": "gpt-4o"}]}
    session.get.return_value = models_response
    with patch("ai_client.http_session", return_value=session):
        text = call_openai_compatible(provider, "hello")
        models = list_provider_models(Provider(name="meme", endpoint="https://api.memeapi.top", api_key="sk-test"))
    assert text == "ok"
    assert models == ["gpt-4o"]
    session.post.assert_called()
    session.get.assert_called()


def test_material_images_are_cached_by_path_and_mtime() -> None:
    import tempfile

    source = inspect.getsource(_material_image_b64s)
    assert "mtime" in source
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "material.png"
        Image.new("RGB", (8, 8), "white").save(path, format="PNG")
        cfg = AppConfig(material_images=[str(path)])
        cache = getattr(ai_client, "_material_cache", None)
        if isinstance(cache, dict):
            cache.clear()
        reads = {"n": 0}
        real_read = Path.read_bytes

        def counted_read(self):
            reads["n"] += 1
            return real_read(self)

        with patch.object(Path, "read_bytes", counted_read):
            first = _material_image_b64s(cfg)
            second = _material_image_b64s(cfg)
        assert first and first == second
        assert reads["n"] == 1


def test_dual_grading_runs_primary_and_secondary_together() -> None:
    cfg = AppConfig(
        workflow=Workflow(dual_enabled=True, dual_threshold=1, arbitration_enabled=False),
        scoring=ScoringSettings(max_score=10),
    )
    barrier = threading.Barrier(2, timeout=1)

    def fake_grade(_config, _image, _provider, on_stream=None):
        barrier.wait()
        # 主评带回调，副评不带，用来区分两边原始分。
        value = 8.0 if on_stream is not None else 8.8
        return GradeResult(score=value, raw_score=value, comment="ok", student_answer="答案")

    with patch("ai_client.grade_with_optional_ocr", side_effect=fake_grade):
        result = grade_dual(cfg, SimpleNamespace(), Provider(name="shared"), on_stream=lambda _text: None)
    assert result.score == 8.4
    assert result.dual_eval and result.dual_eval.get("result") == "共识"
    assert result.dual_eval["scoreA"] == 8.0
    assert result.dual_eval["scoreB"] == 8.8


def test_black_pixel_ratio_uses_histogram() -> None:
    source = inspect.getsource(black_pixel_ratio)
    assert "getdata" not in source
    img = Image.new("RGB", (10, 10), "black")
    result = black_pixel_ratio(img)
    assert result["total"] == 100
    assert result["black"] == 100


if __name__ == "__main__":
    tests = [value for name, value in globals().items() if name.startswith("test_") and callable(value)]
    failed = 0
    for test in tests:
        try:
            test()
            print(f"PASS {test.__name__}")
        except Exception as exc:
            failed += 1
            print(f"FAIL {test.__name__}: {type(exc).__name__}: {exc}")
    if failed:
        raise SystemExit(f"{failed} failed")
    print(f"all {len(tests)} tests passed")
