from __future__ import annotations

import base64
import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable
from urllib.parse import quote_plus, urlencode

import requests

from image_tools import image_to_base64
from models import AppConfig, GradeResult, Provider, provider_for_role
from ollama_discovery import discover_ollama


# AI 模块复刻脚本的结构化提示词、解析器、双评和仲裁逻辑。


StreamCallback = Callable[[str], None]

_tls = threading.local()
_material_cache: dict[tuple[str, float], str] = {}
_material_lock = threading.Lock()


def http_session() -> requests.Session:
    """每个线程复用一个 Session，Keep-Alive 少一次握手，双评并行时也互不抢连接。"""
    session = getattr(_tls, "session", None)
    if session is None:
        session = requests.Session()
        _tls.session = session
    return session


def _image_mime_from_b64(image_b64: str) -> str:
    snippet = (image_b64 or "")[:64]
    pad = (-len(snippet)) % 4
    try:
        raw = base64.b64decode(snippet + ("=" * pad), validate=False)
    except Exception:
        raw = b""
    if raw.startswith(b"\x89PNG"):
        return "image/png"
    if raw.startswith(b"\xff\xd8"):
        return "image/jpeg"
    return "image/jpeg"


def _field_text(value: str) -> str:
    return value.strip() if value else ""


def _context_text(config: AppConfig) -> str:
    parts = []
    if _field_text(config.grade_level):
        parts.append(f"年级：{config.grade_level}")
    if _field_text(config.subject):
        parts.append(f"学科：{config.subject}")
    if _field_text(config.question_type):
        parts.append(f"题型：{config.question_type}")
    return "\n".join(parts)


def use_compact_scoring(config: AppConfig) -> bool:
    # 连续批改只要分数和很短依据，减少模型输出时间；详细复述留给单次查看。
    return True


def scoring_max_tokens(config: AppConfig) -> int:
    if use_compact_scoring(config):
        return 384
    return 2048


def build_prompt(config: AppConfig, student_text: str | None = None) -> str:
    max_score = config.scoring.max_score
    if config.scoring.units:
        max_score = sum(u.max_score for u in config.scoring.units)
    compact = use_compact_scoring(config)
    if student_text is None:
        prompt = "你是一位严格的阅卷老师。请只根据截图中识别框内的学生答案进行 OCR 和评分。\n\n===== 输入信息 ====="
    else:
        prompt = "你是一位严格的阅卷老师。学生答案已经由 OCR 模型识别，请根据识别文本评分；无法确认的文字按不确定处理，不要擅自补全。\n\n===== 输入信息 ====="
        prompt += f"\n【学生答案OCR文本】\n{student_text.strip() or '未能识别'}"
    context = _context_text(config)
    if context:
        prompt += f"\n【题目信息】\n{context}"
    if _field_text(config.question):
        prompt += f"\n【题目】\n{config.question}"
    if _field_text(config.answer):
        prompt += f"\n【标准答案】\n{config.answer}"
    if _field_text(config.rubric):
        prompt += f"\n【评分标准】\n{config.rubric}"
    prompt += f"\n【满分】\n满分{max_score:g}分"
    if config.scoring.units:
        prompt += "\n【分小题】"
        for unit in config.scoring.units:
            prompt += f"\n{unit.label}: 满分{unit.max_score:g}分"
    if compact:
        prompt += "\n\n===== 输出要求 =====\n严格按以下格式输出，内容尽量短：\n\n【答案复述】\n一句话概括学生答案。\n\n【评分依据】\n一两句说明对错。\n\n【得分】\n一个数字。"
        if config.scoring.units:
            for unit in config.scoring.units:
                prompt += f"\n\n{unit.label}分数：一个数字"
        prompt += "\n\n===== 重要约束 =====\n1. 被划掉、涂改、涂抹覆盖的内容视为无效，只评判最终保留的答案。\n2. 无法识别时【答案复述】写“未能识别”，【得分】写 0。\n3. 【得分】必须只包含数字。"
        return prompt
    prompt += "\n\n===== 输出要求 =====\n你必须严格按照以下格式输出，不得添加其他段落：\n\n【答案复述】\n逐条列出学生答案要点。\n\n【评分依据】\n逐项说明得分和扣分点。\n\n【分数计算】\n写出计算公式。"
    if config.scoring.units:
        for unit in config.scoring.units:
            prompt += f"\n\n{unit.label}分数：一个数字\n{unit.label}评语：简短说明"
    prompt += "\n\n【得分】\n一个数字，可以是小数。"
    prompt += "\n\n===== 重要约束 =====\n1. 被划掉、涂改、涂抹覆盖的内容视为无效，只评判最终保留的答案。\n2. 如果无法识别学生答案，在【答案复述】写“未能识别”。\n3. 【得分】必须只包含数字。"
    return prompt


