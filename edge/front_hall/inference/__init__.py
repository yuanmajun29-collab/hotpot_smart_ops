#!/usr/bin/env python3
"""
前厅推理包

入口：pipeline.analyze_table()
兼容：scene_analyzer.analyze_table_image() (deprecated, 转发到 pipeline)
"""
from .pipeline import analyze_table, available_strategies, cleanup
from .scene_analyzer import analyze_table_image  # backward compat
