"""System routes."""
from __future__ import annotations

import os
import time
from typing import Any, Dict

from fastapi import APIRouter, Depends, Request

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
