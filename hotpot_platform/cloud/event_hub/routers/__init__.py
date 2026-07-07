#!/usr/bin/env python3
"""
路由器注册表 — 自动发现 routers/ 下所有 FastAPI 路由模块

新增路由只需：
  1. 在 routers/ 下创建 xxx.py
  2. 导出 `router`（FastAPI APIRouter 实例）
  3. 无需修改 app.py

每个路由模块可选的元信息：
  - ROUTER_TAG: str      # 用于日志/分组
  - ROUTER_PREFIX: str   # 自定义前缀（默认无）
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import List, Dict, Any

from fastapi import FastAPI

_registry: List[Dict[str, Any]] = []

_current_dir = Path(__file__).parent
_exclude = {"__init__", "_deps"}

for _f in sorted(_current_dir.glob("*.py")):
    _name = _f.stem
    if _name in _exclude:
        continue
    _mod = importlib.import_module(f".{_name}", __package__)
    if hasattr(_mod, "router"):
        _registry.append({
            "name": _name,
            "router": _mod.router,
            "tag": getattr(_mod, "ROUTER_TAG", _name),
            "prefix": getattr(_mod, "ROUTER_PREFIX", ""),
        })


def auto_include_routers(app: FastAPI, verbose: bool = True) -> None:
    """自动注册所有已发现的路由器到 FastAPI 应用。"""
    for entry in _registry:
        kwargs = {}
        if entry["prefix"]:
            kwargs["prefix"] = entry["prefix"]
        app.include_router(entry["router"], **kwargs)
        if verbose:
            prefix_info = f" (prefix={entry['prefix']})" if entry["prefix"] else ""
            print(f"  [router] {entry['name']}{prefix_info}")


def list_routers() -> list:
    """列出所有已注册的路由器名称。"""
    return [r["name"] for r in _registry]
