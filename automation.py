from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable

import pyautogui

from models import RegionBox


# 桌面端无法直接访问网页 DOM，因此用用户设置的打分框和提交框完成自动操作。

# 配置日志
logger = logging.getLogger(__name__)

pyautogui.FAILSAFE = True


@dataclass
class AutomationConfig:
    """自动化操作配置"""
    click_delay: float = 0.1          # 点击后延迟
    select_delay: float = 0.05        # 选择文本后延迟
    type_interval: float = 0.01       # 输入字符间隔
    switch_delay: float = 0.05        # 切换输入框延迟
    submit_delay: float = 0.08        # 提交前延迟
    retry_attempts: int = 3           # 重试次数
    retry_delay: float = 0.5          # 重试间隔
    use_paste: bool = False           # 是否使用粘贴模式
    verify_operations: bool = False   # 是否验证操作（可能影响性能）
    safe_mode: bool = True            # 安全模式


# 全局配置实例
_config = AutomationConfig()


def get_config() -> AutomationConfig:
    """获取全局配置"""
    return _config


def set_config(config: AutomationConfig) -> None:
    """设置全局配置"""
    global _config
    _config = config


class AutomationError(Exception):
    """自动化操作异常"""
    pass


def with_retry(func: Callable) -> Callable:
    """重试装饰器"""
    def wrapper(*args, **kwargs):
        config = get_config()
        last_error = None

        for attempt in range(config.retry_attempts):
            try:
                return func(*args, **kwargs)
            except pyautogui.FailSafeException:
                # FailSafe 异常不重试
                raise
            except Exception as e:
                last_error = e
                logger.warning(f"{func.__name__} 第 {attempt + 1} 次尝试失败: {e}")
                if attempt < config.retry_attempts - 1:
                    time.sleep(config.retry_delay)

        raise AutomationError(f"{func.__name__} 执行失败（已重试 {config.retry_attempts} 次）: {last_error}")

    return wrapper


def check_screen_bounds(x: int, y: int) -> bool:
    """检查坐标是否在屏幕范围内"""
    screen_width, screen_height = pyautogui.size()
    return 0 <= x < screen_width and 0 <= y < screen_height


def click_box(box: RegionBox) -> None:
    """点击指定区域的中心点。外层填分/提交负责重试，这里不再套一层，避免连点。"""
    config = get_config()
    x, y = box.center()

    # 安全检查
    if config.safe_mode and not check_screen_bounds(x, y):
        raise AutomationError(f"点击坐标 ({x}, {y}) 超出屏幕范围")

    logger.debug(f"点击 {box.name} 区域 ({x}, {y})")
    pyautogui.click(x, y)
    time.sleep(config.click_delay)


def select_all_text() -> None:
    """全选文本内容"""
    config = get_config()
    pyautogui.hotkey("ctrl", "a")
    time.sleep(config.select_delay)


def input_text(text: str, use_paste: bool = None) -> None:
    """
    输入文本

    Args:
        text: 要输入的文本
        use_paste: 是否使用粘贴模式（None 则使用全局配置）
    """
    config = get_config()
    use_paste_mode = use_paste if use_paste is not None else config.use_paste

    if use_paste_mode:
        # 粘贴模式：更快但需要 pyperclip 库
        try:
            import pyperclip
            pyperclip.copy(str(text))
            pyautogui.hotkey("ctrl", "v")
            time.sleep(config.select_delay)
            logger.debug(f"已粘贴文本: {text}")
        except ImportError:
            logger.warning("pyperclip 未安装，降级为逐字输入")
            pyautogui.write(str(text), interval=config.type_interval)
    else:
        # 逐字输入模式：兼容性更好
        pyautogui.write(str(text), interval=config.type_interval)
        logger.debug(f"已输入文本: {text}")


@with_retry
def fill_score(score_box: RegionBox, score: float | int | str) -> None:
    """
    在指定区域填写分数

    Args:
        score_box: 打分框区域
        score: 分数值
    """
    config = get_config()
    logger.info(f"填写分数: {score} 到 {score_box.name}")

    click_box(score_box)
    select_all_text()
    input_text(str(score))

    logger.info(f"成功填写分数: {score}")


def fill_scores(score_box: RegionBox, scores: list[float | int | str], switch_mode: str = "single") -> None:
    """
    批量填写多个分数

    Args:
        score_box: 第一个打分框区域
        scores: 分数列表
        switch_mode: 切换模式 ("single", "tab", "enter", "space")
    """
    config = get_config()

    if not scores:
        logger.warning("分数列表为空，跳过填写")
        return

    logger.info(f"开始批量填写 {len(scores)} 个分数，切换模式: {switch_mode}")

    # 单个分数或不支持的切换模式
    if switch_mode not in {"tab", "enter", "space"}:
        fill_score(score_box, scores[0])
        if len(scores) > 1:
            logger.warning(f"switch_mode={switch_mode} 不支持多分数，仅填写第一个")
        return

    # 点击第一个打分框
    click_box(score_box)

    # 确定切换按键
    key = "space" if switch_mode == "space" else switch_mode

    for index, score in enumerate(scores):
        try:
            select_all_text()
            input_text(str(score))

            if index < len(scores) - 1:
                pyautogui.press(key)
                time.sleep(config.switch_delay)

            logger.debug(f"已填写第 {index + 1}/{len(scores)} 个分数: {score}")
        except Exception as e:
            logger.error(f"填写第 {index + 1} 个分数时出错: {e}")
            raise

    logger.info(f"成功填写 {len(scores)} 个分数")


@with_retry
def click_submit(submit_box: RegionBox) -> None:
    """点击提交按钮"""
    config = get_config()
    logger.info(f"点击提交按钮: {submit_box.name}")

    time.sleep(config.submit_delay)  # 提交前延迟
    click_box(submit_box)

    logger.info("提交操作已执行")


def fill_and_submit(
    score_box: RegionBox,
    submit_box: RegionBox,
    score: float | int | str,
    scores: list[float | int | str] | None = None,
    switch_mode: str = "single"
) -> None:
    """
    填写分数并提交

    Args:
        score_box: 打分框区域
        submit_box: 提交按钮区域
        score: 单个分数（当 scores 为 None 时使用）
        scores: 分数列表
        switch_mode: 切换模式
    """
    try:
        fill_scores(score_box, scores or [score], switch_mode)
        click_submit(submit_box)
    except AutomationError as e:
        logger.error(f"自动操作失败: {e}")
        raise
    except Exception as e:
        logger.error(f"未预期的错误: {e}", exc_info=True)
        raise AutomationError(f"自动操作失败: {e}")
