"""IoT routes."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_write
from cloud.event_hub.routers._deps import resolve_store_id as _resolve_store_id, IotReadingsBatchBody
from cloud.event_hub.iot_readings_store import iot_readings_store
from cloud.event_hub.hub_core import DEFAULT_STORE_ID

router = APIRouter()


@router.post("/v1/iot/readings/batch")
def iot_readings_batch(
    body: IotReadingsBatchBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    readings = [r.model_dump() for r in body.readings]
    n = iot_readings_store(runtime.db).insert_batch(sid, readings)
    return {"ok": True, "store_id": sid, "inserted": n}


@router.get("/v1/iot/readings")
def iot_readings_list(
    request: Request,
    store_id: Optional[str] = Query(None),
    sensor_id: Optional[str] = Query(None),
    hours: float = Query(24, ge=0.5, le=168),
    limit: int = Query(500, ge=1, le=2000),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    items = iot_readings_store(runtime.db).list_readings(
        sid, sensor_id=sensor_id, hours=hours, limit=limit
    )
    return {"store_id": sid, "sensor_id": sensor_id, "hours": hours, "readings": items, "count": len(items)}
