"""System routes."""

from __future__ import annotations

import os
import time
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel

from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import AuthContext, auth_mode, get_auth_context
from hotpot_platform.cloud.event_hub.hub_core import DEFAULT_STORE_ID
from hotpot_platform.cloud.event_hub.routers._deps import readable_store_ids as _readable_store_ids

router = APIRouter()

_START_TIME = time.time()


@router.get("/health")
def health() -> Dict[str, Any]:
    _database_url = os.environ.get("HOTPOT_DATABASE_URL", "")
    backend = "postgresql" if _database_url else "sqlite"

    # ── DB connectivity check ──
    db_status = "ok"
    db_error = None
    if runtime.db is not None:
        try:
            # Try a lightweight query to verify DB is reachable
            runtime.db._check_connectivity()
            db_status = "ok"
        except Exception as exc:
            db_status = "error"
            db_error = str(exc)[:200]
    else:
        db_status = "unavailable"
        db_error = "db instance not initialized"

    # ── event count ──
    event_count = 0
    if runtime.hub is not None:
        try:
            for sid in runtime.hub._registry:
                store = runtime.hub.get_store(sid)
                event_count += store.get_summary().get("total_events", 0)
        except Exception:
            pass

    return {
        "status": "ok" if db_status == "ok" else "degraded",
        "db_status": db_status,
        "db_error": db_error,
        "db_backend": backend,
        "event_count": event_count,
        "last_heartbeat": time.time(),
        "uptime_sec": round(time.time() - _START_TIME, 1),
        "multi_tenant": True,
        "engine": "fastapi",
        "auth_mode": auth_mode(),
        "persistent": True,
        "alert_gateway": True,
        "daily_report_scheduler": os.environ.get("HOTPOT_DAILY_REPORT_SCHEDULER", "1") == "1",
    }


