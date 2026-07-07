"""设备管理 — 网关(BOX)注册 · 心跳 · 配置下发 · 按大区/区域/门店聚合

层级模型：
  Zone(大区) → Region(区域) → Store(门店) → Gateway(网关, 1个) → Box(推理盒子, N个)

网关 = edge/agent server (:9100)，门店唯一入口，管 N 个同构推理盒子。
盒子功能完全相同（厨房+前厅推理），加盒子只为扩容更多摄像头/算力。

流程：
  网关启动 → POST /v1/gateways/register → Hub登记+所挂盒子列表
  网关定时 → POST /v1/gateways/{id}/heartbeat → 续期+盒子状态
  管理员 → PUT /v1/gateways/{id}/boxes/{bid}/config → 对单个盒子下发配置
  管理员 → GET /v1/devices?zone_id=&region_id=&store_id= → 按层级过滤
"""

from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import AuthContext, get_auth_context
from common.schemas import utc_now_iso

router = APIRouter()

# ─── 内存存储 ───
_gateways: Dict[str, dict] = {}  # gateway_id → {store_id, boxes, ...}


# ═══════════════════════════════════════════════════════════
# 网关管理
# ═══════════════════════════════════════════════════════════

class BoxInfo(BaseModel):
    box_id: str                           # box-01, box-02 ...
    device_type: str = "jetson"           # jetson | rk3588
    ip: str = ""
    active_zones: List[str] = []          # ["kitchen", "front_hall"]
    status: str = "online"                # online | degraded | offline
    inference_count: int = 0              # 累计推理次数
    last_frame_ts: Optional[str] = None   # 最后一帧时间


class GatewayRegisterRequest(BaseModel):
    gateway_id: str
    store_id: str
    ip: str = ""
    hardware: Optional[Dict[str, Any]] = None
    boxes: List[BoxInfo] = []             # 所挂推理盒子列表


class GatewayHeartbeatRequest(BaseModel):
    gateway_id: str
    boxes: List[BoxInfo] = []             # 盒子当前状态


class BoxConfig(BaseModel):
    rtsp_streams: List[Dict[str, Any]] = []
    inference_interval: int = 30
    active_zones: List[str] = []


@router.post("/v1/gateways/register")
def gateway_register(body: GatewayRegisterRequest) -> dict:
    """网关注册。首次注册或重启后重新报到，携所挂盒子完整列表。"""
    now = utc_now_iso()
    gw = _gateways.get(body.gateway_id)

    is_new = gw is None
    gw = {
        "gateway_id": body.gateway_id,
        "store_id": body.store_id,
        "ip": body.ip,
        "hardware": body.hardware or {},
        "boxes": {},
        "registered_at": gw["registered_at"] if gw else now,
        "last_heartbeat": now,
    }
    _gateways[body.gateway_id] = gw

    # 更新盒子状态
    for box in body.boxes:
        bid = box.box_id
        prev_online = gw["boxes"].get(bid, {}).get("online", False)
        gw["boxes"][bid] = {
            "box_id": bid,
            "device_type": box.device_type,
            "ip": box.ip,
            "active_zones": box.active_zones,
            "status": box.status,
            "online": True,
            "inference_count": box.inference_count,
            "last_frame_ts": box.last_frame_ts,
            "last_seen": now,
        }

        if is_new or not prev_online:
            runtime.hub.get_store(body.store_id).add_event({
                "event_type": "box_online" if not is_new else "box_registered",
                "level": "info",
                "message": f"盒子 {bid} {'上线' if not is_new else '首次注册'} ({box.device_type}, zones={box.active_zones})",
                "metadata": {
                    "gateway_id": body.gateway_id,
                    "box_id": bid,
                    "store_id": body.store_id,
                },
            })

    if is_new:
        runtime.hub.get_store(body.store_id).add_event({
            "event_type": "gateway_registered",
            "level": "info",
            "message": f"网关 {body.gateway_id} 首次注册 ({len(body.boxes)} 个盒子)",
            "metadata": {"gateway_id": body.gateway_id, "store_id": body.store_id, "box_count": len(body.boxes)},
        })

    # 返回已有配置（盒子登录即加载）
    box_configs: Dict[str, dict] = {}
    for bid, b in gw["boxes"].items():
        if b.get("config"):
            box_configs[bid] = b["config"]

    return {
        "ok": True,
        "gateway_id": body.gateway_id,
        "box_count": len(gw["boxes"]),
        "box_configs": box_configs,
    }


