"""Kitchen waste routes — 废料计数趋势 API.

GET /api/kitchen/waste/stats?store_id=xxx&days=7
  返回最近 N 天的废料计数趋势 + 每日明细。

数据源：从 events 表中提取 vlm_waste_estimate 事件的计数信息。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_write
from hotpot_platform.cloud.event_hub.hub_core import DEFAULT_STORE_ID

router = APIRouter()
ROUTER_TAG = "kitchen"


@router.get("/api/kitchen/waste/stats")
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
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")

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