@router.get("/metrics")
def metrics(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    _database_url = os.environ.get("HOTPOT_DATABASE_URL", "")
    store_ids = sorted(set(runtime.hub._registry) | set(runtime.hub._stores))
    store_ids = _readable_store_ids(store_ids, auth)
    total_events = 0
    total_critical = 0
    stores_with_data = 0
    for sid in store_ids:
        summary = runtime.hub.get_store(sid).get_summary()
        if summary.get("total_events") or runtime.hub.get_store(sid).has_data():
            stores_with_data += 1
        total_events += summary.get("total_events", 0)
        total_critical += (summary.get("by_level") or {}).get("critical", 0)
    return {
        "uptime_sec": round(time.time() - _START_TIME, 1),
        "store_count": len(store_ids),
        "stores_with_data": stores_with_data,
        "total_events": total_events,
        "total_critical": total_critical,
        "db_path": str(getattr(runtime.db, "db_path", "")),
        "db_backend": "postgresql" if _database_url else "sqlite",
        "auth_mode": auth_mode(),
    }


@router.post("/seed")
async def post_seed(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    if auth_mode() == "strict" and auth.auth_type == "anonymous":
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Seed requires auth")
    runtime.hub.apply_seed(data if isinstance(data, dict) else {})
    return {"ok": True, "store_id": data.get("store_id", DEFAULT_STORE_ID) if isinstance(data, dict) else DEFAULT_STORE_ID}


# ---------------------------------------------------------------------------
# WeChat notification endpoints (DEV-5xx)
# ---------------------------------------------------------------------------

class TestNotifyRequest(BaseModel):
    """Request body for sending a test WeChat notification."""
    message: str = "【测试】企微通知联调探针 - 请忽略"
    msgtype: str = "markdown"  # text, markdown
    webhook_url: Optional[str] = None  # override env-configured webhook


@router.post("/v1/system/notify/test")
def notify_test(
    body: TestNotifyRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Send a test message via WeChat Work webhook.

    Verifies: webhook URL configured, message delivered (or delivers
    diagnosable error). Useful for integration check after config changes.
    """
    try:
        from hotpot_platform.cloud.event_hub.wechat_notifier import get_notifier
    except ImportError:
        return {"ok": False, "error": "wechat_notifier module not importable"}

    notifier = get_notifier()
    webhook_url = body.webhook_url or notifier.webhook_url

    if not webhook_url:
        return {
            "ok": False,
            "error": (
                "webhook_url not configured - set WECHAT_WEBHOOK_URL "
                "or provide webhook_url in request body"
            ),
        }

    sent = False
    if body.msgtype == "text":
        sent = notifier.send_text(body.message, webhook_url=webhook_url)
    elif body.msgtype == "markdown":
        sent = notifier.send_markdown(body.message, webhook_url=webhook_url)
    else:
        return {"ok": False, "error": "msgtype must be text or markdown", "msgtype": body.msgtype}

    return {
        "ok": sent,
        "webhook_url_masked": _mask_url(webhook_url) if notifier else "",
        "msgtype": body.msgtype,
        "stats": notifier.stats.snapshot(),
    }


@router.get("/v1/system/notify/status")
def notify_status(
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Return WeChat notification push statistics and config."""
    if runtime.alert_gateway is not None:
        status = runtime.alert_gateway.get_notify_status()
    else:
        try:
            from hotpot_platform.cloud.event_hub.wechat_notifier import get_notifier
            notifier = get_notifier()
            status = notifier.get_status()
            status["available"] = True
        except ImportError:
            status = {"available": False, "reason": "wechat_notifier not importable"}
    return status


def _mask_url(url: str) -> str:
    if not url:
        return ""
    if len(url) <= 24:
        return url[:8] + "…"
    return url[:20] + "…" + url[-6:]


# ── K-006: 翻台率真实计算 API ──

@router.get("/api/v1/turnover/rate")
def turnover_rate(
    store_id: Optional[str] = Query(None, description="门店 ID"),
    window: str = Query("daily", description="时间窗口: daily / weekly / monthly"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """获取真实翻台率 — 从 table_history 计算。

    不返回静态建议，而是基于桌态变化历史计算：
      turnover_rate = completed_tables / total_tables / time_window_days

    **查询参数**:
    - store_id: 门店 ID（默认从认证获取）
    - window: 时间窗口 daily(当天) / weekly(本周) / monthly(本月)

    **响应示例**:
    ```json
    {
      "date": "2026-07-23",
      "window": "daily",
      "total_tables": 45,
      "completed_tables": 52,
      "turnover_rate": 1.156,
      "avg_dine_min": 48.3,
      "avg_clean_min": 4.2,
      "avg_wait_min": 6.8,
      "details": [
        {"table_id": "T01", "completed_cycles": 2},
        ...
      ]
    }
    ```
    """
    from hotpot_platform.cloud.event_hub.domain.turnover import compute_turnover_rate
    from datetime import date as _date_type

    sid = store_id or auth.store_id or DEFAULT_STORE_ID
    store = runtime.hub.get_store(sid)

    # 时间窗口映射
    window_map = {
        "daily": 24.0,
        "weekly": 168.0,  # 7 * 24
        "monthly": 720.0,  # 30 * 24
    }
    hours = window_map.get(window, 24.0)

    total_tables = len(store.table_states) or 1  # 防止除零

    # 从 table_history 或 events 推断翻台
    table_history = getattr(store, "table_history", {})

    # 如果 history 为空，从 events 构建
    if not table_history:
        events = list(store.events)
        table_events = {}
        for ev in events:
            if not ev.get("table_id"):
                continue
            tid = ev["table_id"]
            st = ev.get("event_type", "").replace("table_", "")
            if st:
                if tid not in table_events:
                    table_events[tid] = []
                table_events[tid].append({
                    "status": st,
                    "changed_at": ev.get("timestamp", ""),
                    "duration_min": 0.0,
                })
        # 按时间排序
        for tid in table_events:
            table_events[tid].sort(key=lambda x: x["changed_at"])
        table_history = table_events

    result = compute_turnover_rate(
        table_history=table_history,
        total_tables=total_tables,
        window_hours=hours,
    )

    return {
        "date": _date_type.today().isoformat(),
        "window": window,
        "store_id": sid,
        **result,
    }