def build_ocr_prompt(config: AppConfig) -> str:
    context = _context_text(config)
    prompt = "请只识别截图中答题卡识别框内的学生手写或打印答案，忽略打分框、提交按钮、网页导航和无关内容。"
    if context:
        prompt += f"\n题目背景：\n{context}"
    prompt += "\n输出要求：只输出识别到的学生答案文本；如果完全无法识别，输出“未能识别”。"
    return prompt


def _image_content_from_b64(image_b64: str) -> dict[str, Any]:
    mime = _image_mime_from_b64(image_b64)
    return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}}


def _material_image_b64s(config: AppConfig) -> list[str]:
    # 评分材料图片来自用户手动添加的题目/答案/评分标准截图，只作为参考材料发送。
    values: list[str] = []
    for path in config.material_images:
        try:
            file_path = Path(path)
            mtime = file_path.stat().st_mtime
            key = (str(file_path.resolve()), mtime)
            with _material_lock:
                cached = _material_cache.get(key)
                if cached is not None:
                    values.append(cached)
                    continue
                data = file_path.read_bytes()
                encoded = base64.b64encode(data).decode("ascii")
                _material_cache[key] = encoded
            values.append(encoded)
        except Exception:
            continue
    return values


def _append_query_api_key(url: str, provider: Provider) -> str:
    key_field = provider.api_key_field or "api_key"
    separator = "&" if "?" in url else "?"
    return f"{url}{separator}{urlencode({key_field: provider.get_api_key_value()})}"


def _redact_provider_secret(text: Any, provider: Provider) -> str:
    value = "" if text is None else str(text)
    secrets = {provider.api_key, provider.get_api_key_value()}
    secrets.update(quote_plus(secret) for secret in list(secrets) if secret)
    for secret in sorted((s for s in secrets if s), key=len, reverse=True):
        value = value.replace(secret, "***")
    return value


def models_url_from_endpoint(endpoint: str) -> str:
    """把聊天/Responses 端点换成 OpenAI 兼容的 /models 列表地址。"""
    url = (endpoint or "").strip().rstrip("/")
    if not url:
        return ""
    if url.endswith("/chat/completions"):
        return url[: -len("/chat/completions")] + "/models"
    if url.endswith("/completions"):
        return url[: -len("/completions")] + "/models"
    if url.endswith("/v1/responses"):
        return url[: -len("/responses")] + "/models"
    if url.endswith("/responses"):
        return url[: -len("/responses")] + "/models"
    if url.endswith("/models"):
        return url
    if url.endswith("/v1"):
        return url + "/models"
    return url + "/v1/models"


def _strip_known_api_suffix(endpoint: str) -> str:
    """去掉常见调用路径，只留下网关根地址。"""
    url = (endpoint or "").strip().rstrip("/")
    suffixes = (
        "/v1/chat/completions",
        "/chat/completions",
        "/v1/responses",
        "/responses",
        "/v1/models",
        "/models",
        "/completions",
    )
    for suffix in suffixes:
        if url.endswith(suffix):
            return url[: -len(suffix)].rstrip("/")
    return url


