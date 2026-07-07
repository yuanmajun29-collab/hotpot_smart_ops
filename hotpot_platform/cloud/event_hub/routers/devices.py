"""设备管理 — 设备注册 · 心跳 · 模块化配置下发 · 按大区/区域/门店聚合

层级模型：
  Zone(大区) → Region(区域) → Store(门店) → Device(推理设备, N个)

设备按模块配置：每个设备可启用 kitchen / front_hall / 等场景模块，
每个模块下挂 RTSP 摄像头列表。平台端可随时增减模块或摄像头。

流程：
  设备启动 → POST /v1/devices/register → Hub登记 + 返回已有配置
  设备定时 → POST /v1/devices/{id}/heartbeat → 续期 + 返回待下发配置
  管理员 → PUT /v1/devices/{id}/config → 按模块推送配置（平台→Hub→设备）
  管理员 → GET /v1/devices?zone_id=&region_id=&store_id= → 按层级过滤
"""

from __future__ import annotations

import time
import threading
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import AuthContext, get_auth_context
from common.schemas import utc_now_iso

router = APIRouter()

# ─── 持久化存储（线程安全） ───
_devices: Dict[str, dict] = {}
_devices_lock = threading.Lock()


def _save_devices():
    """将设备注册表持久化到 SQLite（Hub 重启可恢复）。"""
    with _devices_lock:
        data = {k: v for k, v in _devices.items()}
    try:
        runtime.hub.db.update_devices(data)
    except Exception:
        pass  # 持久化是 best-effort，不阻断业务


def _load_devices():
    """Hub 启动时从 SQLite 恢复设备注册表。"""
    try:
        persisted = runtime.hub.db.get_devices()
        if persisted:
            with _devices_lock:
                _devices.update(persisted)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# 模型定义
# ═══════════════════════════════════════════════════════════

class ModuleConfig(BaseModel):
    """单个推理模块配置。"""
    enabled: bool = True
    cameras: List[str] = []          # RTSP URL 列表
    inference_interval: int = 30     # 推理间隔(秒)
    rules: Dict[str, Any] = {}       # 模块级推理规则覆盖


class DeviceConfig(BaseModel):
    """设备配置：按模块组织。"""
    modules: Dict[str, ModuleConfig] = {}  # {"kitchen": {...}, "front_hall": {...}}


class DeviceRegisterRequest(BaseModel):
    device_id: str
    store_id: str
    ip: str = ""
    device_type: str = "jetson"          # jetson | rk3588
    hardware: Optional[Dict[str, Any]] = None
    active_modules: List[str] = []       # 当前激活的模块列表


class DeviceHeartbeatRequest(BaseModel):
    device_id: str
    active_modules: List[str] = []
    inference_count: int = 0
    last_frame_ts: Optional[str] = None
    metrics: Optional[Dict[str, Any]] = None  # GPU/CPU/内存


# ═══════════════════════════════════════════════════════════
# 设备注册
# ═══════════════════════════════════════════════════════════

@router.post("/v1/devices/register")
def device_register(body: DeviceRegisterRequest) -> dict:
    """设备注册。启动时向 Hub 报到，返回已有模块配置。"""
    now = utc_now_iso()
    with _devices_lock:
        existing = _devices.get(body.device_id)

        is_new = existing is None
        dev = {
            "device_id": body.device_id,
            "store_id": body.store_id,
            "ip": body.ip,
            "device_type": body.device_type,
            "hardware": body.hardware or {},
            "active_modules": body.active_modules,
            "modules": existing["modules"] if existing else {},
            "registered_at": existing["registered_at"] if existing else now,
            "last_heartbeat": now,
        }
        _devices[body.device_id] = dev
        modules_copy = dict(dev["modules"])
    _save_devices()

    if is_new:
        runtime.hub.get_store(body.store_id).add_event({
            "event_type": "device_registered",
            "level": "info",
            "message": f"设备 {body.device_id} 首次注册 ({body.device_type}, modules={body.active_modules})",
            "metadata": {"device_id": body.device_id, "store_id": body.store_id},
        })
    else:
        runtime.hub.get_store(body.store_id).add_event({
            "event_type": "device_online",
            "level": "info",
            "message": f"设备 {body.device_id} 重新上线",
        })

    return {
        "ok": True,
        "device_id": body.device_id,
        "config": _serialize_config(modules_copy),
    }


