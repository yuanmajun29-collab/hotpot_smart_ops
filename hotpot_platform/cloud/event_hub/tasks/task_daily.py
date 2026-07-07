#!/usr/bin/env python3
"""
定时任务 — 每日损耗复盘（22:00）

生成当日损耗日报并推送微信通知。
"""

TASK_NAME = "daily"

from hotpot_platform.cloud.event_hub.daily_scheduler import generate_daily_report_for_store
from hotpot_platform.cloud.event_hub import runtime


def run(store_id: str) -> None:
    generate_daily_report_for_store(
        runtime.hub, runtime.db, runtime.alert_gateway,
        store_id, push=True,
    )
