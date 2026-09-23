#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""预设服务商只保留火山引擎、DeepSeek、智谱和自定义。"""

from __future__ import annotations

from models import config_from_dict, default_providers


EXPECTED_PRESET_NAMES = ["火山引擎", "DeepSeek", "智谱", "自定义服务商"]
RETIRED_PRESET_NAMES = {
    "5plus1官方",
    "Ollama 本地",
    "OpenAI兼容",
    "OneAPI中转站",
    "NewAPI中转站",
    "API2D中转站",
}


def test_default_providers_keep_four_presets() -> None:
    names = [item.name for item in default_providers()]
    assert names == EXPECTED_PRESET_NAMES


def test_default_providers_exclude_retired_presets() -> None:
    names = {item.name for item in default_providers()}
    assert names.isdisjoint(RETIRED_PRESET_NAMES)
    assert all(item.protocol != "ollama" for item in default_providers())


def test_empty_config_uses_volcengine() -> None:
    cfg = config_from_dict({})
    assert cfg.active_provider == "火山引擎"
    assert cfg.workflow.primary_provider_name == "火山引擎"
    assert [item.name for item in cfg.providers] == EXPECTED_PRESET_NAMES


def test_old_config_does_not_reinsert_retired_presets() -> None:
    cfg = config_from_dict(
        {
            "providers": [
                {
                    "name": "自定义服务商",
                    "endpoint": "https://example.com/v1/chat/completions",
                    "api_key": "k",
                    "model": "gpt-4o",
                },
                {
                    "name": "5plus1官方",
                    "endpoint": "https://api.ai.five-plus-one.com/v1/chat/completions",
                    "model": "aimarker-fast",
                },
                {
                    "name": "Ollama 本地",
                    "endpoint": "http://127.0.0.1:11434/api/chat",
                    "protocol": "ollama",
                    "model": "llama3.2-vision:11b",
                },
            ],
            "active_provider": "自定义服务商",
        }
    )
    names = [item.name for item in cfg.providers]
    assert "自定义服务商" in names
    assert "火山引擎" in names
    assert "DeepSeek" in names
    assert "智谱" in names
    assert set(names).isdisjoint(RETIRED_PRESET_NAMES)


def test_preset_endpoints_use_official_domains() -> None:
    by_name = {item.name: item for item in default_providers()}
    assert "ark.cn-beijing.volces.com" in by_name["火山引擎"].endpoint
    assert "api.deepseek.com" in by_name["DeepSeek"].endpoint
    assert "open.bigmodel.cn" in by_name["智谱"].endpoint
    assert by_name["自定义服务商"].endpoint == ""
    assert by_name["自定义服务商"].model == ""
    assert "chat/completions" in by_name["DeepSeek"].endpoint
    assert "chat/completions" in by_name["智谱"].endpoint


if __name__ == "__main__":
    test_default_providers_keep_four_presets()
    test_default_providers_exclude_retired_presets()
    test_empty_config_uses_volcengine()
    test_old_config_does_not_reinsert_retired_presets()
    test_preset_endpoints_use_official_domains()
    print("[OK] default provider checks passed")
