from __future__ import annotations

from unittest.mock import Mock, patch

from models import Provider
from ollama_discovery import discover_ollama, prepare_ollama_provider, refresh_ollama_providers


def test_discover_ollama_reads_installed_and_running_models() -> None:
    tags_response = Mock(status_code=200)
    tags_response.json.return_value = {
        "models": [
            {"name": "qwen2.5:7b"},
            {"name": "qwen2.5vl:7b"},
        ]
    }
    ps_response = Mock(status_code=200)
    ps_response.json.return_value = {"models": [{"name": "qwen2.5vl:7b"}]}

    with patch("ollama_discovery.requests.get", side_effect=[tags_response, ps_response]) as get:
        discovery = discover_ollama("http://127.0.0.1:11434/api/chat")

    assert discovery.running is True
    assert discovery.installed_models == ["qwen2.5:7b", "qwen2.5vl:7b"]
    assert discovery.running_models == ["qwen2.5vl:7b"]
    assert discovery.preferred_model == "qwen2.5vl:7b"
    assert [call.args[0] for call in get.call_args_list] == [
        "http://127.0.0.1:11434/api/tags",
        "http://127.0.0.1:11434/api/ps",
    ]


def test_discover_ollama_marks_service_unavailable() -> None:
    with patch("ollama_discovery.requests.get", side_effect=ConnectionError("refused")):
        discovery = discover_ollama("http://localhost:11434/api/chat")

    assert discovery.running is False
    assert discovery.installed_models == []
    assert "无法连接 Ollama" in discovery.error


def test_prepare_provider_prefers_running_vision_model_and_updates_models() -> None:
    provider = Provider(
        name="Ollama",
        protocol="ollama",
        endpoint="http://127.0.0.1:11434/api/chat",
        model="not-installed:latest",
    )
    discovery = Mock(
        running=True,
        installed_models=["qwen2.5:7b", "llama3.2-vision:11b"],
        running_models=["llama3.2-vision:11b", "qwen2.5:7b"],
        preferred_model="llama3.2-vision:11b",
        error="",
    )

    result = prepare_ollama_provider(provider, discovery)

    assert result == "llama3.2-vision:11b"
    assert provider.model == "llama3.2-vision:11b"
    assert provider.models == ["llama3.2-vision:11b", "qwen2.5:7b"]


def test_refresh_ollama_providers_reuses_discovery_and_updates_all_roles() -> None:
    first = Provider(
        name="主评本地",
        protocol="ollama",
        endpoint="http://127.0.0.1:11434/api/chat",
        model="qwen2.5:7b",
    )
    second = Provider(
        name="OCR本地",
        protocol="ollama",
        endpoint="http://127.0.0.1:11434/api/chat",
        model="qwen2.5:7b",
    )
    discovery = Mock(
        running=True,
        installed_models=["qwen2.5:7b", "qwen2.5vl:7b"],
        running_models=["qwen2.5vl:7b"],
        preferred_model="qwen2.5vl:7b",
        error="",
    )
    discover = Mock(return_value=discovery)

    results = refresh_ollama_providers([first, second], discover=discover)

    assert discover.call_count == 1
    assert first.model == second.model == "qwen2.5vl:7b"
    assert results == []


def test_refresh_ollama_providers_returns_unavailable_error() -> None:
    provider = Provider(
        name="Ollama本地",
        protocol="ollama",
        endpoint="http://localhost:11434/api/chat",
        model="qwen2.5:7b",
    )
    discovery = Mock(running=False, error="无法连接 Ollama：refused")

    errors = refresh_ollama_providers([provider], discover=Mock(return_value=discovery))

    assert errors == ["Ollama本地：无法连接 Ollama：refused"]
