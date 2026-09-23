#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""评分过程展示和题目默认值的回归测试。"""

from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_SOURCE = (ROOT / "app.py").read_text(encoding="utf-8")
MODELS_SOURCE = (ROOT / "models.py").read_text(encoding="utf-8")


def test_subject_defaults_are_stable() -> None:
    assert 'grade_level: str = "高中"' in MODELS_SOURCE
    assert 'subject: str = "生物"' in MODELS_SOURCE
    assert 'grade_level=data.get("grade_level", "高中")' in MODELS_SOURCE
    assert 'subject=data.get("subject", "生物") or "生物"' in MODELS_SOURCE


def test_question_type_is_fixed_to_fill_in() -> None:
    assert 'question_type: str = "填空"' in MODELS_SOURCE
    assert 'question_type="填空"' in MODELS_SOURCE
    config_start = APP_SOURCE.index("    def _build_config_tab")
    config_end = APP_SOURCE.index("    def _build_provider_tab", config_start)
    config_block = APP_SOURCE[config_start:config_end]
    assert '"题型"' not in config_block






if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"PASS {name}")
    print("all scoring process/default tests passed")