# ═══════════════════════════════════════════════════════════
# 心跳
# ═══════════════════════════════════════════════════════════

@router.post("/v1/devices/{device_id}/heartbeat")
def device_heartbeat(device_id: str, body: DeviceHeartbeatRequest) -> dict:
    """设备心跳续期 + 状态上报 + 返回待下发配置。"""
    now = utc_now_iso()
    with _devices_lock:
        dev = _devices.get(device_id)
        if dev is None:
            raise HTTPException(404, f"设备不存在: {device_id}")

        dev.update({
            "last_heartbeat": now,
            "active_modules": body.active_modules,
            "ip": body.metrics.get("ip", dev.get("ip", "")) if body.metrics else dev.get("ip", ""),
            "inference_count": body.inference_count,
            "last_frame_ts": body.last_frame_ts,
            "metrics": body.metrics,
        })

        # 返回待下发配置
        pending_config = None
        if dev.get("config_pending") and dev.get("modules"):
            pending_config = _serialize_config(dev["modules"])
            dev["config_pending"] = False
    _save_devices()

    return {
        "ok": True,
        "device_id": device_id,
        "config": pending_config,
    }


# ═══════════════════════════════════════════════════════════
# 配置拉取 + 下发
# ═══════════════════════════════════════════════════════════

@router.post("/v1/devices/{device_id}/pull-config")
def device_pull_config(device_id: str) -> dict:
    """设备主动拉取模块配置（不依赖心跳，更及时）。"""
    with _devices_lock:
        dev = _devices.get(device_id)
        if dev is None:
            raise HTTPException(404, f"设备不存在: {device_id}")

        config = _serialize_config(dev.get("modules", {}))
        dev["config_pending"] = False
    _save_devices()

    return {
        "ok": True,
        "device_id": device_id,
        "config": config,
    }


