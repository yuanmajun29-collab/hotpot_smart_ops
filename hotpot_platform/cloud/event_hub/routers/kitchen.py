"""Kitchen waste routes — 废料计数统计 + 趋势预警 + 告警 API.

GET /api/kitchen/waste/stats?store_id=xxx&days=7
  返回最近 N 天的废料计数趋势 + 每日明细（从 events 表查询）。

GET /api/kitchen/waste/trend?store_id=xxx&days=30&include_compare=true
  返回 waste_timeseries 表的趋势 + 环比对比。

GET /api/kitchen/waste/alerts?store_id=xxx&days=7
  返回最近 N 天的废料告警列表。

POST /api/kitchen/waste/alerts/check
  触发告警检查（今日 vs 7日均值 ×1.5）。

POST /api/kitchen/waste/alerts/{alert_id}/ack
  确认告警。
"""

from __future__ import annotations

from datetime import datetime, timezone, date as date_type
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import (
    AuthContext,
    enforce_store_write,
    get_auth_context,
)
from hotpot_platform.cloud.event_hub.hub_core import DEFAULT_STORE_ID

router = APIRouter()
ROUTER_TAG = "kitchen"


class AlertCheckBody(BaseModel):
    date: Optional[str] = None
    current_count: Optional[int] = None


def _business_date(date: Optional[str]) -> str:
    """返回业务日期 YYYY-MM-DD。"""
    return date or date_type.today().isoformat()


# ── 已有端点: waste/stats ─────────────────────────────────────

@router.get("/api/v1/kitchen/waste/stats")
def kitchen_waste_stats(
    store_id: Optional[str] = Query(None, description="门店 ID，默认当前门店"),
    days: int = Query(7, ge=1, le=90, description="查询天数 (1-90)"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """废料计数趋势 — 返回最近 N 天的计数聚合。

    **响应示例**:
    ```json
    {
      "store_id": "store_yuhuan",
      "days": 7,
      "daily": [
        {
          "date": "2026-07-16",
          "total_count": 153,
          "event_count": 8,
          "items": [
            {"sku": "毛肚", "count": 45, "waste_type": "备餐废弃"},
            {"sku": "鸭肠", "count": 30, "waste_type": "边角料"}
          ]
        }
      ],
      "trend": [153, 128, 172, 0, 145, 168, 190],
      "dates": ["2026-07-10", "2026-07-11", ...],
      "generated_at": "2026-07-16T15:30:00+00:00"
    }
    ```

    `trend` 数组与 `dates` 数组一一对应，可直接用于前端折线图。
    """
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    stats = runtime.db.query_waste_count_stats(sid, days)

    # ── 同时补充内存中最新的事件（未落 DB 的） ──
    store = runtime.hub.get_store(sid)
    live_events = store.get_events(limit=200)
    from datetime import timedelta as _td

    cutoff = (datetime.now(timezone.utc) - _td(days=days)).strftime("%Y-%m-%d")

    live_total = 0
    for ev in live_events:
        if ev.get("event_type") != "vlm_waste_estimate":
            continue
        ts = ev.get("timestamp", "")[:10]
        if ts < cutoff:
            continue
        meta = ev.get("metadata", {})
        items = meta.get("items", [])
        for item in items:
            c = item.get("count", 0)
            if isinstance(c, (int, float)):
                live_total += int(c)

    stats["live_count"] = live_total

    return stats


# ── K-002: 趋势 API ───────────────────────────────────────────

@router.get("/api/v1/kitchen/waste/trend")
def kitchen_waste_trend(
    store_id: Optional[str] = Query(None, description="门店 ID"),
    days: int = Query(30, ge=1, le=90, description="查询天数 (1-90)"),
    include_compare: bool = Query(True, description="是否包含同比/环比"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """废料趋势 — 从 waste_timeseries 表查询 + 环比对比。

    返回 daily（每日明细）、trend（每日计数数组）、dates（日期数组）、
    comparison（日环比/周环比/7日均值/30日均值）。
    """
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    return runtime.db.query_waste_trend(sid, days, include_compare)


# ── K-002: 告警 API ───────────────────────────────────────────

@router.get("/api/v1/kitchen/waste/alerts")
def kitchen_waste_alerts(
    store_id: Optional[str] = Query(None, description="门店 ID"),
    days: int = Query(7, ge=1, le=90, description="查询天数"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """废料告警列表 — 返回最近 N 天的告警。"""
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    alerts = runtime.db.list_waste_alerts(sid, days)
    return {
        "store_id": sid,
        "alerts": alerts,
        "count": len(alerts),
    }


@router.post("/api/v1/kitchen/waste/alerts/check")
def kitchen_waste_alerts_check(
    body: Optional[AlertCheckBody] = None,
    store_id: Optional[str] = Query(None, description="门店 ID"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """触发废料告警检查。

    检查今日废料计数是否超过 7日均值 × 1.5。
    如果 body 包含 date/current_count 则使用之，否则从 waste_timeseries 查询。
    幂等：同一天只创建一条 spike 告警。
    """
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    bdate = _business_date(body.date if body else None)

    # 如果传了 current_count，先写入 waste_timeseries
    if body and body.current_count is not None:
        from hotpot_platform.cloud.event_hub.domain.waste_timeseries import aggregate_waste_events
        runtime.db.upsert_waste_timeseries(
            sid, bdate, body.current_count, 1, [],
        )

    return runtime.db.check_and_create_waste_alert(sid, bdate)


@router.post("/api/v1/kitchen/waste/alerts/{alert_id}/ack")
def kitchen_waste_alert_ack(
    alert_id: int,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """确认废料告警。"""
    ok = runtime.db.ack_waste_alert(alert_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"告警不存在: {alert_id}")
    return {"ok": True, "alert_id": alert_id}
