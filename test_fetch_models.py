from __future__ import annotations

import json
from unittest.mock import Mock, patch

from ai_client import (
    call_openai_compatible,
    candidate_models_urls,
    detect_api_format,
    list_provider_models,
    models_url_from_endpoint,
    request_url_for_format,
    test_provider as call_test_provider,
)
from models import Provider, default_providers


def test_models_url_converts_chat_completions() -> None:
    assert models_url_from_endpoint("https://api.openai.com/v1/chat/completions") == "https://api.openai.com/v1/models"
    assert models_url_from_endpoint("https://ark.cn-beijing.volces.com/api/v3/chat/completions") == "https://ark.cn-beijing.volces.com/api/v3/models"
    assert models_url_from_endpoint("https://api.example.com/v1/models") == "https://api.example.com/v1/models"
    assert models_url_from_endpoint("https://gateway.example.com/v1") == "https://gateway.example.com/v1/models"
    assert models_url_from_endpoint("https://api.memeapi.top") == "https://api.memeapi.top/v1/models"
    assert models_url_from_endpoint("https://api.memeapi.top/v1/responses") == "https://api.memeapi.top/v1/models"
    assert candidate_models_urls("https://api.memeapi.top")[0] == "https://api.memeapi.top/v1/models"
    assert "https://api.memeapi.top/models" in candidate_models_urls("https://api.memeapi.top")


def test_list_provider_models_uses_key_and_endpoint() -> None:
    provider = Provider(
        name="测试",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="sk-secret-key",
        model="old-model",
        models=["old-model"],
    )
    response = Mock(status_code=200)
    response.json.return_value = {
        "data": [
            {"id": "gpt-4o"},
            {"id": "gpt-4o-mini"},
            {"name": "claude-3-sonnet"},
        ]
    }
    session = Mock()
    session.get.return_value = response
    with patch("ai_client.http_session", return_value=session):
        models = list_provider_models(provider)
    assert models == ["gpt-4o", "gpt-4o-mini", "claude-3-sonnet"]
    assert session.get.call_args.args[0] == "https://api.example.com/v1/models"
    assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer sk-secret-key"


def test_list_provider_models_supports_query_key_and_redacts_secret() -> None:
    provider = Provider(
        name="Query",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="sk-hidden-key",
        api_key_location="query",
        api_key_field="apikey",
        api_key_prefix="",
    )
    response = Mock(status_code=401)
    response.text = "invalid apikey=sk-hidden-key"
    session = Mock()
    session.get.return_value = response
    with patch("ai_client.http_session", return_value=session):
        try:
            list_provider_models(provider)
        except RuntimeError as exc:
            message = str(exc)
        else:
            raise AssertionError("expected failure")
    assert "sk-hidden-key" not in message
    assert "***" in message


def test_list_provider_models_reads_ollama_tags() -> None:
    provider = Provider(
        name="Ollama",
        protocol="ollama",
        endpoint="http://127.0.0.1:11434/api/chat",
        model="old",
    )
    with patch("ai_client.discover_ollama") as discover:
        discover.return_value = Mock(running=True, installed_models=["qwen2.5vl:7b", "llama3.2-vision:11b"], error="")
        models = list_provider_models(provider)
    assert models == ["qwen2.5vl:7b", "llama3.2-vision:11b"]



def test_list_provider_models_skips_empty_body_and_retries_v1_models() -> None:
    provider = Provider(name="meme", endpoint="https://api.memeapi.top", api_key="sk-secret-key")
    empty = Mock(status_code=200, text="")
    empty.json.side_effect = ValueError("Expecting value: line 1 column 1 (char 0)")
    ok = Mock(status_code=200, text='{"data":[{"id":"gpt-4o"}]}')
    ok.json.return_value = {"data": [{"id": "gpt-4o"}]}
    session = Mock()
    session.get.side_effect = [empty, ok]
    with patch("ai_client.http_session", return_value=session):
        models = list_provider_models(provider)
    assert models == ["gpt-4o"]
    assert [call.args[0] for call in session.get.call_args_list][:2] == [
        "https://api.memeapi.top/v1/models",
        "https://api.memeapi.top/models",
    ]


def test_detects_responses_and_chat_completions_endpoints() -> None:
    responses = Provider(endpoint="https://api.memeapi.top/v1/responses")
    chat = Provider(endpoint="https://api.openai.com/v1/chat/completions")
    bare = Provider(endpoint="https://api.memeapi.top")
    assert detect_api_format(responses) == "responses"
    assert detect_api_format(chat) == "chat_completions"
    assert detect_api_format(bare) == "responses"
    assert request_url_for_format(bare.endpoint, "responses") == "https://api.memeapi.top/v1/responses"
    assert request_url_for_format(chat.endpoint, "chat_completions") == "https://api.openai.com/v1/chat/completions"
    forced = Provider(endpoint="https://api.memeapi.top", api_format="chat_completions")
    assert detect_api_format(forced) == "chat_completions"
    assert request_url_for_format(forced.endpoint, "chat_completions") == "https://api.memeapi.top/v1/chat/completions"


