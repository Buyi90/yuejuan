from __future__ import annotations

import json
from unittest.mock import Mock, patch

from ai_client import call_openai_compatible, test_provider as call_test_provider
from models import Provider, config_from_dict, default_providers


def test_default_providers_exclude_preset_ollama() -> None:
    assert all(provider.protocol != "ollama" for provider in default_providers())
    assert all(provider.name != "Ollama 本地" for provider in default_providers())


def test_ollama_protocol_survives_config_round_trip() -> None:
    config = config_from_dict(
        {
            "providers": [
                {
                    "name": "我的 Ollama",
                    "protocol": "ollama",
                    "source": "local",
                    "endpoint": "http://localhost:11434/api/chat",
                    "model": "qwen2.5vl:7b",
                }
            ],
            "active_provider": "我的 Ollama",
        }
    )

    provider = next(provider for provider in config.providers if provider.name == "我的 Ollama")
    assert provider.protocol == "ollama"
    assert provider.requires_api_key is False


def test_ollama_call_posts_native_payload_and_reads_stream() -> None:
    provider = Provider(
        name="Ollama",
        protocol="ollama",
        endpoint="http://127.0.0.1:11434/api/chat",
        model="qwen2.5vl:7b",
    )
    response = Mock(status_code=200)
    response.iter_lines.return_value = [
        json.dumps({"message": {"content": "第一段"}, "done": False}, ensure_ascii=False).encode(),
        json.dumps({"message": {"content": "第二段"}, "done": True}, ensure_ascii=False).encode(),
    ]
    streamed: list[str] = []

    session = Mock()
    session.post.return_value = response
    with patch("ai_client.http_session", return_value=session):
        result = call_openai_compatible(
            provider,
            "请识别答案",
            image_b64="abc123",
            extra_image_b64s=["material456"],
            on_stream=streamed.append,
        )

    body = json.loads(session.post.call_args.kwargs["data"])
    assert result == "第一段第二段"
    assert streamed == ["第一段", "第二段"]
    assert body == {
        "model": "qwen2.5vl:7b",
        "messages": [{"role": "user", "content": "请识别答案", "images": ["material456", "abc123"]}],
        "stream": True,
    }
    assert session.post.call_args.kwargs["headers"] == {"Content-Type": "application/json"}


def test_ollama_provider_test_does_not_require_api_key() -> None:
    provider = Provider(
        name="Ollama",
        protocol="ollama",
        endpoint="http://127.0.0.1:11434/api/chat",
        model="qwen2.5:7b",
    )
    response = Mock(status_code=200)
    response.json.return_value = {"message": {"content": "连接成功"}}

    session = Mock()
    session.post.return_value = response
    with patch("ai_client.http_session", return_value=session):
        result = call_test_provider(provider)

    assert result == "连接成功"
    body = json.loads(session.post.call_args.kwargs["data"])
    assert body["model"] == "qwen2.5:7b"
    assert body["stream"] is False