def candidate_models_urls(endpoint: str) -> list[str]:
    """按兼容性顺序给出模型列表地址，裸域名优先试 /v1/models。"""
    primary = models_url_from_endpoint(endpoint)
    urls: list[str] = []
    if primary:
        urls.append(primary)
    base = _strip_known_api_suffix(endpoint)
    if base.endswith("/v1"):
        base = base[: -len("/v1")].rstrip("/")
    for candidate in ((f"{base}/v1/models", f"{base}/models") if base else ()):
        if candidate not in urls:
            urls.append(candidate)
    return urls


def detect_api_format(provider: Provider) -> str:
    """识别上游该走 Responses 还是 Chat Completions。"""
    forced = (getattr(provider, "api_format", "") or "").strip().lower()
    if forced in {"responses", "chat_completions"}:
        return forced
    url = (provider.endpoint or "").strip().rstrip("/").lower()
    if url.endswith("/chat/completions") or "/chat/completions" in url:
        return "chat_completions"
    if url.endswith("/responses") or "/responses" in url:
        return "responses"
    return "responses"


def request_url_for_format(endpoint: str, api_format: str) -> str:
    """按上游格式补全实际请求地址。"""
    url = (endpoint or "").strip().rstrip("/")
    fmt = (api_format or "").strip().lower()
    if fmt == "responses":
        if url.endswith("/responses"):
            return url
        if url.endswith("/v1"):
            return url + "/responses"
        base = _strip_known_api_suffix(url)
        if base.endswith("/v1"):
            return base + "/responses"
        return (base or url) + "/v1/responses"
    if fmt == "chat_completions":
        if url.endswith("/chat/completions"):
            return url
        if url.endswith("/v1"):
            return url + "/chat/completions"
        base = _strip_known_api_suffix(url)
        if base.endswith("/v1"):
            return base + "/chat/completions"
        return (base or url) + "/v1/chat/completions"
    return url


def _responses_image_content(image_b64: str) -> dict[str, Any]:
    mime = _image_mime_from_b64(image_b64)
    return {"type": "input_image", "image_url": f"data:{mime};base64,{image_b64}"}


def _text_from_responses_payload(data: Any) -> str:
    """从 OpenAI Responses 结果里抽出文本。"""
    if not isinstance(data, dict):
        return ""
    text = data.get("output_text")
    if isinstance(text, str) and text.strip():
        return text
    parts: list[str] = []
    for item in data.get("output") or []:
        if isinstance(item, str) and item.strip():
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        if item.get("type") in {"output_text", "text"} and item.get("text"):
            parts.append(str(item.get("text") or ""))
            continue
        for content in item.get("content") or []:
            if not isinstance(content, dict):
                continue
            if content.get("type") in {"output_text", "text"} and content.get("text"):
                parts.append(str(content.get("text") or ""))
    return "".join(parts)


def _model_ids_from_payload(payload: Any) -> list[str]:
    items: list[Any]
    if isinstance(payload, dict):
        if isinstance(payload.get("data"), list):
            items = payload["data"]
        elif isinstance(payload.get("models"), list):
            items = payload["models"]
        else:
            items = []
    elif isinstance(payload, list):
        items = payload
    else:
        items = []
    names: list[str] = []
    for item in items:
        if isinstance(item, str):
            name = item.strip()
        elif isinstance(item, dict):
            name = str(item.get("id") or item.get("name") or item.get("model") or "").strip()
        else:
            name = ""
        if name and name not in names:
            names.append(name)
    return names


