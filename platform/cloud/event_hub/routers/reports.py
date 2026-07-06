"""Reports routes."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request

from platform.cloud.event_hub import runtime
from platform.cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_read
from platform.cloud.event_hub.hub_core import DEFAULT_STORE_ID
from platform.cloud.event_hub.daily_scheduler import generate_daily_report_for_store
from platform.cloud.event_hub.daily_report_store import daily_report_store
from platform.cloud.event_hub.routers._deps import (
    resolve_store_id as _resolve_store_id,
    DailyReportGenerateBody,
    _enforce_report_generate,
)

router = APIRouter()


@router.post("/v1/reports/daily/generate")
def daily_report_generate(
    body: DailyReportGenerateBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    if sid == "*":
        sid = DEFAULT_STORE_ID
    enforce_store_read(auth, sid)
    _enforce_report_generate(auth)
    return generate_daily_report_for_store(
        runtime.hub,
        runtime.db,
        runtime.alert_gateway,
        sid,
        push=body.push,
        report_date=body.report_date,
    )


@router.get("/v1/reports/daily")
def daily_report_list(
    request: Request,
    store_id: Optional[str] = Query(None),
    report_date: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=90),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    reports = daily_report_store(runtime.db).list_reports(sid, limit=limit, report_date=report_date)
    return {"store_id": sid, "reports": reports, "count": len(reports)}
