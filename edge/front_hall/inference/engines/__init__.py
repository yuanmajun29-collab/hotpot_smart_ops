#!/usr/bin/env python3
"""
引擎注册表 — 懒加载 YOLO / CLIP

新增引擎：在 engines/ 下创建文件，导出 factory 函数（以 `_create_` 开头），
然后在此文件 import 并 register()。
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from .yolo import _create_yolo
from .clip_client import ClipClient

_engines: Dict[str, Any] = {}
_factories: Dict[str, Callable] = {}


def _register(name: str, factory: Callable):
    _factories[name] = factory


_register("yolo", _create_yolo)
_register("clip", ClipClient)


def get_engine(name: str):
    """懒加载获取引擎实例。"""
    if name not in _engines:
        if name not in _factories:
            raise KeyError(f"Unknown engine: {name}. Available: {list(_factories.keys())}")
        _engines[name] = _factories[name]()
    return _engines[name]


def close_all():
    """关闭所有引擎。"""
    for e in _engines.values():
        if hasattr(e, "close"):
            e.close()
    _engines.clear()
