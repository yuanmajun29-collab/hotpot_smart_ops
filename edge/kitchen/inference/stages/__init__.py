#!/usr/bin/env python3
"""
管线级注册表 — 自动发现 stages/ 下所有管线级

新增管线级只需：
  1. 在 stages/ 下创建 stage_xxx.py
  2. 导出 STAGE_NAME + STAGE_ORDER + run(frame_path, ctx) 函数
  3. 无需修改 pipeline.py
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Dict, List

StageFunc = Callable[[str, dict], dict]  # (frame_path, ctx) -> result

_stages: List[Dict[str, Any]] = []

_current_dir = Path(__file__).parent
for _f in sorted(_current_dir.glob("stage_*.py")):
    _mod = importlib.import_module(f".{_f.stem}", __package__)
    if hasattr(_mod, "STAGE_NAME") and hasattr(_mod, "run"):
        _stages.append({
            "name": _mod.STAGE_NAME,
            "order": getattr(_mod, "STAGE_ORDER", 99),
            "run": _mod.run,
        })

# 按 order 排序
STAGES = sorted(_stages, key=lambda s: s["order"])


def list_stages() -> list:
    """列出所有已注册管线级名称。"""
    return [s["name"] for s in STAGES]
