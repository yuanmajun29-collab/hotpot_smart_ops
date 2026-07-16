"""Daily waste report domain — 废料日报聚合 (K-003).

纯函数聚合 waste_timeseries + waste_alerts 数据，不依赖 FastAPI。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List
from zoneinfo import ZoneInfo

from hotpot_platform.cloud.event_hub.domain.waste_timeseries import compute_trend_comparison

SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _as_int(value: Any) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    return 0


def build_daily_report(daily: list, alerts: list, date: str) -> dict:
    """构建废料日报结构化响应。"""
    today_row: Dict[str, Any] = daily[-1] if daily else {}
    total_waste_count = _as_int(today_row.get("total_count"))
    event_count = _as_int(today_row.get("event_count"))

    top_skus = today_row.get("top_skus") or []
    sorted_skus = sorted(
        [sku for sku in top_skus if isinstance(sku, dict)],
        key=lambda item: -_as_int(item.get("count")),
    )[:5]
    top_5_skus: List[Dict[str, Any]] = []
    for item in sorted_skus:
        count = _as_int(item.get("count"))
        pct = round(count / total_waste_count * 100, 1) if total_waste_count > 0 else 0.0
        top_5_skus.append({
            "sku": item.get("sku", "unknown"),
            "count": count,
            "pct": pct,
        })

    comparison = compute_trend_comparison(daily)

    return {
        "store_id": today_row.get("store_id"),
        "date": date,
        "hero": {
            "total_waste_count": total_waste_count,
            "event_count": event_count,
            "top_5_skus": top_5_skus,
            "day_over_day": comparison.get("day_over_day"),
            "week_over_week": comparison.get("week_over_week"),
            "seven_day_avg": comparison.get("seven_day_avg", 0.0),
            "thirty_day_avg": comparison.get("thirty_day_avg", 0.0),
        },
        "trend_30d": {
            "daily": daily,
            "trend": [_as_int(d.get("total_count")) for d in daily if isinstance(d, dict)],
            "dates": [d.get("date") for d in daily if isinstance(d, dict)],
            "comparison": comparison,
        },
        "alerts": alerts,
        "generated_at": datetime.now(SHANGHAI_TZ).isoformat(),
    }


def daily_report_for_store(db: Any, store_id: str, date: str) -> dict:
    """查询门店废料趋势和告警，并构建日报。"""
    trend = db.query_waste_trend(store_id, days=30, include_compare=True)
    alerts = db.list_waste_alerts(store_id, days=7)
    daily = trend.get("daily", [])

    result = build_daily_report(daily, alerts, date)
    result["store_id"] = store_id
    return result
