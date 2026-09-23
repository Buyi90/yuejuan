from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import requests

from models import Provider


VISION_MODEL_MARKERS = (
    "vision",
    "vl",
    "llava",
    "minicpm-v",
    "moondream",
    "bakllava",
    "gemma3",
    "mllama",
)


@dataclass
class OllamaDiscovery:
    running: bool = False
    installed_models: list[str] | None = None
    running_models: list[str] | None = None
    preferred_model: str = ""
    error: str = ""

    def __post_init__(self) -> None:
        self.installed_models = list(self.installed_models or [])
        self.running_models = list(self.running_models or [])


def ollama_base_url(endpoint: str) -> str:
    parsed = urlsplit(endpoint.strip() or "http://127.0.0.1:11434")
    path = parsed.path.rstrip("/")
    for suffix in ("/api/chat", "/api/generate", "/api/tags", "/api/ps"):
        if path.endswith(suffix):
            path = path[: -len(suffix)]
            break
    return urlunsplit((parsed.scheme or "http", parsed.netloc, path, "", "")).rstrip("/")


def _model_names(payload: Any) -> list[str]:
    values: list[str] = []
    for item in payload.get("models", []) if isinstance(payload, dict) else []:
        name = item.get("name") if isinstance(item, dict) else item
        if name and str(name) not in values:
            values.append(str(name))
    return values


def is_vision_model(model_name: str) -> bool:
    normalized = model_name.lower()
    return any(marker in normalized for marker in VISION_MODEL_MARKERS)


def _ordered_models(installed: list[str], running: list[str]) -> list[str]:
    groups = (
        [model for model in running if is_vision_model(model)],
        [model for model in installed if is_vision_model(model)],
        [model for model in running if not is_vision_model(model)],
        [model for model in installed if not is_vision_model(model)],
    )
    result: list[str] = []
    for group in groups:
        for model in group:
            if model not in result:
                result.append(model)
    return result


def discover_ollama(endpoint: str, timeout: float = 3.0) -> OllamaDiscovery:
    base_url = ollama_base_url(endpoint)
    try:
        tags_response = requests.get(f"{base_url}/api/tags", timeout=timeout)
        tags_response.raise_for_status()
        installed = _model_names(tags_response.json())
    except Exception as exc:
        return OllamaDiscovery(error=f"无法连接 Ollama：{exc}")

    running: list[str] = []
    ps_error = ""
    try:
        ps_response = requests.get(f"{base_url}/api/ps", timeout=timeout)
        ps_response.raise_for_status()
        running = _model_names(ps_response.json())
    except Exception as exc:
        ps_error = f"无法读取 Ollama 运行中模型：{exc}"

    ordered = _ordered_models(installed, running)
    return OllamaDiscovery(
        running=True,
        installed_models=installed,
        running_models=running,
        preferred_model=ordered[0] if ordered else "",
        error=ps_error,
    )


def prepare_ollama_provider(provider: Provider, discovery: OllamaDiscovery) -> str:
    models = _ordered_models(discovery.installed_models, discovery.running_models)
    if models:
        provider.models = models
    if discovery.preferred_model:
        provider.model = discovery.preferred_model
    return provider.model


def refresh_ollama_providers(
    providers: list[Provider],
    discover=discover_ollama,
) -> list[str]:
    errors: list[str] = []
    by_endpoint: dict[str, OllamaDiscovery] = {}
    for provider in providers:
        if provider.protocol != "ollama":
            continue
        if provider.endpoint not in by_endpoint:
            by_endpoint[provider.endpoint] = discover(provider.endpoint)
        discovery = by_endpoint[provider.endpoint]
        if not discovery.running:
            errors.append(f"{provider.name}：{discovery.error or 'Ollama 未运行'}")
            continue
        if not discovery.installed_models:
            errors.append(f"{provider.name}：Ollama 中没有已安装模型")
            continue
        prepare_ollama_provider(provider, discovery)
    return errors
