from __future__ import annotations

from pathlib import Path

import storage


def test_ensure_data_dir_creates_missing_parent_directories(tmp_path: Path) -> None:
    original = storage.DATA_DIR
    try:
        storage.DATA_DIR = tmp_path / "missing" / "MyApp" / "data"
        storage.ensure_data_dir()
        assert storage.DATA_DIR.is_dir()
    finally:
        storage.DATA_DIR = original
