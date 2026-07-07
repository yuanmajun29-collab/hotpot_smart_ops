#!/usr/bin/env python3
"""
定时任务注册表 — 自动发现 tasks/ 下所有任务模块

新增定时任务只需：
  1. 在 tasks/ 下创建 task_xxx.py
  2. 导出 TASK_NAME + run(store_id) 函数
  3. （可选）导出 TASK_SCHEDULE 覆盖默认调度时间
  4. 无需修改 app.py
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any, Callable, Dict

TaskFunc = Callable[[str], None]

_registry: Dict[str, TaskFunc] = {}

_current_dir = Path(__file__).parent
for _f in sorted(_current_dir.glob("task_*.py")):
    _mod = importlib.import_module(f".{_f.stem}", __package__)
    if hasattr(_mod, "TASK_NAME") and hasattr(_mod, "run"):
        _registry[_mod.TASK_NAME] = _mod.run


def get_dispatch() -> Dict[str, TaskFunc]:
    """返回 {task_name: run_fn} 调度映射表，供 DailyReportScheduler 使用。"""
    return dict(_registry)


def list_tasks() -> list:
    """列出所有已注册定时任务名称。"""
    return sorted(_registry.keys())
