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
    """懒加载 YOLO，处理 hotpot platform/ 模块名冲突。"""
    # ── 强制恢复 stdlib platform ──
    _need_fix = ("platform" in sys.modules
                 and not hasattr(sys.modules["platform"], "system"))
    if _need_fix:
        del sys.modules["platform"]
        importlib.invalidate_caches()

    _saved_path = list(sys.path)
    sys.path = [p for p in sys.path if "hotpot" not in str(p)]

    # 验证 stdlib platform
    import platform as _chk
    assert hasattr(_chk, "system"), f"stdlib platform broken! file={_chk.__file__}"

    # 加载 YOLO 模块
    spec = importlib.util.spec_from_file_location(
        "real_yolo",
        PROJECT_ROOT / "edge" / "common" / "detector" / "real_yolo.py",
    )
    mod = importlib.util.module_from_spec(spec)
    sys.path = [p for p in sys.path if "hotpot" not in str(p)]
    spec.loader.exec_module(mod)
    sys.path[:] = _saved_path

    return mod.RealYoloDetector(conf=0.2)
