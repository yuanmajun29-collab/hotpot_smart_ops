"""IoT routes."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_write
from cloud.event_hub.routers._deps import resolve_store_id as _resolve_store_id, IotReadingsBatchBody
from cloud.event_hub.iot_readings_store import iot_readings_store
from cloud.event_hub.hub_core import DEFAULT_STORE_ID
from shared.iot_sensors import evaluate_sensor_health, sensor_profiles

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


@router.get("/v1/iot/devices")
def iot_devices(
    request: Request,
    store_id: Optional[str] = Query(None),
    required_only: bool = Query(True, description="仅返回 P1A 必选设备，默认 true"),
    hours: float = Query(24, ge=0.5, le=168),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Registered IoT device profiles + health (LOSS-501).

    Health is derived from the latest reading in ``iot_readings``. Missing or
    stale readings (> profile.health_max_age_sec, P1A default 5min) surface as
    offline, while fresh readings outside ``normal_range`` surface as out_of_range.
    """
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    readings = iot_readings_store(runtime.db).list_readings(sid, hours=hours, limit=2000)
    latest_by_sensor: Dict[str, Dict[str, Any]] = {}
    for reading in readings:
        sensor_id = reading.get("sensor_id")
        if sensor_id:
            latest_by_sensor[sensor_id] = reading

    devices = []
    status_counts: Dict[str, int] = {}
    for profile in sensor_profiles(sid, required_only=required_only):
        latest = latest_by_sensor.get(profile["sensor_id"])
        health = evaluate_sensor_health(profile, latest)
        status = health["status"]
        status_counts[status] = status_counts.get(status, 0) + 1
        devices.append({
            **profile,
            "latest_reading": latest,
            "health": health,
        })

    total = len(devices)
    online = status_counts.get("online", 0)
    return {
        "store_id": sid,
        "required_only": required_only,
        "devices": devices,
        "count": total,
        "summary": {
            "total": total,
            "online": online,
            "offline": status_counts.get("offline", 0),
            "out_of_range": status_counts.get("out_of_range", 0),
            "online_rate_pct": round(online / total * 100, 1) if total else 0,
        },
    }
