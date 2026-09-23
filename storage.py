from __future__ import annotations

import json
from pathlib import Path
import sys
from typing import Any

from models import AppConfig, RegionBox, config_from_dict
from platformdirs_helper import get_app_data_dir


# 所有用户数据都放在 data/ 中，便于备份、导入和后续打包。

ROOT = Path(__file__).resolve().parent
DATA_ROOT = Path(get_app_data_dir("MyApp")) if getattr(sys, "frozen", False) else ROOT
DATA_DIR = DATA_ROOT / "data"
CONFIG_FILE = DATA_DIR / "config.json"
PRESETS_FILE = DATA_DIR / "presets.json"
HISTORY_FILE = DATA_DIR / "history.json"
BLANK_REF_FILE = DATA_DIR / "blank_reference.json"


def ensure_data_dir() -> None:
    DATA_DIR.mkdir(exist_ok=True)


def default_boxes() -> list[RegionBox]:
    return [
        RegionBox("识别框", "recognition", 120, 160, 520, 280, "#2e7d32"),
        RegionBox("打分框", "score", 720, 260, 140, 56, "#1565c0"),
        RegionBox("提交框", "submit", 920, 260, 150, 60, "#ef6c00"),
    ]


def load_config() -> AppConfig:
    ensure_data_dir()
    if not CONFIG_FILE.exists():
        cfg = AppConfig(boxes=default_boxes())
        save_config(cfg)
        return cfg
    try:
        raw = json.loads(CONFIG_FILE.read_text(encoding="utf-8"))
        raw_box_count = len(raw.get("boxes", []))
        cfg = config_from_dict(raw)
        if not cfg.boxes:
            cfg.boxes = default_boxes()
        if raw_box_count != len(cfg.boxes):
            save_config(cfg)
        return cfg
    except Exception:
        cfg = AppConfig(boxes=default_boxes())
        save_config(cfg)
        return cfg


def save_config(config: AppConfig) -> None:
    ensure_data_dir()
    CONFIG_FILE.write_text(json.dumps(config.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")


def load_presets() -> dict[str, Any]:
    ensure_data_dir()
    if not PRESETS_FILE.exists():
        return {"默认配置": load_config().to_dict()}
    try:
        return json.loads(PRESETS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"默认配置": load_config().to_dict()}


def save_presets(presets: dict[str, Any]) -> None:
    ensure_data_dir()
    PRESETS_FILE.write_text(json.dumps(presets, ensure_ascii=False, indent=2), encoding="utf-8")


def load_history() -> list[dict[str, Any]]:
    ensure_data_dir()
    if not HISTORY_FILE.exists():
        return []
    try:
        return json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def save_history(records: list[dict[str, Any]]) -> None:
    ensure_data_dir()
    HISTORY_FILE.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")


def load_blank_reference() -> dict[str, Any] | None:
    ensure_data_dir()
    if not BLANK_REF_FILE.exists():
        return None
    try:
        return json.loads(BLANK_REF_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def save_blank_reference(data: dict[str, Any]) -> None:
    ensure_data_dir()
    BLANK_REF_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def clear_blank_reference() -> None:
    if BLANK_REF_FILE.exists():
        BLANK_REF_FILE.unlink()
