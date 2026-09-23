#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
中转站 API 配置助手

快速配置常见中转站服务的工具
"""

import json
from pathlib import Path
from typing import Any


# 预设的中转站配置模板
GATEWAY_TEMPLATES = {
    "oneapi": {
        "name": "OneAPI中转站",
        "endpoint": "https://your-oneapi-domain.com/v1/chat/completions",
        "model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini", "claude-3-sonnet"],
        "api_key_location": "header",
        "api_key_prefix": "Bearer ",
        "gateway_type": "oneapi",
        "timeout": 90,
        "retry_enabled": True,
        "retry_count": 3,
        "retry_delay": 1.0,
    },
    "newapi": {
        "name": "NewAPI中转站",
        "endpoint": "https://your-newapi-domain.com/v1/chat/completions",
        "model": "gpt-4o",
        "models": ["gpt-4o", "claude-3-sonnet"],
        "api_key_location": "header",
        "api_key_prefix": "Bearer ",
        "gateway_type": "newapi",
        "timeout": 90,
        "retry_enabled": True,
        "retry_count": 3,
    },
    "api2d": {
        "name": "API2D中转站",
        "endpoint": "https://openai.api2d.net/v1/chat/completions",
        "model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "api_key_location": "header",
        "api_key_prefix": "Bearer ",
        "gateway_type": "api2d",
        "timeout": 90,
        "retry_enabled": True,
        "retry_count": 3,
    },
    "aihubmix": {
        "name": "AiHubMix中转站",
        "endpoint": "https://api.aihubmix.com/v1/chat/completions",
        "model": "gpt-4o",
        "models": ["gpt-4o", "claude-3-sonnet", "gemini-pro"],
        "api_key_location": "header",
        "api_key_prefix": "Bearer ",
        "gateway_type": "aihubmix",
        "timeout": 90,
        "retry_enabled": True,
        "retry_count": 3,
    },
    "cloudflare": {
        "name": "Cloudflare Workers中转",
        "endpoint": "https://your-worker.workers.dev/v1/chat/completions",
        "model": "gpt-4o",
        "models": ["gpt-4o", "gpt-4o-mini"],
        "api_key_location": "header",
        "api_key_prefix": "Bearer ",
        "timeout": 120,
        "retry_enabled": True,
        "retry_count": 4,
    },
    "custom_header": {
        "name": "自定义头认证",
        "endpoint": "https://api.example.com/v1/chat/completions",
        "model": "gpt-4o",
        "api_key_location": "header",
        "api_key_field": "X-API-Key",
        "api_key_prefix": "",
        "custom_headers": {
            "X-Project-ID": "your-project-id"
        },
        "timeout": 90,
        "retry_enabled": True,
    },
    "query_mode": {
        "name": "Query参数模式",
        "endpoint": "https://api.example.com/v1/chat/completions",
        "model": "gpt-4o",
        "api_key_location": "query",
        "api_key_field": "apikey",
        "api_key_prefix": "",
        "timeout": 90,
    },
}


def print_banner():
    """打印横幅"""
    print("\n" + "=" * 60)
    print("       中转站 API 配置助手")
    print("=" * 60 + "\n")


def print_templates():
    """打印可用的模板"""
    print("可用的中转站模板：\n")
    templates = [
        ("oneapi", "OneAPI 中转站（开源）"),
        ("newapi", "NewAPI 中转站（开源）"),
        ("api2d", "API2D 中转站（商业）"),
        ("aihubmix", "AiHubMix 中转站"),
        ("cloudflare", "Cloudflare Workers 自建"),
        ("custom_header", "自定义 HTTP 头认证"),
        ("query_mode", "Query 参数模式"),
    ]

    for i, (key, desc) in enumerate(templates, 1):
        print(f"  {i}. {desc} ({key})")

    print()


def get_user_input(prompt: str, default: str = "") -> str:
    """获取用户输入"""
    if default:
        user_input = input(f"{prompt} [{default}]: ").strip()
        return user_input if user_input else default
    else:
        return input(f"{prompt}: ").strip()


def configure_gateway(template_key: str) -> dict[str, Any]:
    """配置中转站"""
    template = GATEWAY_TEMPLATES.get(template_key, {}).copy()

    if not template:
        print(f"错误：未找到模板 '{template_key}'")
        return {}

    print(f"\n配置 {template.get('name', '中转站')}")
    print("-" * 60)

    # 必填项
    endpoint = get_user_input("端点 URL", template.get("endpoint", ""))
    api_key = get_user_input("API Key")
    model = get_user_input("模型名称", template.get("model", ""))

    template["endpoint"] = endpoint
    template["api_key"] = api_key
    template["model"] = model

    # 可选项
    print("\n高级配置（直接回车使用默认值）：")
    timeout_input = get_user_input(f"超时时间（秒）", str(template.get("timeout", 90)))
    retry_count_input = get_user_input(f"重试次数", str(template.get("retry_count", 3)))

    try:
        template["timeout"] = int(timeout_input)
        template["retry_count"] = int(retry_count_input)
    except ValueError:
        pass

    return template


def save_config(config: dict[str, Any], filepath: str = None):
    """保存配置到文件"""
    if filepath is None:
        filepath = "gateway_config.json"

    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    print(f"\n配置已保存到: {filepath}")


def display_config(config: dict[str, Any]):
    """显示配置"""
    print("\n生成的配置：")
    print("-" * 60)

    # 隐藏 API Key
    display_config = config.copy()
    if "api_key" in display_config and display_config["api_key"]:
        key = display_config["api_key"]
        display_config["api_key"] = f"{key[:10]}...{key[-6:]}" if len(key) > 16 else "***"

    print(json.dumps(display_config, ensure_ascii=False, indent=2))
    print("-" * 60)


def interactive_mode():
    """交互式配置"""
    print_banner()
    print_templates()

    choice = get_user_input("请选择模板编号或输入模板 key")

    # 处理数字输入
    template_keys = list(GATEWAY_TEMPLATES.keys())
    if choice.isdigit():
        idx = int(choice) - 1
        if 0 <= idx < len(template_keys):
            choice = template_keys[idx]

    if choice not in GATEWAY_TEMPLATES:
        print(f"\n错误：无效的选择 '{choice}'")
        return

    config = configure_gateway(choice)

    if not config:
        return

    display_config(config)

    # 确认保存
    save_choice = get_user_input("\n是否保存配置？(y/n)", "y")
    if save_choice.lower() in ["y", "yes", ""]:
        filename = get_user_input("保存文件名", "gateway_config.json")
        save_config(config, filename)

        print("\n提示：")
        print("1. 请将此配置添加到应用的 config.json 的 providers 数组中")
        print("2. 或在应用界面的'服务商管理'中手动添加")
        print("3. 记得在实际使用前填写正确的 API Key")


def quick_config(template_key: str, endpoint: str, api_key: str, model: str = None):
    """快速配置（命令行模式）"""
    template = GATEWAY_TEMPLATES.get(template_key, {}).copy()

    if not template:
        print(f"错误：未找到模板 '{template_key}'")
        return None

    template["endpoint"] = endpoint
    template["api_key"] = api_key

    if model:
        template["model"] = model

    return template


def main():
    """主函数"""
    import sys

    if len(sys.argv) > 1:
        # 命令行模式
        if sys.argv[1] == "list":
            print_banner()
            print_templates()
        elif sys.argv[1] == "quick" and len(sys.argv) >= 5:
            # python gateway_config_helper.py quick oneapi https://... sk-xxx gpt-4o
            template_key = sys.argv[2]
            endpoint = sys.argv[3]
            api_key = sys.argv[4]
            model = sys.argv[5] if len(sys.argv) > 5 else None

            config = quick_config(template_key, endpoint, api_key, model)
            if config:
                display_config(config)
                save_config(config, f"{template_key}_config.json")
        else:
            print("用法:")
            print("  交互模式: python gateway_config_helper.py")
            print("  列出模板: python gateway_config_helper.py list")
            print("  快速配置: python gateway_config_helper.py quick <template> <endpoint> <api_key> [model]")
    else:
        # 交互模式
        interactive_mode()


if __name__ == "__main__":
    main()
