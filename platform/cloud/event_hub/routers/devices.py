"""设备管理 — 边缘盒子注册 · 心跳 · 配置下发 (LOSS-600)

流程：
  盒子启动 → POST /v1/devices/register → Hub登记
  盒子定时 → GET /v1/devices/{id}/config → 拉最新配置
  管理员 → PUT /v1/devices/{id}/config → 改RTSP流/参数
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from platform.cloud.event_hub import runtime
from platform.cloud.event_hub.auth import AuthContext, get_auth_context
from shared.schemas import utc_now_iso

router = APIRouter()

# ─── 内存存储（后续可迁移到 hub.db） ───
_devices: Dict[str, dict] = {}


# ─── 请求/响应模型 ───

class DeviceRegisterRequest(BaseModel):
    device_id: str
    store_id: str
    device_type: str = "jetson"           # jetson | rk3588 | iot-gateway
    ip: str = ""
    hardware: Optional[Dict[str, Any]] = None   # {model, jetpack, memory_gb, ...}


class RTSPStream(BaseModel):
    zone: str                              # kitchen | front_hall
    url: str = ""                          # rtsp://...
    enabled: bool = True
    camera_id: str = "cam01"


class DeviceConfig(BaseModel):
    rtsp_streams: List[RTSPStream] = []
    inference_interval: int = 30           # 秒
    push_hub_url: str = "http://192.168.2.85:8098"
    labels: Optional[List[str]] = None     # 检测标签白名单


class DeviceStatus(BaseModel):
    device_id: str
    store_id: str
    device_type: str
    ip: str
    online: bool
    last_heartbeat: Optional[str] = None
    registered_at: Optional[str] = None
    config: DeviceConfig = DeviceConfig()


# ─── 端点 ───

@router.post("/v1/devices/register")
def device_register(body: DeviceRegisterRequest) -> dict:
    """盒子报到。首次注册或心跳续期。配置合并返回。"""
    now = utc_now_iso()
    dev = _devices.get(body.device_id)

    if dev is None:
        # 首次注册
        dev = {
            "device_id": body.device_id,
            "store_id": body.store_id,
            "device_type": body.device_type,
            "ip": body.ip,
            "hardware": body.hardware or {},
            "registered_at": now,
            "config": {
                "rtsp_streams": [],
                "inference_interval": 30,
                "push_hub_url": "http://192.168.2.85:8098",
            },
        }
        _devices[body.device_id] = dev
        runtime.hub.get_store(body.store_id).add_event({
            "event_type": "device_registered",
            "level": "info",
            "message": f"设备 {body.device_id} 首次注册 ({body.device_type})",
            "metadata": {"device_id": body.device_id, "store_id": body.store_id},
        })

    # 更新心跳
    dev["ip"] = body.ip or dev["ip"]
    dev["last_heartbeat"] = now

    return {
        "ok": True,
        "device_id": body.device_id,
        "config": dev.get("config", {}),
    }


@router.get("/v1/devices/{device_id}/config")
def device_get_config(device_id: str) -> dict:
    """盒子拉配置。"""
    dev = _devices.get(device_id)
    if dev is None:
        raise HTTPException(404, f"设备不存在: {device_id}")
    return {
        "ok": True,
        "device_id": device_id,
        "config": dev.get("config", {}),
    }


@router.put("/v1/devices/{device_id}/config")
def device_update_config(
    device_id: str,
    body: DeviceConfig,
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """管理员或Dashboard更新设备配置（RTSP流、推理参数）。"""
    dev = _devices.get(device_id)
    if dev is None:
        raise HTTPException(404, f"设备不存在: {device_id}")

    config = body.model_dump()
    dev["config"] = config

    runtime.hub.get_store(dev["store_id"]).add_event({
        "event_type": "device_config_updated",
        "level": "info",
        "message": f"设备 {device_id} 配置已更新",
        "metadata": {"device_id": device_id, "config": config},
    })

    return {"ok": True, "device_id": device_id, "config": config}


@router.get("/v1/devices")
def device_list(
    store_id: str = "",
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """列出所有设备。可按门店过滤。"""
    devices = []
    for d in _devices.values():
        if store_id and d["store_id"] != store_id:
            continue
        devices.append({
            "device_id": d["device_id"],
            "store_id": d["store_id"],
            "device_type": d["device_type"],
            "ip": d["ip"],
            "online": _is_online(d),
            "last_heartbeat": d.get("last_heartbeat"),
            "registered_at": d.get("registered_at"),
            "config": d.get("config", {}),
        })
    return {"devices": devices, "total": len(devices)}


@router.delete("/v1/devices/{device_id}")
def device_delete(device_id: str, auth: AuthContext = Depends(get_auth_context)) -> dict:
    """删除设备（管理员操作）。"""
    if device_id not in _devices:
        raise HTTPException(404, f"设备不存在: {device_id}")
    del _devices[device_id]
    return {"ok": True, "device_id": device_id}


# ─── 辅助 ───

def _is_online(dev: dict, timeout_seconds: int = 120) -> bool:
    hb = dev.get("last_heartbeat")
    if not hb:
        return False
    try:
        return (time.time() - _parse_iso(hb)) < timeout_seconds
    except Exception:
        return False


def _parse_iso(ts: str) -> float:
    from datetime import datetime, timezone
    dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
    return dt.timestamp()
