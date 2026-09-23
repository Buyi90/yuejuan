from __future__ import annotations

import base64
import io
from typing import Iterable

from PIL import Image, ImageEnhance, ImageFilter, ImageGrab, ImageOps

from models import RegionBox


# 截图和预处理只处理识别框区域，保证 OCR/AI 不会看到打分框或提交框。


def capture_region(box: RegionBox, margin: int = 0) -> Image.Image:
    # 边距只向内收缩，避免 OCR 误读框线、网页按钮或旁边题目。
    safe_margin = max(0, min(int(margin or 0), box.width // 3, box.height // 3))
    x1 = box.x + safe_margin
    y1 = box.y + safe_margin
    x2 = box.x + box.width - safe_margin
    y2 = box.y + box.height - safe_margin
    return ImageGrab.grab(bbox=(x1, y1, x2, y2))


def image_to_base64(img: Image.Image) -> str:
    # 手写答案用较高质量 JPEG，体积比 PNG 小很多，上传更快，识别质量基本不掉。
    buffer = io.BytesIO()
    img.convert("RGB").save(buffer, format="JPEG", quality=92, optimize=True, subsampling=0)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def preprocess_image(img: Image.Image, level: int = 1) -> Image.Image:
    if level <= 0:
        return img.convert("RGB")
    out = img.convert("RGB")
    out = ImageOps.autocontrast(out)
    if level >= 1:
        out = ImageEnhance.Contrast(out).enhance(1.35)
        out = ImageEnhance.Sharpness(out).enhance(1.2)
    if level >= 2:
        gray = ImageOps.grayscale(out)
        out = gray.filter(ImageFilter.MedianFilter(size=3)).convert("RGB")
    if level >= 3:
        gray = ImageOps.grayscale(out)
        out = gray.point(lambda p: 255 if p > 165 else 0).convert("RGB")
    return out


def image_quality_report(img: Image.Image) -> dict[str, float | int | str]:
    # 给用户一个可读的识别区质量提示，不参与评分，避免因为截图太小或太暗导致误判。
    gray = ImageOps.grayscale(img)
    hist = gray.histogram()
    total = max(gray.width * gray.height, 1)
    mean = sum(i * c for i, c in enumerate(hist)) / total
    variance = sum(((i - mean) ** 2) * c for i, c in enumerate(hist)) / total
    dark_ratio = sum(hist[:90]) / total
    bright_ratio = sum(hist[210:]) / total
    if gray.width < 120 or gray.height < 80:
        level = "识别框偏小"
    elif mean < 65:
        level = "画面偏暗"
    elif variance < 350:
        level = "对比度偏低"
    elif dark_ratio < 0.003 and bright_ratio > 0.93:
        level = "可能为空白"
    else:
        level = "正常"
    return {
        "width": gray.width,
        "height": gray.height,
        "mean": round(mean, 2),
        "variance": round(variance, 2),
        "dark_ratio": round(dark_ratio, 4),
        "level": level,
    }


def black_pixel_ratio(img: Image.Image) -> dict[str, float]:
    gray = ImageOps.grayscale(img)
    hist = gray.histogram()
    total = gray.width * gray.height
    sum_all = sum(i * count for i, count in enumerate(hist))
    sum_bg = 0
    w_bg = 0
    best_threshold = 0
    best_var = 0.0
    for t, count in enumerate(hist):
        w_bg += count
        if w_bg == 0:
            continue
        w_fg = total - w_bg
        if w_fg == 0:
            break
        sum_bg += t * count
        mean_bg = sum_bg / w_bg
        mean_fg = (sum_all - sum_bg) / w_fg
        variance = w_bg * w_fg * (mean_bg - mean_fg) ** 2
        if variance > best_var:
            best_var = variance
            best_threshold = t
    black = sum(hist[: best_threshold + 1])
    return {"ratio": black / total if total else 0, "threshold": float(best_threshold), "black": float(black), "total": float(total)}


def is_blank(current: dict[str, float], reference: dict[str, float], threshold: float) -> tuple[bool, str]:
    diff = abs(current["ratio"] - reference["ratio"])
    if diff <= threshold:
        return True, f"黑色像素占比差异 {diff * 100:.2f}% <= {threshold * 100:.2f}%"
    return False, f"黑色像素占比差异 {diff * 100:.2f}% > {threshold * 100:.2f}%"


def concat_preview(images: Iterable[Image.Image]) -> Image.Image | None:
    imgs = [i.convert("RGB") for i in images]
    if not imgs:
        return None
    width = max(i.width for i in imgs)
    height = sum(i.height for i in imgs)
    canvas = Image.new("RGB", (width, height), "white")
    y = 0
    for img in imgs:
        canvas.paste(img, (0, y))
        y += img.height
    return canvas
