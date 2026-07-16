#!/usr/bin/env python3
"""
定时任务 — 废料日报（22:00）

聚合今日 vlm_waste_estimate 事件 → 写入 waste_timeseries → 触发告警检查。
"""
TASK_NAME = "waste_daily"

from hotpot_platform.cloud.event_hub.domain.waste_timeseries import aggregate_waste_events
from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.daily_scheduler import local_today


def run(store_id: str) -> None:
    """22:00 废料日报 — 聚合今日事件落库。"""
    today = local_today()
    store = runtime.hub.get_store(store_id)

    # ── 聚合内存中今天的 vlm_waste_estimate 事件 ──
    live_events = store.get_events(limit=500)
    today_events = [
        ev for ev in live_events
        if ev.get("event_type") == "vlm_waste_estimate"
        and ev.get("timestamp", "")[:10] == today
    ]

    total = 0
    event_count = 0
    top_skus = []

    if today_events:
        agg = aggregate_waste_events(today_events, today)
        total = agg["total_count"]
        event_count = agg["event_count"]
        top_skus = agg["top_skus"]

    runtime.db.upsert_waste_timeseries(store_id, today, total, event_count, top_skus)

    # 触发告警检查
    alert_result = runtime.db.check_and_create_waste_alert(store_id, today)

    print(
        f"[waste_daily] {store_id} {today} "
        f"total={total} events={event_count} "
        f"alert={'triggered' if alert_result.get('triggered') else 'ok'}",
        flush=True,
    )
