"""System routes."""
from __future__ import annotations

import os
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

from cloud.event_hub import runtime
from cloud.event_hub.auth import AUTH_MODE, AuthContext, get_auth_context
from cloud.event_hub.hub_core import DEFAULT_STORE_ID

router = APIRouter()

_START_TIME = time.time()


@router.get("/health")
def health() -> Dict[str, Any]:
    _database_url = os.environ.get("HOTPOT_DATABASE_URL", "")
    backend = "postgresql" if _database_url else "sqlite"
    return {
        "status": "ok",
        "multi_tenant": True,
        "engine": "fastapi",
        "auth_mode": AUTH_MODE,
        "persistent": True,
        "alert_gateway": True,
        "db_backend": backend,
        "daily_report_scheduler": os.environ.get("HOTPOT_DAILY_REPORT_SCHEDULER", "1") == "1",
        "uptime_sec": round(time.time() - _START_TIME, 1),
    }


@router.get("/metrics")
def metrics(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    _database_url = os.environ.get("HOTPOT_DATABASE_URL", "")
    store_ids = sorted(set(runtime.hub._registry) | set(runtime.hub._stores))
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
        "auth_mode": AUTH_MODE,
    }


@router.post("/seed")
async def post_seed(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    if AUTH_MODE == "strict" and auth.auth_type == "anonymous":
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail="Seed requires auth")
    runtime.hub.apply_seed(data if isinstance(data, dict) else {})
    return {"ok": True, "store_id": data.get("store_id", DEFAULT_STORE_ID) if isinstance(data, dict) else DEFAULT_STORE_ID}
