#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""主评、副评、仲裁和 OCR 共用同一服务商、同一个模型，并且取消勤勉加分。"""

from __future__ import annotations

import ast
from pathlib import Path

from models import AppConfig, GradeResult, Provider, ScoringSettings, Workflow, config_from_dict, provider_for_role
from scoring import apply_scoring
from ai_client import build_prompt


ROOT = Path(__file__).resolve().parent


def test_config_unifies_grading_providers_to_one_key() -> None:
    cfg = config_from_dict({
        "active_provider": "自定义服务商",
        "providers": [
            {"name": "自定义服务商", "endpoint": "https://a.example/v1/chat/completions", "api_key": "key-a", "model": "gpt-4o", "models": ["gpt-4o", "gpt-4o-mini"]},
            {"name": "备用服务商", "endpoint": "https://b.example/v1/chat/completions", "api_key": "key-b", "model": "aimarker-fast", "models": ["aimarker-fast", "aimarker-pro"]},
        ],
        "workflow": {
            "primary_provider_name": "自定义服务商",
            "secondary_provider_name": "备用服务商",
            "arbitration_provider_name": "备用服务商",
            "ocr_provider_name": "备用服务商",
            "primary_model": "gpt-4o",
            "secondary_model": "gpt-4o-mini",
            "arbitration_model": "gpt-4o",
        },
        "scoring": {"diligence_enabled": True, "diligence_max_bonus": 3},
    })
    assert cfg.workflow.primary_provider_name == "自定义服务商"
    assert cfg.workflow.secondary_provider_name == "自定义服务商"
    assert cfg.workflow.arbitration_provider_name == "自定义服务商"
    assert cfg.workflow.ocr_provider_name == "自定义服务商"
    assert cfg.scoring.diligence_enabled is False

    secondary = provider_for_role(cfg, "secondary")
    arbitration = provider_for_role(cfg, "arbitration")
    primary = provider_for_role(cfg, "primary")
    ocr = provider_for_role(cfg, "ocr")
    assert primary.api_key == secondary.api_key == arbitration.api_key == "key-a"
    assert primary.endpoint == secondary.endpoint == arbitration.endpoint
    assert ocr.api_key == "key-a"
    assert ocr.endpoint == primary.endpoint
    assert primary.model == secondary.model == arbitration.model == ocr.model == "gpt-4o"
    assert cfg.workflow.primary_model == cfg.workflow.secondary_model == cfg.workflow.arbitration_model == "gpt-4o"


def test_apply_scoring_never_adds_diligence_bonus() -> None:
    settings = ScoringSettings(max_score=10, diligence_enabled=True, diligence_max_bonus=3)
    result = GradeResult(raw_score=6, score=6, student_answer="这是一段足够长的学生答案用于触发勤勉加分", diligence_level=5)
    scored = apply_scoring(result, settings)
    assert scored["bonus"] == 0
    assert scored["final_score"] == 6


def test_prompt_has_no_diligence_section() -> None:
    cfg = AppConfig(scoring=ScoringSettings(diligence_enabled=True))
    prompt = build_prompt(cfg)
    assert "勤勉度" not in prompt
    assert "勤勉" not in prompt




if __name__ == "__main__":
    test_config_unifies_grading_providers_to_one_key()
    test_apply_scoring_never_adds_diligence_bonus()
    test_prompt_has_no_diligence_section()
    test_config_tab_shares_provider_and_hides_diligence()
    print("[OK] shared grading provider checks passed")
