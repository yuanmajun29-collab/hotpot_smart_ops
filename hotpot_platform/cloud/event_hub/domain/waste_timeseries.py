"""Waste timeseries domain — 时序聚合 + 趋势对比 + 告警检测 (K-002).

纯函数，无FastAPI/DB依赖。被 db.py 和 routers/kitchen.py 调用。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def aggregate_waste_events(events: List[Dict[str, Any]], date: str) -> Dict[str, Any]:
    """从 events 列表中聚合某天的废料计数。

    Args:
        events: vlm_waste_estimate 事件的 dict 列表
        date: 日期字符串 YYYY-MM-DD

    Returns:
        {"date": "2026-07-16", "total_count": 153, "event_count": 8,
         "top_skus": [{"sku": "毛肚", "count": 45}, ...]}
    """
    total_count = 0
    event_count = len(events)
    sku_map: Dict[str, int] = {}

    for ev in events:
        payload = ev.get("payload", ev)
        meta = payload.get("metadata", payload.get("metadata", {}))
        items = meta.get("items", [])

        tc = meta.get("total_waste_count", 0)
        if tc and isinstance(tc, (int, float)):
            total_count += int(tc)
        else:
            # 从 items 累加
            for item in items:
                c = item.get("count", 0)
                if isinstance(c, (int, float)):
                    total_count += int(c)

        # 按 SKU 聚合
        for item in items:
            sku = item.get("sku", "unknown")
            count = item.get("count", 0)
            if isinstance(count, (int, float)) and count > 0:
                sku_map[sku] = sku_map.get(sku, 0) + int(count)

    # Top SKUs (按 count 降序取前10)
    top_skus = sorted(
        [{"sku": k, "count": v} for k, v in sku_map.items()],
        key=lambda x: -x["count"],
    )[:10]

    return {
        "date": date,
        "total_count": total_count,
        "event_count": event_count,
        "top_skus": top_skus,
    }


def compute_trend_comparison(daily: List[Dict[str, Any]]) -> Dict[str, Any]:
    """从 daily 列表计算同比/环比。

    Args:
        daily: 按日期升序排列的每日聚合列表，
               [{date, total_count, event_count, top_skus}, ...]

    Returns:
        {week_over_week, day_over_day, thirty_day_avg, seven_day_avg}
    """
    result: Dict[str, Any] = {
        "week_over_week": None,
        "day_over_day": None,
        "thirty_day_avg": 0.0,
        "seven_day_avg": 0.0,
    }

    if not daily:
        return result

    # ── 日环比：今天 vs 昨天 ──
    if len(daily) >= 2:
        today = daily[-1]["total_count"]
        yesterday = daily[-2]["total_count"]
        if yesterday > 0:
            change_pct = round((today - yesterday) / yesterday * 100, 1)
        elif today > 0:
            change_pct = 100.0  # 昨天为0，今天有数据
        else:
            change_pct = 0.0
        direction = "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat")
        result["day_over_day"] = {
            "today": today,
            "yesterday": yesterday,
            "change_pct": change_pct,
            "direction": direction,
        }
    elif len(daily) == 1:
        result["day_over_day"] = {
            "today": daily[-1]["total_count"],
            "yesterday": None,
            "change_pct": None,
            "direction": "flat",
        }

    # ── 周环比：最近7天 vs 前7天 ──
    if len(daily) >= 14:
        recent_7 = daily[-7:]
        prev_7 = daily[-14:-7]
        recent_vals = [d["total_count"] for d in recent_7 if d["total_count"] > 0]
        prev_vals = [d["total_count"] for d in prev_7 if d["total_count"] > 0]
        recent_avg = sum(recent_vals) / len(recent_vals) if recent_vals else 0.0
        prev_avg = sum(prev_vals) / len(prev_vals) if prev_vals else 0.0

        if prev_avg > 0:
            change_pct = round((recent_avg - prev_avg) / prev_avg * 100, 1)
        elif recent_avg > 0:
            change_pct = 100.0
        else:
            change_pct = 0.0
        direction = "up" if change_pct > 0 else ("down" if change_pct < 0 else "flat")
        result["week_over_week"] = {
            "current_avg": round(recent_avg, 1),
            "previous_avg": round(prev_avg, 1),
            "change_pct": change_pct,
            "direction": direction,
        }

    # ── 7日均值和30日均值 ──
    def _rolling_avg(data: List[Dict[str, Any]], window: int) -> float:
        window_data = data[-window:] if len(data) >= window else data
        non_zero = [d["total_count"] for d in window_data if d["total_count"] > 0]
        if not non_zero:
            return 0.0
        return round(sum(non_zero) / len(non_zero), 1)

    result["seven_day_avg"] = _rolling_avg(daily, 7)
    result["thirty_day_avg"] = _rolling_avg(daily, 30)

    return result


def check_alert(
    current_count: int,
    seven_day_avg: float,
    threshold: float = 1.5,
) -> Tuple[bool, float]:
    """判定是否触发告警。

    Args:
        current_count: 今日废料总数
        seven_day_avg: 7日移动均值
        threshold: 阈值倍数，默认1.5

    Returns:
        (triggered, ratio)
    """
    if seven_day_avg <= 0 or current_count <= 0:
        return False, 0.0
    ratio = round(current_count / seven_day_avg, 2)
    triggered = ratio > threshold
    return triggered, ratio


def format_alert_message(
    date: str,
    current_count: int,
    baseline_avg: float,
    ratio: float,
) -> str:
    """格式化告警消息文案。"""
    change_pct = round((ratio - 1) * 100)
    return (
        f"废料计数暴增：{date} 共计{current_count}件 "
        f"> 7日均值{baseline_avg:.1f}件 × 1.5，"
        f"环比+{change_pct}%"
    )
