#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""确认软件不再包含激活码、试用额度或授权拦截。"""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parent

FORBIDDEN_MODULE_NAMES = {
    "activation_dialog",
    "activation_dialog_hybrid",
    "license_client",
    "license_gate",
    "license_hybrid",
    "license_manager",
}

FORBIDDEN_IDENTIFIERS = {
    "init_trial",
    "check_trial_quota",
    "consume_trial_quota",
    "reset_trial",
    "get_license_status",
    "show_activation_dialog",
    "show_trial_expired_dialog",
    "update_license_bar",
    "_build_license_bar",
    "activate_license",
}

FORBIDDEN_TEXT = (
    "激活码",
    "试用额度",
    "试用中",
    "立即激活",
    "license_hybrid",
    "activation_dialog",
)


def _imported_modules(tree: ast.AST) -> set[str]:
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".")[0])
    return names


def _used_names(tree: ast.AST) -> set[str]:
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def _method_names(tree: ast.AST, class_name: str) -> list[str]:
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [item.name for item in node.body if isinstance(item, ast.FunctionDef)]
    raise AssertionError(f"class {class_name} not found")


def test_main_entry_has_no_license_gate() -> None:
    source = (ROOT / "main.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = _imported_modules(tree)
    used = _used_names(tree)
    assert imported.isdisjoint(FORBIDDEN_MODULE_NAMES), imported & FORBIDDEN_MODULE_NAMES
    assert used.isdisjoint(FORBIDDEN_IDENTIFIERS), used & FORBIDDEN_IDENTIFIERS
    assert "run_app" in used


def test_app_has_no_activation_or_trial_quota() -> None:
    source = (ROOT / "app.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported = _imported_modules(tree)
    used = _used_names(tree)
    methods = set(_method_names(tree, "AIMarkerApp"))

    assert imported.isdisjoint(FORBIDDEN_MODULE_NAMES), imported & FORBIDDEN_MODULE_NAMES
    assert used.isdisjoint(FORBIDDEN_IDENTIFIERS), used & FORBIDDEN_IDENTIFIERS
    assert methods.isdisjoint(FORBIDDEN_IDENTIFIERS), methods & FORBIDDEN_IDENTIFIERS
    for needle in FORBIDDEN_TEXT:
        assert needle not in source, f"app.py still contains {needle}"


def test_readme_sells_software_not_activation_codes() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    assert "输入激活码" not in readme
    assert "获取激活码" not in readme
    assert "需要激活后使用" not in readme
    assert "直接售卖" in readme or "购买后" in readme
    assert "无需激活码" in readme


def test_license_modules_are_removed() -> None:
    leftover = [name + ".py" for name in sorted(FORBIDDEN_MODULE_NAMES) if (ROOT / f"{name}.py").exists()]
    assert leftover == [], leftover


if __name__ == "__main__":
    test_main_entry_has_no_license_gate()
    test_app_has_no_activation_or_trial_quota()
    test_readme_sells_software_not_activation_codes()
    test_license_modules_are_removed()
    print("[OK] activation-free checks passed")