def list_provider_models(provider: Provider) -> list[str]:
    """按当前端点和 API Key 拉取该服务商可用模型，再给用户下拉选择。"""
    if provider.protocol == "ollama":
        discovery = discover_ollama(provider.endpoint)
        if not discovery.running:
            raise RuntimeError(discovery.error or "Ollama 未运行")
        if not discovery.installed_models:
            raise RuntimeError("Ollama 已启动，但没有检测到已安装模型。请先执行 ollama pull。")
        return list(discovery.installed_models)
    if provider.requires_api_key and not provider.api_key:
        raise RuntimeError("请先填写 API Key")
    urls = candidate_models_urls(provider.endpoint)
    if not urls:
        raise RuntimeError("请先填写 API 端点")
    last_error: Exception | None = None
    for url in urls:
        request_url = url
        if provider.api_key_location == "query" and provider.api_key:
            request_url = _append_query_api_key(url, provider)
        try:
            response = http_session().get(request_url, headers=provider.build_headers(), timeout=min(provider.timeout or 30, 30))
        except Exception as exc:
            last_error = RuntimeError(f"获取模型失败: {_redact_provider_secret(exc, provider)}")
            continue
        status = getattr(response, "status_code", 0)
        if status < 200 or status >= 300:
            error_msg = _redact_provider_secret(getattr(response, "text", "")[:500], provider)
            last_error = RuntimeError(f"获取模型失败 {status}: {error_msg}")
            continue
        raw = getattr(response, "text", None)
        if raw is not None and not str(raw).strip():
            last_error = RuntimeError("模型列表解析失败: Expecting value: line 1 column 1 (char 0)")
            continue
        try:
            payload = response.json()
        except Exception as exc:
            last_error = RuntimeError(f"模型列表解析失败: {_redact_provider_secret(exc, provider)}")
            continue
        models = _model_ids_from_payload(payload)
        if models:
            return models
        last_error = RuntimeError("该端点没有返回可用模型")
    if last_error:
        raise last_error
    raise RuntimeError("该端点没有返回可用模型")


def _ollama_message(prompt: str, image_b64: str | None = None, extra_image_b64s: list[str] | None = None) -> dict[str, Any]:
    message: dict[str, Any] = {"role": "user", "content": prompt}
    images = [image for image in (extra_image_b64s or []) if image]
    if image_b64:
        images.append(image_b64)
    if images:
        message["images"] = images
    return message


def _call_ollama(provider: Provider, prompt: str, image_b64: str | None = None, on_stream: StreamCallback | None = None, extra_image_b64s: list[str] | None = None, max_tokens: int | None = None) -> str:
    body: dict[str, Any] = {
        "model": provider.model,
        "messages": [_ollama_message(prompt, image_b64, extra_image_b64s)],
        "stream": True,
    }
    if max_tokens:
        body["options"] = {"num_predict": max_tokens}
    body.update(provider.extra_body_params)
    try:
        response = http_session().post(
            provider.endpoint,
            headers=provider.build_headers(),
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            timeout=provider.timeout,
            stream=True,
        )
    except Exception as exc:
        raise RuntimeError(f"Ollama 调用失败: {_redact_provider_secret(exc, provider)}") from exc

    if response.status_code < 200 or response.status_code >= 300:
        error_msg = _redact_provider_secret(response.text[:500], provider)
        raise RuntimeError(f"Ollama API 报错 {response.status_code}: {error_msg}")

    parts: list[str] = []
    try:
        for raw_line in response.iter_lines():
            if not raw_line:
                continue
            line = raw_line.decode("utf-8") if isinstance(raw_line, bytes) else str(raw_line)
            chunk = json.loads(line)
            text = chunk.get("message", {}).get("content", "")
            if text:
                parts.append(text)
                if on_stream:
                    on_stream(text)
            if chunk.get("done"):
                break
    except Exception as exc:
        raise RuntimeError(f"Ollama 响应解析失败: {_redact_provider_secret(exc, provider)}") from exc
    return "".join(parts)


def _chat_content(prompt: str, image_b64: str | None = None, extra_image_b64s: list[str] | None = None) -> list[dict[str, Any]]:
    content = [{"type": "text", "text": prompt}]
    for extra in extra_image_b64s or []:
        content.append(_image_content_from_b64(extra))
    if image_b64:
        content.append(_image_content_from_b64(image_b64))
    return content


