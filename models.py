from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace
from typing import Any


# 本文件只放数据结构，避免 UI、AI、自动点击逻辑互相耦合。


@dataclass
class RegionBox:
    name: str
    kind: str
    x: int
    y: int
    width: int
    height: int
    color: str
    enabled: bool = True

    def rect(self) -> tuple[int, int, int, int]:
        return (self.x, self.y, self.x + self.width, self.y + self.height)

    def center(self) -> tuple[int, int]:
        return (self.x + self.width // 2, self.y + self.height // 2)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RegionBox":
        return cls(
            name=data.get("name", "未命名"),
            kind=data.get("kind", "recognition"),
            x=int(data.get("x", 100)),
            y=int(data.get("y", 100)),
            width=int(data.get("width", 300)),
            height=int(data.get("height", 180)),
            color=data.get("color", "#2e7d32"),
            enabled=bool(data.get("enabled", True)),
        )


OPERATION_BOX_KINDS = {"recognition", "score", "submit"}


def normalize_operation_boxes(boxes: list[RegionBox]) -> list[RegionBox]:
    """Keep only the first recognition/score/submit box; preserve other kinds."""
    seen: set[str] = set()
    normalized: list[RegionBox] = []
    for box in boxes:
        if box.kind in OPERATION_BOX_KINDS:
            if box.kind in seen:
                continue
            seen.add(box.kind)
        normalized.append(box)
    return normalized


@dataclass
class Provider:
    name: str = "火山引擎"
    endpoint: str = "https://ark.cn-beijing.volces.com/api/v3/chat/completions"
    api_key: str = ""
    model: str = "doubao-seed-2-0-pro-260215"
    reasoning_effort: str = "medium"
    models: list[str] = field(default_factory=list)
    source: str = "network"

    # 中转站 API 支持
    custom_headers: dict[str, str] = field(default_factory=dict)  # 自定义 HTTP 头
    api_key_location: str = "header"  # API Key 位置: header | query | body
    api_key_field: str = ""  # API Key 字段名（空则使用默认）
    api_key_prefix: str = "Bearer "  # API Key 前缀
    timeout: int = 90  # 请求超时（秒）
    retry_enabled: bool = True  # 是否启用重试
    retry_count: int = 3  # 重试次数
    retry_delay: float = 1.0  # 重试延迟（秒）
    extra_body_params: dict[str, Any] = field(default_factory=dict)  # 额外请求参数
    gateway_type: str = ""  # 中转站类型: oneapi | newapi | api2d 等
    protocol: str = "openai_compatible"  # openai_compatible | ollama
    api_format: str = ""  # 上游格式: 空=自动, responses, chat_completions

    @property
    def requires_api_key(self) -> bool:
        return self.protocol != "ollama"

    def available_models(self) -> list[str]:
        # 每个供应商保存自己的模型列表，当前模型不在列表时也保留，避免用户手动输入后丢失。
        values = [m for m in self.models if m]
        if self.model and self.model not in values:
            values.insert(0, self.model)
        return values

    def get_api_key_header_name(self) -> str:
        """获取 API Key 在 HTTP 头中的字段名"""
        if self.api_key_field:
            return self.api_key_field
        return "Authorization" if self.api_key_location == "header" else "X-API-Key"

    def get_api_key_value(self) -> str:
        """获取完整的 API Key 值（包含前缀）"""
        if not self.api_key:
            return ""
        # 如果 key 已包含前缀，不重复添加
        if self.api_key_prefix and not self.api_key.startswith(self.api_key_prefix):
            return f"{self.api_key_prefix}{self.api_key}"
        return self.api_key

    def build_headers(self) -> dict[str, str]:
        """构建完整的 HTTP 请求头"""
        headers = {"Content-Type": "application/json"}
        headers.update(self.custom_headers)

        # 添加 API Key（如果在 header 中）
        if self.api_key_location == "header" and self.api_key:
            header_name = self.get_api_key_header_name()
            headers[header_name] = self.get_api_key_value()

        return headers


DEFAULT_PROVIDER_NAME = "火山引擎"
RETIRED_PRESET_NAMES = {
    "5plus1官方",
    "Ollama 本地",
    "OpenAI兼容",
    "OneAPI中转站",
    "NewAPI中转站",
    "API2D中转站",
}


def default_providers() -> list[Provider]:
    # 预设只保留四家：火山引擎、DeepSeek、智谱、自定义。协议代码仍支持手动新增 Ollama。
    return [
        Provider(
            name="火山引擎",
            endpoint="https://ark.cn-beijing.volces.com/api/v3/chat/completions",
            model="doubao-seed-2-0-pro-260215",
            reasoning_effort="medium",
            models=["doubao-seed-2-0-lite-260428", "doubao-seed-2-0-pro-260215"],
        ),
        Provider(
            name="DeepSeek",
            endpoint="https://api.deepseek.com/v1/chat/completions",
            model="deepseek-chat",
            reasoning_effort="medium",
            models=["deepseek-chat", "deepseek-reasoner"],
        ),
        Provider(
            name="智谱",
            endpoint="https://open.bigmodel.cn/api/paas/v4/chat/completions",
            model="glm-4.5-flash",
            reasoning_effort="medium",
            models=["glm-4.5-flash", "glm-4.5", "glm-4-flash"],
        ),
        Provider(
            name="自定义服务商",
            endpoint="",
            model="",
        ),
    ]


@dataclass
class ScoringUnit:
    label: str
    max_score: float = 0.0
    round_step: float = 1.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ScoringUnit":
        return cls(
            label=data.get("label", "总分"),
            max_score=float(data.get("max_score", 0) or 0),
            round_step=float(data.get("round_step", 1) or 1),
        )


@dataclass
class ScoringSettings:
    max_score: float = 10.0
    round_step: float = 1.0
    round_method: str = "round"
    diligence_enabled: bool = False
    diligence_max_bonus: float = 3.0
    diligence_decay_power: float = 2.0
    diligence_criteria: str = "字数较多且书写较为工整"
    units: list[ScoringUnit] = field(default_factory=list)


@dataclass
class Workflow:
    mode: str = "normal"
    recognition_mode: str = "direct"
    primary_enabled: bool = True
    dual_enabled: bool = False
    arbitration_enabled: bool = True
    dual_threshold: float = 2.0
    primary_provider_name: str = DEFAULT_PROVIDER_NAME
    secondary_provider_name: str = DEFAULT_PROVIDER_NAME
    arbitration_provider_name: str = DEFAULT_PROVIDER_NAME
    primary_model: str = ""
    secondary_model: str = ""
    arbitration_model: str = ""
    ocr_provider_name: str = DEFAULT_PROVIDER_NAME
    ocr_provider: Provider = field(default_factory=Provider)
    secondary_provider: Provider = field(default_factory=Provider)
    arbitration_provider: Provider = field(default_factory=Provider)
    target_count_enabled: bool = False
    target_count: int = 0
    retry_limit: int = 5
    confirm_before_submit: bool = True
    normal_countdown: int = 5
    unattended_countdown: int = 1
    capture_delay: float = 0.15
    scoring_delay: float = 0.0
    next_paper_delay: float = 0.2
    score_switch_mode: str = "single"
    pause_hotkey: str = "F8"  # 连续批改暂停快捷键，仅开始批改后生效
    enable_abnormal_termination: bool = False
    abnormal_termination_count: int = 10
    enable_page_refresh: bool = False
    page_refresh_frequency: int = 20
    page_refresh_hotkey: str = "F5"
    page_refresh_wait_seconds: float = 5.0


@dataclass
class AppConfig:
    active_preset: str = "默认配置"
    active_provider: str = DEFAULT_PROVIDER_NAME
    providers: list[Provider] = field(default_factory=default_providers)
    grade_level: str = "高中"
    subject: str = "生物"
    question_type: str = "填空"
    question: str = ""
    answer: str = ""
    rubric: str = ""
    material_images: list[str] = field(default_factory=list)
    scoring: ScoringSettings = field(default_factory=ScoringSettings)
    workflow: Workflow = field(default_factory=Workflow)
    boxes: list[RegionBox] = field(default_factory=list)
    preprocess_level: int = 1
    recognition_margin: int = 0
    blank_detection_enabled: bool = False
    blank_threshold: float = 0.01
    save_images: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GradeResult:
    student_answer: str = "未能识别"
    score: float | None = None
    raw_score: float | None = None
    comment: str = ""
    scoring_basis: str = ""
    calculation: str = ""
    diligence_level: int = 0
    diligence_reason: str = ""
    sub_scores: list[dict[str, Any]] = field(default_factory=list)
    sections: dict[str, str] = field(default_factory=dict)
    dual_eval: dict[str, Any] | None = None


def provider_from_dict(data: dict[str, Any]) -> Provider:
    return Provider(
        name=data.get("name", "自定义服务商"),
        endpoint=data.get("endpoint", ""),
        api_key=data.get("api_key", ""),
        model=data.get("model", ""),
        reasoning_effort=data.get("reasoning_effort", ""),
        models=[str(x).strip() for x in data.get("models", []) if str(x).strip()],
        source=data.get("source", "network"),
        # 中转站 API 支持字段
        custom_headers=dict(data.get("custom_headers", {})),
        api_key_location=data.get("api_key_location", "header"),
        api_key_field=data.get("api_key_field", ""),
        api_key_prefix=data.get("api_key_prefix", "Bearer "),
        timeout=int(data.get("timeout", 90)),
        retry_enabled=bool(data.get("retry_enabled", True)),
        retry_count=int(data.get("retry_count", 3)),
        retry_delay=float(data.get("retry_delay", 1.0)),
        extra_body_params=dict(data.get("extra_body_params", {})),
        gateway_type=data.get("gateway_type", ""),
        protocol=data.get("protocol", "openai_compatible"),
        api_format=str(data.get("api_format", "") or ""),
    )



def _normalize_pause_hotkey(value: Any) -> str:
    """把用户填写的快捷键整理成 Ctrl+Shift+P 这种格式，非法则回退 F8。"""
    from hotkeys import normalize_hotkey
    return normalize_hotkey(str(value or ""))


def _normalize_page_refresh_hotkey(value: Any) -> str:
    from hotkeys import normalize_hotkey
    return normalize_hotkey(str(value or ""), default="F5")


def config_from_dict(data: dict[str, Any]) -> AppConfig:
    if "grade_level" not in data and "gradeLevel" in data:
        data = dict(data)
        data["grade_level"] = data.get("gradeLevel")
    scoring_raw = data.get("scoring", {})
    round_step = float(scoring_raw.get("round_step", 1) or 1)
    if round_step <= 0:
        round_step = 1.0
    round_method = str(scoring_raw.get("round_method", "round") or "round")
    if round_method not in {"round", "floor", "ceil"}:
        round_method = "round"
    scoring = ScoringSettings(
        max_score=float(scoring_raw.get("max_score", 10) or 10),
        round_step=round_step,
        round_method=round_method,
        diligence_enabled=False,
        diligence_max_bonus=float(scoring_raw.get("diligence_max_bonus", 3) or 3),
        diligence_decay_power=float(scoring_raw.get("diligence_decay_power", 2) or 2),
        diligence_criteria=scoring_raw.get("diligence_criteria", "字数较多且书写较为工整"),
        units=[ScoringUnit.from_dict(x) for x in scoring_raw.get("units", [])],
    )
    workflow_raw = data.get("workflow", {})
    workflow = Workflow(
        mode=workflow_raw.get("mode", "normal"),
        recognition_mode="direct",
        primary_enabled=bool(workflow_raw.get("primary_enabled", workflow_raw.get("primaryEnabled", True))),
        dual_enabled=bool(workflow_raw.get("dual_enabled", False)),
        arbitration_enabled=bool(workflow_raw.get("arbitration_enabled", workflow_raw.get("arbitrationEnabled", True))),
        dual_threshold=float(workflow_raw.get("dual_threshold", 2) or 2),
        primary_provider_name=workflow_raw.get("primary_provider_name", workflow_raw.get("primaryProviderName", data.get("active_provider", DEFAULT_PROVIDER_NAME))),
        secondary_provider_name=workflow_raw.get("secondary_provider_name", workflow_raw.get("secondaryProviderName", "")),
        arbitration_provider_name=workflow_raw.get("arbitration_provider_name", workflow_raw.get("arbitrationProviderName", "")),
        primary_model=str(workflow_raw.get("primary_model", "") or ""),
        secondary_model=str(workflow_raw.get("secondary_model", "") or ""),
        arbitration_model=str(workflow_raw.get("arbitration_model", "") or ""),
        ocr_provider_name=workflow_raw.get("ocr_provider_name", workflow_raw.get("ocrProviderName", "")),
        ocr_provider=provider_from_dict(workflow_raw.get("ocr_provider", {})),
        secondary_provider=provider_from_dict(workflow_raw.get("secondary_provider", {})),
        arbitration_provider=provider_from_dict(workflow_raw.get("arbitration_provider", {})),
        target_count_enabled=bool(workflow_raw.get("target_count_enabled", False)),
        target_count=int(workflow_raw.get("target_count", 0) or 0),
        retry_limit=int(workflow_raw.get("retry_limit", 5) or 5),
        confirm_before_submit=bool(workflow_raw.get("confirm_before_submit", True)),
        normal_countdown=int(workflow_raw.get("normal_countdown", 5) or 5),
        unattended_countdown=int(workflow_raw.get("unattended_countdown", 1) or 1),
        capture_delay=float(workflow_raw.get("capture_delay", 0.15) or 0),
        scoring_delay=float(workflow_raw.get("scoring_delay", 0) or 0),
        next_paper_delay=float(workflow_raw.get("next_paper_delay", 0.2) or 0),
        score_switch_mode="single",
        pause_hotkey=_normalize_pause_hotkey(workflow_raw.get("pause_hotkey", workflow_raw.get("pauseHotkey", "F8"))),
        enable_abnormal_termination=bool(workflow_raw.get("enable_abnormal_termination", False)),
        abnormal_termination_count=int(workflow_raw.get("abnormal_termination_count", 10) or 10),
        enable_page_refresh=bool(workflow_raw.get("enable_page_refresh", False)),
        page_refresh_frequency=int(workflow_raw.get("page_refresh_frequency", 20) or 20),
        page_refresh_hotkey=_normalize_page_refresh_hotkey(workflow_raw.get("page_refresh_hotkey", workflow_raw.get("pageRefreshHotkey", "F5"))),
        page_refresh_wait_seconds=float(workflow_raw.get("page_refresh_wait_seconds", 5.0) if workflow_raw.get("page_refresh_wait_seconds", 5.0) is not None else 5.0),
    )
    cfg = AppConfig(
        active_preset=data.get("active_preset", "默认配置"),
        active_provider=data.get("active_provider", data.get("activeProvider", DEFAULT_PROVIDER_NAME)),
        providers=_providers_from_raw(data.get("providers")),
        grade_level=data.get("grade_level", "高中") or "高中",
        subject=data.get("subject", "生物") or "生物",
        question_type="填空",
        question=data.get("question", ""),
        answer=data.get("answer", ""),
        rubric=data.get("rubric", ""),
        material_images=[str(x) for x in data.get("material_images", data.get("materialImages", []))],
        scoring=scoring,
        workflow=workflow,
        boxes=normalize_operation_boxes([RegionBox.from_dict(x) for x in data.get("boxes", [])]),
        preprocess_level=1,
        recognition_margin=int(data.get("recognition_margin", 0) or 0),
        blank_detection_enabled=bool(data.get("blank_detection_enabled", False)),
        blank_threshold=float(data.get("blank_threshold", 0.01) or 0.01),
        save_images=bool(data.get("save_images", False)),
    )
    names = {p.name for p in cfg.providers}
    if cfg.active_provider not in names and cfg.providers:
        cfg.active_provider = cfg.providers[0].name
    return unify_grading_roles(cfg)


def provider_for_role(cfg: AppConfig, role: str) -> Provider:
    """主评、副评、仲裁和 OCR 共用同一家服务商、同一个模型。"""
    name = cfg.workflow.primary_provider_name or cfg.active_provider
    base = next((p for p in cfg.providers if p.name == name), None)
    if base is None:
        if role == "ocr":
            base = cfg.workflow.ocr_provider
        else:
            base = cfg.providers[0] if cfg.providers else Provider()
    model = cfg.workflow.primary_model or base.model
    return replace(base, model=model or base.model)


def unify_grading_roles(cfg: AppConfig) -> AppConfig:
    """加载旧配置时，把主评/副评/仲裁/OCR 统一到同一家服务商和同一个模型，并关闭勤勉加分。"""
    names = {p.name for p in cfg.providers}
    if not cfg.workflow.primary_provider_name or cfg.workflow.primary_provider_name not in names:
        cfg.workflow.primary_provider_name = cfg.active_provider if cfg.active_provider in names else (cfg.providers[0].name if cfg.providers else "")
    shared = cfg.workflow.primary_provider_name
    cfg.workflow.secondary_provider_name = shared
    cfg.workflow.arbitration_provider_name = shared
    cfg.workflow.ocr_provider_name = shared
    primary = next((p for p in cfg.providers if p.name == shared), Provider())
    shared_model = cfg.workflow.primary_model or primary.model
    cfg.workflow.primary_model = shared_model
    cfg.workflow.secondary_model = shared_model
    cfg.workflow.arbitration_model = shared_model
    if primary.name:
        primary.model = shared_model or primary.model
    cfg.workflow.secondary_provider = provider_for_role(cfg, "secondary")
    cfg.workflow.arbitration_provider = provider_for_role(cfg, "arbitration")
    cfg.workflow.ocr_provider = provider_for_role(cfg, "ocr")
    cfg.scoring.diligence_enabled = False
    return cfg


def _providers_from_raw(raw: Any) -> list[Provider]:
    defaults = default_providers()
    default_by_name = {p.name: p for p in defaults}
    if not raw:
        return defaults
    providers: list[Provider] = []
    if isinstance(raw, dict):
        for name, value in raw.items():
            if isinstance(value, dict):
                item = {**value, "name": value.get("name", name)}
                providers.append(provider_from_dict(item))
    elif isinstance(raw, list):
        providers = [provider_from_dict(x) for x in raw if isinstance(x, dict)]
    providers = [item for item in providers if item.name not in RETIRED_PRESET_NAMES]
    if not providers:
        return defaults
    by_name = {p.name: p for p in providers}
    for name, provider in default_by_name.items():
        if name not in by_name:
            providers.append(provider)
        elif not by_name[name].models:
            by_name[name].models = list(provider.models)
            if not by_name[name].model:
                by_name[name].model = provider.model
    return providers