@router.post("/v1/gateways/{gateway_id}/heartbeat")
def gateway_heartbeat(gateway_id: str, body: GatewayHeartbeatRequest) -> dict:
    """网关心跳续期 + 上报盒子当前状态 + 返回待下发配置（平台→网关→盒子透传）。"""
    now = utc_now_iso()
    gw = _gateways.get(gateway_id)
    if gw is None:
        raise HTTPException(404, f"网关不存在: {gateway_id}")

    gw["last_heartbeat"] = now

    for box in body.boxes:
        bid = box.box_id
        existing = gw["boxes"].get(bid, {})
        gw["boxes"][bid] = {
            "box_id": bid,
            "device_type": box.device_type or existing.get("device_type", "jetson"),
            "ip": box.ip or existing.get("ip", ""),
            "active_zones": box.active_zones,
            "status": box.status,
            "online": True,
            "inference_count": box.inference_count,
            "last_frame_ts": box.last_frame_ts,
            "last_seen": now,
        }

    # 标记超时盒子为 offline
    for bid, b in gw["boxes"].items():
        if _seconds_since(b.get("last_seen", "")) > 180:
            b["online"] = False
            b["status"] = "offline"

    # 收集待下发配置，打包返回给网关（透传）
    pending_configs: Dict[str, dict] = {}
    for bid, b in gw["boxes"].items():
        if b.get("config_pending") and b.get("config"):
            pending_configs[bid] = b["config"]
            b["config_pending"] = False  # 已下发，清标记

    return {
        "ok": True,
        "gateway_id": gateway_id,
        "box_count": len(gw["boxes"]),
        "pending_configs": pending_configs,
    }


@router.post("/v1/gateways/{gateway_id}/pull-config")
def gateway_pull_config(gateway_id: str) -> dict:
    """网关主动拉取所有盒子的待下发配置（不依赖心跳，更及时）。"""
    gw = _gateways.get(gateway_id)
    if gw is None:
        raise HTTPException(404, f"网关不存在: {gateway_id}")

    configs: Dict[str, dict] = {}
    for bid, b in gw["boxes"].items():
        if b.get("config"):
            configs[bid] = b["config"]
            b["config_pending"] = False

    return {"ok": True, "gateway_id": gateway_id, "box_configs": configs}


@router.get("/v1/gateways/{gateway_id}/boxes")
def gateway_list_boxes(gateway_id: str) -> dict:
    """查看某网关下所有盒子。"""
    gw = _gateways.get(gateway_id)
    if gw is None:
        raise HTTPException(404, f"网关不存在: {gateway_id}")

    boxes = []
    for bid, b in gw["boxes"].items():
        boxes.append({
            "box_id": bid,
            "device_type": b.get("device_type", "jetson"),
            "ip": b.get("ip", ""),
            "online": b.get("online", False),
            "status": b.get("status", "unknown"),
            "active_zones": b.get("active_zones", []),
            "inference_count": b.get("inference_count", 0),
            "last_frame_ts": b.get("last_frame_ts"),
            "last_seen": b.get("last_seen"),
        })
    return {
        "gateway_id": gateway_id,
        "store_id": gw["store_id"],
        "boxes": boxes,
        "total": len(boxes),
    }


