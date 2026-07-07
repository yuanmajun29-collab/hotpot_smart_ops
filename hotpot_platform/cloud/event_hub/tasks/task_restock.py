#!/usr/bin/env python3
"""
定时任务 — 15:00 备货建议

基于损耗预算和库存数据，推送次日备货建议。
"""

TASK_NAME = "restock"

from hotpot_platform.cloud.event_hub.daily_scheduler import push_restock_advice_for_store
from hotpot_platform.cloud.event_hub import runtime


def run(store_id: str) -> None:
    push_restock_advice_for_store(
        runtime.hub, runtime.db, runtime.alert_gateway,
        store_id,
    )
