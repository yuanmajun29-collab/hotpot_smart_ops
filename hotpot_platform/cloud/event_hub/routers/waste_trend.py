"""废料趋势告警路由 — 时序存储 + 趋势对比 + 警报检测。

将废料识别结果按天聚合写入 waste_timeseries 表，
提供趋势查询和警报检查 API。

API:
  GET  /v1/waste/trend?store_id=&days=14
    返回趋势数据（daily/trend/dates/comparison）

  GET  /v1/waste/alert?store_id=
    返回趋势告警列表

  POST /v1/waste/alert/check?store_id=
    触发趋势告警检查（今日计数 vs 7日均值×1.5）
"""

from __future__ import annotations

from datetime import date as date_type, datetime, timezone
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
ROUTER_TAG = "waste_trend"


class WasteTrendWriteBody(BaseModel):
    """废料计数写入请求 - 每次 pipeline 结果到达时调用。"""
    store_id: Optional[str] = None
    zone: Optional[str] = None  # 后厨/前厅
    item_class: Optional[str] = None
    item_count: int = 0
    estimated_loss_amount: float = 0.0
    date: Optional[str] = None  # YYYY-MM-DD，默认今日


def _business_date(date: Optional[str]) -> str:
    """返回业务日期 YYYY-MM-DD。"""
    return date or date_type.today().isoformat()


def record_waste_to_timeseries(
    store_id: str,
    date: str,
    zone: str = "后厨",
    item_class: str = "general",
    item_count: int = 0,
    estimated_loss_amount: float = 0.0,
) -> None:
    """将一次 pipeline 废料计数写入时序表。

    采用 UPSERT 语义：同一天同一门店的数据会被聚合更新。
    由 routers/vlm.py 或 routers/kitchen.py 在每次废料事件时调用。
    """
    from hotpot_platform.cloud.event_hub.domain.waste_timeseries import aggregate_waste_events

    # 获取当日已有数据
    store = runtime.hub.get_store(store_id)
    existing = runtime.db.query_waste_trend(store_id, days=1, include_compare=False)
    daily = existing.get("daily", [])
    today_entry = daily[-1] if daily and daily[-1]["date"] == date else None

    # 合并当日计数
    total_count = (today_entry.get("total_count", 0) if today_entry else 0) + item_count
    event_count = (today_entry.get("event_count", 0) if today_entry else 0) + 1

    # 更新 top_skus
    top_skus: List[Dict[str, Any]] = list(today_entry.get("top_skus", [])) if today_entry else []
    # 合并 item_class 到 top_skus
    found = False
    for s in top_skus:
        if s.get("sku") == item_class:
            s["count"] = s.get("count", 0) + item_count
            s["estimated_loss_amount"] = s.get("estimated_loss_amount", 0) + estimated_loss_amount
            found = True
            break
    if not found:
        top_skus.append({
            "sku": item_class,
            "count": item_count,
            "zone": zone,
            "estimated_loss_amount": estimated_loss_amount,
        })
    # 只保留前 10
    top_skus.sort(key=lambda x: -x.get("count", 0))
    top_skus = top_skus[:10]

    runtime.db.upsert_waste_timeseries(store_id, date, total_count, event_count, top_skus)


@router.get("/api/v1/waste/trend")
def waste_trend(
    store_id: Optional[str] = Query(None, description="门店 ID"),
    days: int = Query(14, ge=1, le=90, description="查询天数 (1-90)"),
    include_compare: bool = Query(True, description="是否包含同比/环比"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """获取废料趋势数据。

    返回 daily/trend/dates/comparison，包含：
    - 日环比（today vs yesterday）
    - 周环比（本周 vs 上周同类废料数量对比）
    - 7日均值、30日均值

    **示例**:
    ```json
    {
      "store_id": "store_yuhuan",
      "days": 14,
      "daily": [{"date": "2026-07-10", "total_count": 42, ...}],
      "trend": [42, 38, 55, ...],
      "dates": ["2026-07-10", ...],
      "comparison": {
        "day_over_day": {"change_pct": 10.5, "direction": "up"},
        "week_over_week": {"change_pct": -3.2, "direction": "down"},
        "seven_day_avg": 45.3,
        "thirty_day_avg": 40.7
      }
    }
    ```
    """
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    return runtime.db.query_waste_trend(sid, days, include_compare)


@router.get("/api/v1/waste/alert")
def waste_alert_list(
    store_id: Optional[str] = Query(None, description="门店 ID"),
    days: int = Query(7, ge=1, le=90, description="查询天数"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """获取趋势告警列表。

    告警条件：连续3天超上周均值150% → 生成告警。
    返回最近 N 天的废料 spike 告警列表。
    """
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    alerts = runtime.db.list_waste_alerts(sid, days)
    return {
        "store_id": sid,
        "alerts": alerts,
        "count": len(alerts),
    }


@router.post("/api/v1/waste/alert/check")
def waste_alert_check(
    store_id: Optional[str] = Query(None, description="门店 ID"),
    date: Optional[str] = Query(None, description="检查日期 YYYY-MM-DD"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """触发废料趋势告警检查。

    检查今日废料计数是否超过 7日均值 × 1.5。
    幂等：同一天只创建一条 spike 告警。
    """
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    bdate = _business_date(date)
    return runtime.db.check_and_create_waste_alert(sid, bdate)


@router.post("/api/v1/waste/timeseries/write")
def waste_timeseries_write(
    body: WasteTrendWriteBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """写入废料时序数据。

    每次 pipeline 废料计数结果到达时调用，自动按天聚合到 waste_timeseries 表。

    **请求体**:
    ```json
    {
      "store_id": "store_yuhuan",
      "zone": "后厨",
      "item_class": "毛肚",
      "item_count": 12,
      "estimated_loss_amount": 156.0,
      "date": "2026-07-23"
    }
    ```
    """
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)

    bdate = _business_date(body.date)
    record_waste_to_timeseries(
        store_id=sid,
        date=bdate,
        zone=body.zone or "后厨",
        item_class=body.item_class or "general",
        item_count=body.item_count,
        estimated_loss_amount=body.estimated_loss_amount,
    )

    # 检查是否需要告警
    alert_result = runtime.db.check_and_create_waste_alert(sid, bdate)

    return {
        "ok": True,
        "store_id": sid,
        "date": bdate,
        "recorded_count": body.item_count,
        "alert": alert_result,
    }