@router.put("/v1/gateways/{gateway_id}/boxes/{box_id}/config")
def gateway_update_box_config(
    gateway_id: str,
    box_id: str,
    body: BoxConfig,
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """管理员对单个盒子下发配置（RTSP流、推理参数）。"""
    gw = _gateways.get(gateway_id)
    if gw is None:
        raise HTTPException(404, f"网关不存在: {gateway_id}")
    if box_id not in gw["boxes"]:
        raise HTTPException(404, f"盒子不存在: {box_id} (gateway={gateway_id})")

    config = body.model_dump()
    gw["boxes"][box_id]["config"] = config
    gw["boxes"][box_id]["config_pending"] = True  # 网关下次心跳时拉取

    return {"ok": True, "gateway_id": gateway_id, "box_id": box_id, "config": config}


@router.get("/v1/gateways/{gateway_id}/overview")
def gateway_overview(gateway_id: str) -> dict:
    """网关+盒子运行概览（Dashboard 用）。"""
    gw = _gateways.get(gateway_id)
    if gw is None:
        raise HTTPException(404, f"网关不存在: {gateway_id}")

    boxes_online = sum(1 for b in gw["boxes"].values() if b.get("online"))
    boxes_total = len(gw["boxes"])

    return {
        "gateway_id": gateway_id,
        "store_id": gw["store_id"],
        "ip": gw.get("ip", ""),
        "online": _seconds_since(gw.get("last_heartbeat", "")) < 180,
        "last_heartbeat": gw.get("last_heartbeat"),
        "registered_at": gw.get("registered_at"),
        "boxes_online": boxes_online,
        "boxes_total": boxes_total,
        "boxes": [
            {
                "box_id": bid,
                "online": b.get("online", False),
                "status": b.get("status", "unknown"),
                "active_zones": b.get("active_zones", []),
            }
            for bid, b in gw["boxes"].items()
        ],
    }


# ═══════════════════════════════════════════════════════════
# 设备列表（兼容旧的 /v1/devices 查询，按大区/区域/门店过滤）
# ═══════════════════════════════════════════════════════════

@router.get("/v1/devices")
def device_list(
    store_id: str = "",
    region_id: str = "",
    zone_id: str = "",
    auth: AuthContext = Depends(get_auth_context),
) -> dict:
    """列出所有设备（网关+盒子）。支持按 门店/区域/大区 过滤。"""
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
    for gw_id, gw in _gateways.items():
        sid = gw["store_id"]
        if store_id and sid != store_id:
            continue
        if store_ids_filter is not None and sid not in store_ids_filter:
            continue

        # 网关条目
        devices.append({
            "type": "gateway",
            "device_id": gw_id,
            "store_id": sid,
            "region_id": store_to_region.get(sid, ""),
            "zone_id": store_to_zone.get(sid, ""),
            "ip": gw.get("ip", ""),
            "online": _seconds_since(gw.get("last_heartbeat", "")) < 180,
            "last_heartbeat": gw.get("last_heartbeat"),
            "box_count": len(gw["boxes"]),
            "boxes_online": sum(1 for b in gw["boxes"].values() if b.get("online")),
        })

        # 盒子条目
        for bid, b in gw["boxes"].items():
            devices.append({
                "type": "box",
                "device_id": bid,
                "gateway_id": gw_id,
                "store_id": sid,
                "region_id": store_to_region.get(sid, ""),
                "zone_id": store_to_zone.get(sid, ""),
                "device_type": b.get("device_type", "jetson"),
                "ip": b.get("ip", ""),
                "online": b.get("online", False),
                "active_zones": b.get("active_zones", []),
                "last_seen": b.get("last_seen"),
            })

    return {"devices": devices, "total": len(devices)}


# ═══════════════════════════════════════════════════════════
# 辅助
# ═══════════════════════════════════════════════════════════

def _seconds_since(ts: str) -> float:
    if not ts:
        return 999999
    try:
        from datetime import datetime, timezone
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return time.time() - dt.timestamp()
    except Exception:
        return 999999