def _responses_input_content(prompt: str, image_b64: str | None = None, extra_image_b64s: list[str] | None = None) -> list[dict[str, Any]]:
    content = [{"type": "input_text", "text": prompt}]
    for extra in extra_image_b64s or []:
        content.append(_responses_image_content(extra))
    if image_b64:
        content.append(_responses_image_content(image_b64))
    return content


def _openai_request_body(provider: Provider, prompt: str, image_b64: str | None, extra_image_b64s: list[str] | None, api_format: str, max_tokens: int = 2048) -> dict[str, Any]:
    if api_format == "responses":
        body: dict[str, Any] = {
            "model": provider.model,
            "input": [{"role": "user", "content": _responses_input_content(prompt, image_b64, extra_image_b64s)}],
            "max_output_tokens": max_tokens,
            "stream": False,
        }
        if provider.reasoning_effort:
            body["reasoning"] = {"effort": provider.reasoning_effort}
    else:
        body = {
            "model": provider.model,
            "messages": [{"role": "user", "content": _chat_content(prompt, image_b64, extra_image_b64s)}],
            "max_tokens": max_tokens,
            "stream": False,
        }
        if provider.reasoning_effort:
            body["reasoning_effort"] = provider.reasoning_effort
    body.update(provider.extra_body_params)
    if provider.api_key_location == "body" and provider.api_key:
        key_field = provider.api_key_field or "api_key"
        body[key_field] = provider.get_api_key_value()
    return body


