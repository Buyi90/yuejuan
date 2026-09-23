from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def test_project_uses_tk_ui_without_legacy_qt_compat_layer() -> None:
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8").lower()
    app_tree = ast.parse((ROOT / "app.py").read_text(encoding="utf-8"))
    imported_modules = {
        alias.name.split(".")[0]
        for node in ast.walk(app_tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    app_class = next(
        node for node in app_tree.body
        if isinstance(node, ast.ClassDef) and node.name == "AIMarkerApp"
    )
    bases = [ast.unparse(base) for base in app_class.bases]

    assert "pyside6" not in requirements
    assert "qtcompat" not in imported_modules
    assert "ttkbootstrap" in imported_modules
    assert "ttk.Window" in bases
    assert not (ROOT / "qtcompat.py").exists()
