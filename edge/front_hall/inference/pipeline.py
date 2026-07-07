#!/usr/bin/env python3
"""
前厅场景推理管线 — 统一入口

架构：engines/（推理引擎）+ strategies/（分析策略）+ rules.py（规则配置）

新增策略 = 在 strategies/ 丢一个文件，自动注册。
新增引擎 = 在 engines/ 丢一个文件 + register()。

使用：
    result = analyze_table(image, table_id="T01", image_path="/tmp/frame.jpg", strategy="plan_b")
"""

from __future__ import annotations

import time
from typing import Any, Dict, Tuple

import numpy as np

from .engines import get_engine, close_all
from .rules import count_detections
from .strategies import get_strategy, list_strategies


def analyze_table(
    image: np.ndarray,
    table_id: str = "",
    image_path: str = "",
    strategy: str = "plan_b",
) -> Dict[str, Any]:
    """
    统一推理入口。

    Args:
        image: BGR 图像 (numpy array)
        table_id: 桌号（如 "T01"）
        image_path: 图片路径（Plan A 需要）
        strategy: 策略名（"plan_b" | "plan_a"，或自定义策略名）

    Returns:
        分析结果 dict（status / alerts / recommendation / _diagnostics 等）
    """
    t_start = time.perf_counter()

    # 1. YOLO 检测（所有策略共用）
    yolo = get_engine("yolo")
    result = yolo.detect(image, zone="front")
    detections = result.get("detections", [])
    yolo_ms = result.get("inference_ms", 0)
    counts = count_detections(detections)

    # 2. 策略分发（通过注册表，不 hardcode 策略名）
    strategy_instance = get_strategy(strategy)

    output = strategy_instance.analyze(
        engine_provider=get_engine,
        counts=counts,
        table_id=table_id,
        yolo_ms=yolo_ms,
        ndet=len(detections),
        image_path=image_path,
    )

    total_ms = (time.perf_counter() - t_start) * 1000
    output["_diagnostics"]["total_ms"] = round(total_ms, 1)
    return output


# ── 公共 API ──

def available_strategies() -> list:
    """列出所有可用策略。"""
    return list_strategies()


def cleanup():
    """关闭所有引擎（进程退出前调用）。"""
    close_all()