@router.put("/v1/devices/{device_id}/config")
def device_update_config(
    device_id: str,
    body: DeviceConfig,
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """管理员推送模块化配置（平台→Hub→设备下次心跳/拉取时下发）。"""
    with _devices_lock:
        dev = _devices.get(device_id)
        if dev is None:
            raise HTTPException(404, f"设备不存在: {device_id}")

        # 存储模块配置
        modules = {}
        for mod_name, mod in body.modules.items():
            modules[mod_name] = mod.model_dump()

        dev["modules"] = modules
        dev["config_pending"] = True
        module_names = list(modules.keys())
    _save_devices()

    return {
        "ok": True,
        "device_id": device_id,
        "modules": module_names,
        "pending": True,
    }


# ═══════════════════════════════════════════════════════════
# 设备列表 + 详情
# ═══════════════════════════════════════════════════════════

@router.get("/v1/devices")
def device_list(
    store_id: str = "",
    region_id: str = "",
    zone_id: str = "",
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """列出所有设备。支持按 门店/区域/大区 过滤。"""
    org_tree = runtime.org_registry.get_org_tree()

    # 构建 store → region → zone 映射
    store_to_region: Dict[str, str] = {}
    store_to_zone: Dict[str, str] = {}
    for r in org_tree.get("regions", []):
        for sid in r.get("store_ids", []):
            store_to_region[sid] = r.get("region_id", "")
    for z in org_tree.get("parent_regions", []):
        for rid in z.get("child_region_ids", []):
            for r in org_tree.get("regions", []):
                if r.get("region_id") == rid:
                    for sid in r.get("store_ids", []):
                        store_to_zone[sid] = z.get("zone_id", "")

    # 按 region/zone 过滤
    store_ids_filter: Optional[set] = None
    if region_id:
        target = next((r for r in org_tree.get("regions", []) if r.get("region_id") == region_id), None)
        if target:
            store_ids_filter = set(target.get("store_ids", []))
    if zone_id:
        target = next((z for z in org_tree.get("parent_regions", []) if z.get("zone_id") == zone_id), None)
        if target:
            zsids = set()
            for rid in target.get("child_region_ids", []):
                for r in org_tree.get("regions", []):
                    if r.get("region_id") == rid:
                        zsids.update(r.get("store_ids", []))
            store_ids_filter = store_ids_filter & zsids if store_ids_filter else zsids

    devices = []
    for did, dev in _devices.items():
        sid = dev["store_id"]
        if store_id and sid != store_id:
            continue
        if store_ids_filter is not None and sid not in store_ids_filter:
            continue

        devices.append(_serialize_device(did, dev, store_to_region, store_to_zone))

    return {"devices": devices, "total": len(devices)}


@router.get("/v1/devices/{device_id}")
def device_detail(device_id: str) -> dict:
    """设备详情 + 当前模块配置。"""
    with _devices_lock:
        dev = _devices.get(device_id)
        if dev is None:
            raise HTTPException(404, f"设备不存在: {device_id}")
        dev_copy = dict(dev)

    org_tree = runtime.org_registry.get_org_tree()
    store_to_region, store_to_zone = _build_store_maps(org_tree)

    return {
        **_serialize_device(device_id, dev_copy, store_to_region, store_to_zone),
        "config": _serialize_config(dev_copy.get("modules", {})),
    }


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════

def _serialize_config(modules: dict) -> dict:
    """序列化模块配置（ModuleConfig → 可下发格式）。"""
    return {
        "modules": {
            name: {
                "enabled": mod.get("enabled", True),
                "cameras": mod.get("cameras", []),
                "inference_interval": mod.get("inference_interval", 30),
                "rules": mod.get("rules", {}),
            }
            for name, mod in modules.items()
        }
    }


def _serialize_device(
    device_id: str,
    dev: dict,
    store_to_region: dict,
    store_to_zone: dict,
) -> dict:
    """序列化设备条目。"""
    sid = dev["store_id"]
    return {
        "device_id": device_id,
        "device_type": dev.get("device_type", "jetson"),
        "store_id": sid,
        "region_id": store_to_region.get(sid, ""),
        "zone_id": store_to_zone.get(sid, ""),
        "ip": dev.get("ip", ""),
        "online": _seconds_since(dev.get("last_heartbeat", "")) < 180,
        "last_heartbeat": dev.get("last_heartbeat"),
        "registered_at": dev.get("registered_at"),
        "active_modules": dev.get("active_modules", []),
        "inference_count": dev.get("inference_count", 0),
        "last_frame_ts": dev.get("last_frame_ts"),
        "modules": list(dev.get("modules", {}).keys()),
    }


def _build_store_maps(org_tree: dict) -> tuple:
    """构建 store→region + store→zone 映射。"""
    store_to_region: Dict[str, str] = {}
    store_to_zone: Dict[str, str] = {}
    for r in org_tree.get("regions", []):
        for sid in r.get("store_ids", []):
            store_to_region[sid] = r.get("region_id", "")
    for z in org_tree.get("parent_regions", []):
        for rid in z.get("child_region_ids", []):
            for r in org_tree.get("regions", []):
                if r.get("region_id") == rid:
                    for sid in r.get("store_ids", []):
                        store_to_zone[sid] = z.get("zone_id", "")
    return store_to_region, store_to_zone


def _seconds_since(ts: str) -> float:
    if not ts:
        return 999999
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return time.time() - dt.timestamp()
    except Exception:
        return 999999