def test_call_openai_compatible_posts_responses_payload() -> None:
    provider = Provider(
        name="meme",
        endpoint="https://api.memeapi.top/v1/responses",
        api_key="sk-secret-key",
        model="gpt-4o",
        api_format="responses",
        reasoning_effort="medium",
    )
    response = Mock(status_code=200)
    response.json.return_value = {"output_text": "连接成功"}
    session = Mock()
    session.post.return_value = response
    with patch("ai_client.http_session", return_value=session):
        text = call_openai_compatible(provider, "请只回复：连接成功")
    assert text == "连接成功"
    body = json.loads(session.post.call_args.kwargs["data"])
    assert session.post.call_args.args[0] == "https://api.memeapi.top/v1/responses"
    assert "messages" not in body
    assert body["model"] == "gpt-4o"
    assert body["input"][0]["role"] == "user"
    assert body["input"][0]["content"][0]["type"] == "input_text"
    assert body["max_output_tokens"] == 2048
    assert body["reasoning"]["effort"] == "medium"


def test_call_openai_compatible_keeps_chat_completions() -> None:
    provider = Provider(
        name="OpenAI",
        endpoint="https://api.openai.com/v1/chat/completions",
        api_key="sk-secret-key",
        model="gpt-4o",
    )
    response = Mock(status_code=200)
    response.json.return_value = {"choices": [{"message": {"content": "ok"}}]}
    session = Mock()
    session.post.return_value = response
    with patch("ai_client.http_session", return_value=session):
        text = call_openai_compatible(provider, "hello")
    assert text == "ok"
    body = json.loads(session.post.call_args.kwargs["data"])
    assert "messages" in body
    assert "input" not in body


def test_call_openai_compatible_falls_back_from_responses_and_remaps_reasoning() -> None:
    provider = Provider(
        name="meme",
        endpoint="https://api.memeapi.top",
        api_key="sk-secret-key",
        model="glm-5.3-flash",
        retry_enabled=False,
        retry_count=1,
    )
    assert detect_api_format(provider) == "responses"
    responses_error = Mock(
        status_code=400,
        text='{"error":{"message":"model \\"glm-5.3-flash\\" is not supported on /v1/responses; use /v1/chat/completions instead","code":"model_not_supported_on_endpoint"}}',
    )
    reasoning_error = Mock(
        status_code=400,
        text='{"error":{"message":"The request is invalid: 该模型始终思考，不支持关闭思考；请使用 low、high 或 max."}}',
    )
    success = Mock(status_code=200)
    success.json.return_value = {"choices": [{"message": {"content": "连接成功"}}]}
    session = Mock()
    session.post.side_effect = [responses_error, reasoning_error, success]
    with patch("ai_client.http_session", return_value=session):
        text = call_openai_compatible(provider, "只回复连接成功")
    assert text == "连接成功"
    urls = [call.args[0] for call in session.post.call_args_list]
    assert urls == [
        "https://api.memeapi.top/v1/responses",
        "https://api.memeapi.top/v1/chat/completions",
        "https://api.memeapi.top/v1/chat/completions",
    ]
    bodies = [json.loads(call.kwargs["data"]) for call in session.post.call_args_list]
    assert "input" in bodies[0]
    assert "messages" in bodies[1]
    assert bodies[1].get("reasoning_effort") == "medium"
    assert bodies[2].get("reasoning_effort") == "low"


def test_provider_tab_shows_upstream_format_choices() -> None:
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    assert "上游格式" in source
    assert "Responses" in source
    assert "Chat Completions" in source
    assert "API_FORMAT_CHOICES" in source

def test_reasoning_effort_defaults_to_medium() -> None:
    assert Provider().reasoning_effort == "medium"
    volcengine = next(item for item in default_providers() if item.name == "火山引擎")
    assert volcengine.reasoning_effort == "medium"
    ollama = Provider(name="Ollama", protocol="ollama", reasoning_effort="")
    assert ollama.reasoning_effort == ""


def test_provider_tab_can_fetch_models_and_shows_chinese_reasoning() -> None:
    from pathlib import Path
    source = Path("app.py").read_text(encoding="utf-8")
    assert "获取模型" in source
    assert "list_provider_models" in source
    assert "中等" in source
    assert 'row = self._entry(form, row, "推理强度"' not in source
    assert "REASONING_CHOICES" in source


if __name__ == "__main__":
    test_models_url_converts_chat_completions()
    test_list_provider_models_uses_key_and_endpoint()
    test_list_provider_models_supports_query_key_and_redacts_secret()
    test_list_provider_models_reads_ollama_tags()
    test_list_provider_models_skips_empty_body_and_retries_v1_models()
    test_detects_responses_and_chat_completions_endpoints()
    test_call_openai_compatible_posts_responses_payload()
    test_call_openai_compatible_keeps_chat_completions()
    test_call_openai_compatible_falls_back_from_responses_and_remaps_reasoning()
    test_reasoning_effort_defaults_to_medium()
    test_provider_tab_can_fetch_models_and_shows_chinese_reasoning()
    test_provider_tab_shows_upstream_format_choices()
    print("[OK] fetch models checks passed")
