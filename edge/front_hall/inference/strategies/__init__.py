#!/usr/bin/env python3
"""
策略注册表 — 自动发现 strategies/ 下所有策略类

新增策略只需：
  1. 在 strategies/ 下创建 xxx.py
  2. 继承 BaseStrategy，设置 strategy_name
  3. 实现 analyze() 方法
  4. 无需修改任何其他文件
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path
from typing import Dict, Type

from .base import BaseStrategy

# ── 自动发现 ──

STRATEGIES: Dict[str, BaseStrategy] = {}

_current_dir = Path(__file__).parent
for _f in sorted(_current_dir.glob("*.py")):
    _name = _f.stem
    if _name.startswith("_") or _name.startswith("._") or _name == "base":
        continue
    _mod = importlib.import_module(f".{_name}", __package__)
    for _attr_name in dir(_mod):
        _obj = getattr(_mod, _attr_name)
        if (
            inspect.isclass(_obj)
            and issubclass(_obj, BaseStrategy)
            and _obj is not BaseStrategy
            and hasattr(_obj, "strategy_name")
        ):
            STRATEGIES[_obj.strategy_name] = _obj()
            break


# ── 查询接口 ──

def list_strategies() -> list:
    """列出所有已注册策略名称。"""
    return sorted(STRATEGIES.keys())


def get_strategy(name: str = "plan_b") -> BaseStrategy:
    """按名称获取策略实例。"""
    if name not in STRATEGIES:
        raise KeyError(f"Unknown strategy: {name}. Available: {list_strategies()}")
    return STRATEGIES[name]
