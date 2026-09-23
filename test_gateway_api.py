#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
中转站 API 功能测试脚本

测试新增的 Provider 配置功能是否正常工作
"""

from models import Provider
from ai_client import _append_query_api_key, _redact_provider_secret


def test_basic_provider():
    """测试基础 Provider 功能"""
    print("=" * 60)
    print("测试 1: 基础 Provider（默认配置）")
    print("=" * 60)

    provider = Provider(
        name="测试服务商",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="sk-test-key-12345",
        model="gpt-4o"
    )

    print(f"服务商名称: {provider.name}")
    print(f"端点: {provider.endpoint}")
    print(f"模型: {provider.model}")
    print(f"API Key 位置: {provider.api_key_location}")
    print(f"API Key 前缀: '{provider.api_key_prefix}'")
    print(f"超时时间: {provider.timeout}s")
    print(f"重试启用: {provider.retry_enabled}")
    print(f"重试次数: {provider.retry_count}")
    print()

    # 测试方法
    headers = provider.build_headers()
    print("生成的请求头:")
    for key, value in headers.items():
        if key == "Authorization":
            # 隐藏完整的 key
            print(f"  {key}: Bearer sk-***{value[-8:]}")
        else:
            print(f"  {key}: {value}")
    print()


def test_custom_headers():
    """测试自定义 HTTP 头"""
    print("=" * 60)
    print("测试 2: 自定义 HTTP 头")
    print("=" * 60)

    provider = Provider(
        name="自定义头服务商",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="custom-key-abc",
        model="gpt-4o",
        custom_headers={
            "X-Project-ID": "project-123",
            "X-User-Agent": "GradingSystem/2.0"
        }
    )

    headers = provider.build_headers()
    print("生成的请求头:")
    for key, value in headers.items():
        if "key" in key.lower() or "auth" in key.lower():
            print(f"  {key}: ***{value[-8:]}")
        else:
            print(f"  {key}: {value}")
    print()


def test_no_prefix():
    """测试无前缀的 API Key"""
    print("=" * 60)
    print("测试 3: 无前缀 API Key")
    print("=" * 60)

    provider = Provider(
        name="无前缀服务商",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="plain-key-without-prefix",
        model="gpt-4o",
        api_key_prefix=""  # 无前缀
    )

    key_value = provider.get_api_key_value()
    print(f"API Key 值: {key_value[:10]}...{key_value[-8:]}")
    print(f"是否包含 'Bearer': {key_value.startswith('Bearer')}")
    print()


def test_custom_key_field():
    """测试自定义 API Key 字段名"""
    print("=" * 60)
    print("测试 4: 自定义 API Key 字段名")
    print("=" * 60)

    provider = Provider(
        name="自定义字段服务商",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="custom-key-xyz",
        model="gpt-4o",
        api_key_field="X-API-Key",  # 自定义字段名
        api_key_prefix=""
    )

    header_name = provider.get_api_key_header_name()
    print(f"API Key 字段名: {header_name}")

    headers = provider.build_headers()
    print("生成的请求头:")
    for key, value in headers.items():
        if "key" in key.lower():
            print(f"  {key}: ***{value[-8:]}")
        else:
            print(f"  {key}: {value}")
    print()


def test_query_mode():
    """测试 Query 参数模式"""
    print("=" * 60)
    print("测试 5: Query 参数模式")
    print("=" * 60)

    provider = Provider(
        name="Query模式服务商",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="query-key-123",
        model="gpt-4o",
        api_key_location="query",  # Query 模式
        api_key_field="apikey",
        api_key_prefix=""
    )

    print(f"API Key 位置: {provider.api_key_location}")
    print(f"Query 参数名: {provider.api_key_field}")

    # 模拟 URL 构建
    url = provider.endpoint
    key_field = provider.api_key_field or "api_key"
    separator = "&" if "?" in url else "?"
    full_url = f"{url}{separator}{key_field}={provider.get_api_key_value()}"

    # 隐藏 key 显示
    safe_url = full_url.replace(provider.api_key, "***" + provider.api_key[-8:])
    print(f"生成的 URL: {safe_url}")
    print()


def test_body_mode():
    """测试 Body 参数模式"""
    print("=" * 60)
    print("测试 6: Body 参数模式")
    print("=" * 60)

    provider = Provider(
        name="Body模式服务商",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="body-key-456",
        model="gpt-4o",
        api_key_location="body",  # Body 模式
        api_key_field="apiKey"
    )

    print(f"API Key 位置: {provider.api_key_location}")
    print(f"Body 参数名: {provider.api_key_field}")
    print(f"说明: API Key 将被添加到请求体中")
    print()


def test_extra_params():
    """测试额外请求参数"""
    print("=" * 60)
    print("测试 7: 额外请求参数")
    print("=" * 60)

    provider = Provider(
        name="额外参数服务商",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="test-key-789",
        model="gpt-4o",
        extra_body_params={
            "temperature": 0.7,
            "top_p": 0.9,
            "user": "grading-system"
        }
    )

    print("额外的请求体参数:")
    for key, value in provider.extra_body_params.items():
        print(f"  {key}: {value}")
    print()


def test_retry_config():
    """测试重试配置"""
    print("=" * 60)
    print("测试 8: 重试配置")
    print("=" * 60)

    provider = Provider(
        name="重试测试服务商",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="retry-key",
        model="gpt-4o",
        timeout=120,
        retry_enabled=True,
        retry_count=5,
        retry_delay=2.0
    )

    print(f"超时时间: {provider.timeout}s")
    print(f"重试启用: {provider.retry_enabled}")
    print(f"重试次数: {provider.retry_count}")
    print(f"重试延迟: {provider.retry_delay}s")
    print()


def test_gateway_types():
    """测试不同类型的中转站"""
    print("=" * 60)
    print("测试 9: 中转站类型")
    print("=" * 60)

    gateways = [
        ("OneAPI", "oneapi"),
        ("NewAPI", "newapi"),
        ("API2D", "api2d"),
    ]

    for name, gateway_type in gateways:
        provider = Provider(
            name=f"{name}中转站",
            endpoint=f"https://{gateway_type}.example.com/v1/chat/completions",
            api_key=f"{gateway_type}-key",
            model="gpt-4o",
            gateway_type=gateway_type
        )

        print(f"  {name}:")
        print(f"    类型: {provider.gateway_type}")
        print(f"    端点: {provider.endpoint}")
    print()


def test_query_key_encoding_and_redaction():
    """测试 Query Key 编码和错误脱敏"""
    print("=" * 60)
    print("测试 10: Query Key 编码和错误脱敏")
    print("=" * 60)

    provider = Provider(
        name="Query安全测试",
        endpoint="https://api.example.com/v1/chat/completions",
        api_key="key with spaces/and+symbols",
        model="gpt-4o",
        api_key_location="query",
        api_key_field="apikey",
        api_key_prefix="",
    )

    url = _append_query_api_key(provider.endpoint, provider)
    assert "key+with+spaces%2Fand%2Bsymbols" in url, "Query API Key 应进行 URL 编码"

    message = f"request failed: {url}"
    redacted = _redact_provider_secret(message, provider)
    assert provider.api_key not in redacted, "原始 API Key 不应出现在错误信息中"
    assert "key+with+spaces%2Fand%2Bsymbols" not in redacted, "编码后的 API Key 不应出现在错误信息中"
    assert "***" in redacted, "错误信息应保留脱敏标记"
    print("Query Key 编码和脱敏正常")
    print()


def main():
    """运行所有测试"""
    print("\n" + "=" * 60)
    print("中转站 API 功能测试")
    print("=" * 60 + "\n")

    tests = [
        test_basic_provider,
        test_custom_headers,
        test_no_prefix,
        test_custom_key_field,
        test_query_mode,
        test_body_mode,
        test_extra_params,
        test_retry_config,
        test_gateway_types,
        test_query_key_encoding_and_redaction,
    ]

    for i, test in enumerate(tests, 1):
        try:
            test()
        except Exception as e:
            print(f"[FAIL] 测试 {i} 失败: {e}\n")
        else:
            print(f"[OK] 测试 {i} 通过\n")

    print("=" * 60)
    print("所有测试完成！")
    print("=" * 60)


if __name__ == "__main__":
    main()
