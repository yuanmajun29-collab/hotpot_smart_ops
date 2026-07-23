"""IoT 食安传感器推理模块 — FastAPI router for Edge Agent."""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from edge.agent.config import API_KEY, DEVICE_ID, HUB_URL, STORE_ID
from edge.iot_food_safety import available_drivers, build_sensors, default_sensors
from edge.iot_food_safety.rules import DEFAULT_THRESHOLDS, merge_thresholds
from edge.iot_food_safety.sensor_bridge import SensorBridge


router = APIRouter(tags=["iot_food_safety"])

# 由 server.py 在配置驱动下设置
_active = False
_bridge: Optional[SensorBridge] = None
_last_snapshot: Optional[Dict[str, Any]] = None
buffer = None


class SensorConfig(BaseModel):
    """Sensor driver configuration accepted by the IoT endpoint."""

    sensor_id: str
    driver: str
    location: str = "kitchen"
    address: Optional[str] = None
    characteristic_uuid: Optional[str] = None
    serial_port: Optional[str] = None
    data_path: Optional[str] = None
    mock: Optional[bool] = None


class IotInferRequest(BaseModel):
    """IoT food-safety collection request."""

    sensors: Optional[List[SensorConfig]] = None
    alert_thresholds: Optional[Dict[str, Any]] = None
    push_hub: bool = True


def _check_active() -> None:
    if not _active:
        raise HTTPException(503, "iot_food_safety 模块未激活（配置中无 iot_food_safety zone）")


def _sensor_payload(config: SensorConfig) -> Dict[str, Any]:
    if hasattr(config, "model_dump"):
        return config.model_dump(exclude_none=True)
    return config.dict(exclude_none=True)


def _get_bridge(req: IotInferRequest) -> SensorBridge:
    """Build a request-scoped bridge when configs are supplied, otherwise reuse default bridge."""
    global _bridge
    thresholds = merge_thresholds(req.alert_thresholds)
    if req.sensors:
        sensors = build_sensors(_sensor_payload(cfg) for cfg in req.sensors)
        return SensorBridge(
            sensors=sensors,
            store_id=STORE_ID,
            device_id=DEVICE_ID,
            hub_url=HUB_URL,
            api_key=API_KEY,
            thresholds=thresholds,
            inference_buffer=buffer,
        )

    if _bridge is None:
        _bridge = SensorBridge(
            sensors=default_sensors(),
            store_id=STORE_ID,
            device_id=DEVICE_ID,
            hub_url=HUB_URL,
            api_key=API_KEY,
            thresholds=thresholds,
            inference_buffer=buffer,
        )
    else:
        _bridge.thresholds = thresholds
    return _bridge


@router.post("/infer/iot")
async def iot_infer(req: IotInferRequest) -> Dict[str, Any]:
    """Collect food-safety sensor readings, evaluate rules, and optionally push to Hub."""
    global _last_snapshot
    _check_active()
    started = time.perf_counter()
    bridge = _get_bridge(req)
    try:
        snapshot = await bridge.collect_once()
        forward_result = await bridge.forward(snapshot) if req.push_hub else {"skipped": True}
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:
        raise HTTPException(500, f"IoT 食安采集失败: {exc}") from exc
    _last_snapshot = snapshot
    return {
        "ok": True,
        "store_id": STORE_ID,
        "device_id": DEVICE_ID,
        "snapshot": snapshot,
        "hub": forward_result,
        "total_ms": round((time.perf_counter() - started) * 1000, 1),
    }


@router.get("/status/iot")
def iot_status() -> Dict[str, Any]:
    """Return IoT food-safety module status and the latest in-memory snapshot."""
    return {
        "module": "iot_food_safety",
        "active": _active,
        "hub": HUB_URL,
        "store_id": STORE_ID,
        "device_id": DEVICE_ID,
        "drivers": available_drivers(),
        "default_thresholds": DEFAULT_THRESHOLDS,
        "last_snapshot": _last_snapshot,
    }
