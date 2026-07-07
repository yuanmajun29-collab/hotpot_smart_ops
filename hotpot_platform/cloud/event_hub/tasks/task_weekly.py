#!/usr/bin/env python3
"""
定时任务 — 周一 09:00 趋势周报（P1.5 预留槽）

当前由 HOTPOT_WEEKLY_REPORT 环境变量控制开关。
"""

TASK_NAME = "weekly"

import os


def run(store_id: str) -> None:
    if os.environ.get("HOTPOT_WEEKLY_REPORT", "0") != "1":
        return
    # P1.5 LLM 损耗趋势周报，LOSS-507 预留调度位
    pass