def _text_from_chat_payload(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    return data.get("choices", [{}])[0].get("message", {}).get("content", "") or ""


def _should_switch_to_chat_completions(api_format: str, error_text: str) -> bool:
    if api_format != "responses":
        return False
    lowered = (error_text or "").lower()
    return "chat/completions" in lowered or "model_not_supported_on_endpoint" in lowered


def _should_remap_reasoning_effort(error_text: str, current: str) -> str | None:
    current = (current or "").strip().lower()
    if current in {"low", "high", "max"}:
        return None
    text = error_text or ""
    lowered = text.lower()
    if "始终思考" in text or "请使用 low" in text or "low、high 或 max" in text or "low, high" in lowered:
        return "low"
    return None


def call_openai_compatible(provider: Provider, prompt: str, image_b64: str | None = None, on_stream: StreamCallback | None = None, extra_image_b64s: list[str] | None = None, max_tokens: int | None = None) -> str:
    if provider.protocol == "ollama":
        return _call_ollama(provider, prompt, image_b64, on_stream, extra_image_b64s, max_tokens)
    if provider.requires_api_key and not provider.api_key:
        raise RuntimeError("请先填写 API Key")

    from dataclasses import replace

    working = replace(provider)
    api_format = detect_api_format(working)
    switched_format = False
    remapped_effort = False

    last_error = None
    retry_count = working.retry_count if working.retry_enabled else 1

    for attempt in range(retry_count):
        try:
            while True:
                body = _openai_request_body(working, prompt, image_b64, extra_image_b64s, api_format, max_tokens=max_tokens or 2048)
                headers = working.build_headers()
                url = request_url_for_format(working.endpoint, api_format)
                if working.api_key_location == "query" and working.api_key:
                    url = _append_query_api_key(url, working)
                response = http_session().post(
                    url,
                    headers=headers,
                    data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                    timeout=working.timeout,
                )
                if response.status_code < 200 or response.status_code >= 300:
                    error_msg = _redact_provider_secret(response.text[:500], working)
                    if not switched_format and _should_switch_to_chat_completions(api_format, error_msg):
                        api_format = "chat_completions"
                        switched_format = True
                        continue
                    remapped = _should_remap_reasoning_effort(error_msg, working.reasoning_effort)
                    if remapped and not remapped_effort:
                        working = replace(working, reasoning_effort=remapped)
                        remapped_effort = True
                        continue
                    raise RuntimeError(f"API 报错 {response.status_code}: {error_msg}")
                data = response.json()
                text = _text_from_responses_payload(data) if api_format == "responses" else _text_from_chat_payload(data)
                if on_stream:
                    on_stream(text)
                return text
        except Exception as e:
            last_error = e
            if attempt < retry_count - 1:
                import time
                time.sleep(working.retry_delay)
            else:
                error_msg = _redact_provider_secret(last_error, working)
                raise RuntimeError(f"API 调用失败（已重试 {retry_count} 次）: {error_msg}")


def test_provider(provider: Provider, message: str = "请只回复：连接成功") -> str:
    # 服务商测试不带图片，便于快速验证 endpoint、key、model 是否可用。
    if provider.protocol == "ollama":
        body: dict[str, Any] = {
            "model": provider.model,
            "messages": [_ollama_message(message)],
            "stream": False,
        }
        body.update(provider.extra_body_params)
        try:
            response = http_session().post(
                provider.endpoint,
                headers=provider.build_headers(),
                data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                timeout=30,
            )
        except Exception as exc:
            raise RuntimeError(f"Ollama 调用失败: {_redact_provider_secret(exc, provider)}") from exc
        if response.status_code < 200 or response.status_code >= 300:
            error_msg = _redact_provider_secret(response.text[:500], provider)
            raise RuntimeError(f"Ollama API 报错 {response.status_code}: {error_msg}")
        return response.json().get("message", {}).get("content", "").strip() or "连接成功"
    text = call_openai_compatible(provider, message)
    return (text or "").strip() or "连接成功"


test_provider.__test__ = False


def extract_score(text: str | None, max_score: float) -> float | None:
    if not text:
        return None
    match = re.search(r"-?\d+(?:\.\d+)?", text)
    if not match:
        return None
    value = float(match.group(0))
    return min(max(value, 0), max_score if max_score > 0 else 999)


def parse_response(text: str, config: AppConfig) -> GradeResult:
    sections: dict[str, str] = {}
    for match in re.finditer(r"【([^】]+)】\s*([\s\S]*?)(?=【|$)", text):
        sections[match.group(1).strip()] = match.group(2).strip()
    max_score = config.scoring.max_score
    if config.scoring.units:
        max_score = sum(u.max_score for u in config.scoring.units)
    score = extract_score(sections.get("得分") or sections.get("最终得分") or sections.get("总分"), max_score)
    if score is None:
        legacy = re.search(r"(?:分数|得分|总分)[：:]\s*(-?\d+(?:\.\d+)?)", text)
        if legacy:
            score = min(max(float(legacy.group(1)), 0), max_score)
    sub_scores = []
    for unit in config.scoring.units:
        unit_score = extract_score(sections.get(f"{unit.label}分数"), unit.max_score)
        comment = sections.get(f"{unit.label}评语", "")
        if unit_score is not None:
            sub_scores.append({"label": unit.label, "score": unit_score, "maxScore": unit.max_score, "comment": comment})
    diligence_level = 0
    diligence_reason = ""
    if sections.get("勤勉度"):
        level_match = re.search(r"等级[：:]\s*(\d)", sections["勤勉度"])
        if level_match:
            diligence_level = min(max(int(level_match.group(1)), 1), 5)
        reason_match = re.search(r"依据[：:]\s*(.+)", sections["勤勉度"])
        if reason_match:
            diligence_reason = reason_match.group(1).strip()
    return GradeResult(
        student_answer=sections.get("答案复述", "未能识别"),
        score=score,
        raw_score=score,
        comment=sections.get("评分依据", text),
        scoring_basis=sections.get("评分依据", ""),
        calculation=sections.get("分数计算", ""),
        diligence_level=diligence_level,
        diligence_reason=diligence_reason,
        sub_scores=sub_scores,
        sections=sections,
    )


def recognize_image(config: AppConfig, image, provider: Provider, on_stream: StreamCallback | None = None) -> str:
    raw = call_openai_compatible(provider, build_ocr_prompt(config), image_to_base64(image), on_stream, extra_image_b64s=None, max_tokens=256)
    return raw.strip() or "未能识别"


def grade_image(config: AppConfig, image, provider: Provider, on_stream: StreamCallback | None = None, student_text: str | None = None) -> GradeResult:
    prompt = build_prompt(config, student_text)
    max_tokens = scoring_max_tokens(config)
    if student_text is None:
        raw = call_openai_compatible(provider, prompt, image_to_base64(image), on_stream, _material_image_b64s(config), max_tokens=max_tokens)
    else:
        # OCR 先行模式面向纯文本评分：先识别文字，再只传识别文本，不再传截图。
        raw = call_openai_compatible(provider, prompt, None, on_stream, None, max_tokens=max_tokens)
    return parse_response(raw, config)


def grade_with_optional_ocr(config: AppConfig, image, provider: Provider, on_stream: StreamCallback | None = None) -> GradeResult:
    if config.workflow.recognition_mode != "ocr_first":
        return grade_image(config, image, provider, on_stream)
    student_text = recognize_image(config, image, provider_for_role(config, "ocr"), on_stream)
    if on_stream:
        on_stream(f"\n\n【OCR结果】\n{student_text}\n")
    result = grade_image(config, image, provider, on_stream, student_text=student_text)
    result.student_answer = result.student_answer if result.student_answer and result.student_answer != "未能识别" else student_text
    return result


def build_arbitration_prompt(config: AppConfig, a: GradeResult, b: GradeResult) -> str:
    return (
        "你是阅卷仲裁专家。两位老师对同一份试卷评分有分歧，请独立审阅截图后裁定。\n\n"
        f"老师A评分：{a.score}，依据：{a.comment}\n"
        f"老师B评分：{b.score}，依据：{b.comment}\n\n"
        f"题目：{config.question}\n标准答案：{config.answer}\n评分标准：{config.rubric}\n\n"
        "严格按以下格式输出：\n【答案复述】\n...\n【独立评分依据】\n...\n【仲裁分析】\n...\n【最终得分】\n一个数字"
    )


def grade_dual(config: AppConfig, image, provider: Provider, on_stream: StreamCallback | None = None) -> GradeResult:
    if not config.workflow.dual_enabled:
        return grade_with_optional_ocr(config, image, provider, on_stream)
    # 主评和副评同时打，仲裁仍等两边都回来后再做。
    first_image = image.copy() if hasattr(image, "copy") else image
    second_image = image.copy() if hasattr(image, "copy") else image
    with ThreadPoolExecutor(max_workers=2) as pool:
        first_future = pool.submit(grade_with_optional_ocr, config, first_image, provider, on_stream)
        second_future = pool.submit(grade_with_optional_ocr, config, second_image, provider_for_role(config, "secondary"), None)
        first = first_future.result()
        second = second_future.result()
    if first.score is None:
        return second
    if second.score is None:
        return first
    score_a, score_b = first.score, second.score
    diff = abs(score_a - score_b)
    if diff <= config.workflow.dual_threshold:
        final = first
        final.score = round((score_a + score_b) / 2, 2)
        final.raw_score = final.score
        final.dual_eval = {"scoreA": score_a, "scoreB": score_b, "diff": diff, "result": "共识"}
        return final
    if not config.workflow.arbitration_enabled:
        score_a, score_b = first.score, second.score
        first.score = round((score_a + score_b) / 2, 2)
        first.raw_score = first.score
        first.dual_eval = {"scoreA": score_a, "scoreB": score_b, "diff": diff, "result": "未启用仲裁，取平均"}
        return first
    prompt = build_arbitration_prompt(config, first, second)
    if config.workflow.recognition_mode == "ocr_first":
        raw = call_openai_compatible(provider_for_role(config, "arbitration"), prompt, None, on_stream, None)
    else:
        raw = call_openai_compatible(provider_for_role(config, "arbitration"), prompt, image_to_base64(image), on_stream, _material_image_b64s(config))
    arb = parse_response(raw, config)
    arb.dual_eval = {"scoreA": first.score, "scoreB": second.score, "diff": diff, "result": "仲裁", "arbScore": arb.score}
    return arb
