#!/usr/bin/env python3
"""
YOLO 检测器引擎 — 懒加载 RealYoloDetector

导出 _create_yolo 工厂函数，由 engines/__init__.py 注册。
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[4]


def _create_yolo():
    """懒加载 YOLO，使用标准 import（已验证无 platform 冲突）。"""
    from edge.common.detector.real_yolo import RealYoloDetector
    return RealYoloDetector(conf=0.2)
