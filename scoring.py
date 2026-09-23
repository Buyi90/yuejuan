from __future__ import annotations

import math
from typing import Any

from models import GradeResult, ScoringSettings


# 这里复刻脚本中的取整和分小题分配逻辑；勤勉加分已取消。


def round_score(score: float | None, settings: ScoringSettings, step: float | None = None) -> float | None:
    if score is None:
        return None
    round_step = step or settings.round_step or 1
    method = settings.round_method or "round"
    if round_step <= 0:
        round_step = 1
    scaled = score / round_step
    if method == "floor":
        value = math.floor(scaled) * round_step
    elif method == "ceil":
        value = math.ceil(scaled) * round_step
    else:
        value = round(scaled) * round_step
    return round(value, 2)


def diligence_bonus(score: float, diligence_level: int, max_score: float, settings: ScoringSettings) -> dict[str, float]:
    if not settings.diligence_enabled or diligence_level <= 1 or max_score <= 0:
        return {"bonus": 0.0, "raw_bonus": 0.0, "decay_factor": 0.0}
    ratio = min(score / max_score, 1)
    decay = pow(1 - ratio, settings.diligence_decay_power)
    raw = min(max(0, diligence_level - 1), settings.diligence_max_bonus, max(0, max_score - score))
    bonus = round(raw * decay, 2)
    rounded_bonus = round_score(bonus, settings) or 0
    return {"bonus": rounded_bonus, "raw_bonus": raw, "decay_factor": decay}


def apply_scoring(result: GradeResult, settings: ScoringSettings) -> dict[str, Any]:
    raw_score = result.raw_score if result.raw_score is not None else result.score
    if raw_score is None:
        return {"final_score": None, "sub_scores": [], "bonus": 0, "breakdown": {}}

    max_score = settings.max_score
    if settings.units:
        max_score = sum(u.max_score for u in settings.units) or max_score

    accuracy = round_score(raw_score, settings) or 0
    final_score = min(accuracy, max_score)

    final_subs: list[dict[str, Any]] = []
    if result.sub_scores:
        for index, item in enumerate(result.sub_scores):
            unit_step = settings.units[index].round_step if index < len(settings.units) else settings.round_step
            score = round_score(item.get("score"), settings, unit_step)
            max_unit = item.get("maxScore") or item.get("max_score") or (settings.units[index].max_score if index < len(settings.units) else 0)
            final_subs.append({**item, "score": score, "maxScore": max_unit})

    return {
        "final_score": final_score,
        "sub_scores": final_subs,
        "bonus": 0,
        "breakdown": {
            "raw_score": raw_score,
            "accuracy": accuracy,
            "max_score": max_score,
        },
    }
