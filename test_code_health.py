#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""轻量代码健康检查，防止明显的维护陷阱回归。"""

from __future__ import annotations

import ast
import importlib
import os
from pathlib import Path
import sys
import tempfile


ROOT = Path(__file__).resolve().parent


def _class_method_names(path: Path, class_name: str) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return [item.name for item in node.body if isinstance(item, ast.FunctionDef)]
    raise AssertionError(f"class {class_name} not found in {path}")


def test_aimarker_app_has_no_duplicate_method_names() -> None:
    names = _class_method_names(ROOT / "app.py", "AIMarkerApp")
    duplicates = sorted({name for name in names if names.count(name) > 1})
    assert duplicates == [], f"duplicate AIMarkerApp methods: {duplicates}"


def test_config_tab_variable_initialization_is_extracted() -> None:
    names = _class_method_names(ROOT / "app.py", "AIMarkerApp")
    assert "_init_config_vars" in names


def test_provider_model_lookup_is_centralized() -> None:
    names = _class_method_names(ROOT / "app.py", "AIMarkerApp")
    assert "_provider_model_name" in names


def test_packaged_storage_uses_appdata() -> None:
    old_appdata = os.environ.get("APPDATA")
    had_frozen = hasattr(sys, "frozen")
    old_frozen = getattr(sys, "frozen", None)
    sys.modules.pop("storage", None)

    try:
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["APPDATA"] = tmp
            sys.frozen = True
            storage = importlib.import_module("storage")
            expected = Path(tmp) / "MyApp" / "data"
            assert storage.DATA_DIR == expected
            storage.ensure_data_dir()
            assert expected.is_dir()
    finally:
        sys.modules.pop("storage", None)
        if had_frozen:
            sys.frozen = old_frozen
        else:
            delattr(sys, "frozen")
        if old_appdata is None:
            os.environ.pop("APPDATA", None)
        else:
            os.environ["APPDATA"] = old_appdata
        importlib.import_module("storage")


if __name__ == "__main__":
    test_aimarker_app_has_no_duplicate_method_names()
    test_config_tab_variable_initialization_is_extracted()
    test_provider_model_lookup_is_centralized()
    test_packaged_storage_uses_appdata()
    print("[OK] code health checks passed")
