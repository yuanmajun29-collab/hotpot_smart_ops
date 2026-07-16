"""Daily waste report route — 废料日报 API (K-003)."""

from __future__ import annotations

from datetime import date as date_type
from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query

from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import (
    AuthContext,
    enforce_store_read,
    get_auth_context,
)
from hotpot_platform.cloud.event_hub.domain.daily_report import daily_report_for_store
from hotpot_platform.cloud.event_hub.hub_core import DEFAULT_STORE_ID

router = APIRouter()
ROUTER_TAG = "daily_report"
SHANGHAI_TZ = ZoneInfo("Asia/Shanghai")


def _business_date(value: Optional[str]) -> str:
    """返回业务日期 YYYY-MM-DD，并拒绝未来日期。"""
    if value:
        try:
            parsed = date_type.fromisoformat(value)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD") from exc
    else:
        parsed = datetime.now(SHANGHAI_TZ).date()

    if parsed > datetime.now(SHANGHAI_TZ).date():
        raise HTTPException(status_code=400, detail="date cannot be in the future")
    return parsed.isoformat()


def _live_waste_count_for_date(store_id: str, date: str) -> int:
    """聚合内存中尚未落库的 vlm_waste_estimate 计数。"""
    store = runtime.hub.get_store(store_id)
    live_events = store.get_events(limit=200)
    live_total = 0

    for ev in live_events:
        if ev.get("event_type") != "vlm_waste_estimate":
            continue
        if ev.get("timestamp", "")[:10] != date:
            continue
        meta = ev.get("metadata", {})
        items = meta.get("items", [])
        for item in items:
            count = item.get("count", 0)
            if isinstance(count, (int, float)):
                live_total += int(count)

    return live_total


@router.get("/api/daily-report")
def daily_report(
    store_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """废料日报 — 返回 Hero、30天趋势和最近告警。"""
    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    if sid == "*":
        sid = DEFAULT_STORE_ID
    enforce_store_read(auth, sid)

    bdate = _business_date(date)
    result = daily_report_for_store(runtime.db, sid, bdate)

    today = datetime.now(SHANGHAI_TZ).date().isoformat()
    if bdate == today:
        result["hero"]["total_waste_count"] += _live_waste_count_for_date(sid, bdate)

    return result
