#!/usr/bin/env python3
"""
兼容层 — 旧 API 转发到新 pipeline.py

保留旧接口 analyze_table_image()，内部委托给 pipeline.analyze_table()，
避免改动所有调用方。
"""

from __future__ import annotations

from typing import Any, Dict

import numpy as np

from .pipeline import analyze_table as _analyze


def analyze_table_image(
    image: np.ndarray, table_id: str = "",
    image_path: str = "", mode: str = "plan_b",
) -> Dict[str, Any]:
    """
    兼容旧 API。

    Args:
        mode: "plan_b" | "plan_a"（映射到新架构的 strategy 参数）
    """
    return _analyze(
        image=image, table_id=table_id,
        image_path=image_path, strategy=mode,
    )
