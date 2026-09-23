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

def test_hidden_scoring_defaults_are_not_rendered_as_editable_fields() -> None:
    config_start = APP_SOURCE.index("    def _build_config_tab")
    config_end = APP_SOURCE.index("    def _build_provider_tab", config_start)
    config_block = APP_SOURCE[config_start:config_end]
    assert '"年级"' not in config_block
    assert '"学科"' not in config_block
    assert '"打分个数"' not in config_block
    assert '"打分步长"' not in config_block
    assert '"取整方式"' not in config_block
    assert '"题目满分"' in config_block


def test_grading_flow_hides_fixed_controls_and_uses_compact_role_row() -> None:
    flow_start = APP_SOURCE.index('        inner = self._card_section(page, "批改流程")')
    flow_end = APP_SOURCE.index('    def _build_provider_tab', flow_start)
    flow_block = APP_SOURCE[flow_start:flow_end]
    assert '识别方式' not in flow_block
    assert 'OCR 预处理强度' not in flow_block
    assert '多打分框切换' not in flow_block
    assert '.pack(side="left"' in flow_block
    assert 'self.config_data.workflow.recognition_mode = "direct"' in APP_SOURCE
    assert 'self.config_data.preprocess_level = 1' in APP_SOURCE
    assert 'self.config_data.workflow.score_switch_mode = "single"' in APP_SOURCE

def test_latest_result_updates_process_output_even_in_continuous_mode() -> None:
    result_start = APP_SOURCE.index("    def _show_result")
    result_end = APP_SOURCE.index("    def _max_score", result_start)
    result_block = APP_SOURCE[result_start:result_end]
    assert "self._update_process_views(result)" in result_block
    assert "if self.continuous:" in result_block


if __name__ == "__main__":
    for name, test in sorted(globals().items()):
        if name.startswith("test_"):
            test()
            print(f"PASS {name}")
    print("all scoring process/default tests passed")


