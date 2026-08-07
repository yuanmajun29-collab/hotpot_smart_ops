"""
统一边缘事件契约 (P0-B: 改造方案要求)

POST /api/v1/edge/events — 边缘设备批量上报事件

改造方案核心要求:
- 幂等: 通过 idempotency_key 去重
- 批量: 单次请求支持多事件
- 证据引用: evidence_ref 关联图像/视频片段
- 离线回放: offline_buffer 标记离线缓存数据
- 死信: 无法处理的事件进入死信队列

目标架构:
  摄像机 → Edge → YOLO/VLM → [统一契约] → Hub PG → Agent → 人工 → KPI

API 路径规范 (改造方案要求):
- 统一使用 /api/v1/ 前缀 (不再混用 /v1)
- 边缘事件入口: /api/v1/edge/events
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel, Field

from hotpot_platform.cloud.event_hub.auth import AuthContext, enforce_store_write, get_auth_context

router = APIRouter()


# ── 统一事件契约 Schema ──

class EventSeverity(str, Enum):
    """事件严重程度"""
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


class EventType(str, Enum):
    """标准事件类型 (改造方案四大闭环)"""
    # 后厨损耗与出品闭环
    WASTE_DETECTED = "waste_detected"              # 废料检测
    SOP_VIOLATION = "sop_violation"                # SOP违规
    DISH_OUTPUT = "dish_output"                    # 出品记录
    FOOD_QUALITY = "food_quality"                  # 食材品质

    # 收货/供应链闭环
    RECEIVING_START = "receiving_start"            # 收货开始
    RECEIVING_COMPLETE = "receiving_complete"      # 收货完成
    RECEIVING_REJECT = "receiving_reject"          # 收货拒收
    INVENTORY_ALERT = "inventory_alert"            # 库存预警

    # 前厅服务与翻台闭环
    TABLE_DIRTY = "table_dirty"                    # 脏桌检测
    TABLE_CLEANED = "table_cleaned"                # 清台完成
    SERVICE_TIMEOUT = "service_timeout"            # 服务超时
    CUSTOMER_ENTRY = "customer_entry"              # 客流进入

    # 销售增长闭环
    POS_ORDER = "pos_order"                        # POS订单
    SKU_SALES = "sku_sales"                        # SKU销量
    PROMO_TRIGGER = "promo_trigger"                # 推荐触发

    # 系统事件
    DEVICE_HEARTBEAT = "device_heartbeat"          # 设备心跳
    CONFIG_ACK = "config_ack"                      # 配置确认
    MODEL_INFERENCE = "model_inference"            # 模型推理结果


class EvidenceRef(BaseModel):
    """证据引用 (关联图像/视频/VLM结果)"""
    type: str = Field(..., description="证据类型: image/video/vlm_result")
    url: Optional[str] = Field(None, description="对象存储URL或本地路径")
    hash_sha256: Optional[str] = Field(None, content_type="SHA256哈希值")
    captured_at: Optional[str] = Field(None, description="采集时间 ISO8601")
    camera_id: Optional[str] = Field(None, description="来源摄像机ID")
    frame_index: Optional[int] = Field(None, description="帧序号")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class UnifiedEdgeEvent(BaseModel):
    """
    统一边缘事件 (P0-B 改造方案)

    每个事件必须包含:
    - event_id: 全局唯一ID (或由服务端生成)
    - event_type: 标准事件类型
    - store_id: 门店标识
    - device_id: 边缘设备标识
    - timestamp: 事件时间
    - payload: 业务载荷 (自由结构)
    """
    # 必填字段
    event_type: EventType = Field(..., description="标准事件类型")
    store_id: str = Field(..., description="门店ID")
    device_id: str = Field(..., description="边缘设备ID")
    timestamp: str = Field(..., description="事件时间 ISO8601")
    payload: Dict[str, Any] = Field(..., description="业务载荷")

    # 可选字段 (推荐)
    event_id: Optional[str] = Field(None, description="全局唯一事件ID (不填则自动生成)")
    idempotency_key: Optional[str] = Field(None, description="幂等键 (用于去重)")
    severity: EventSeverity = Field(EventSeverity.INFO, description="严重程度")
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0, description="模型置信度")

    # 证据引用
    evidence_ref: Optional[EvidenceRef] = Field(None, description="证据引用")

    # 来源追踪
    source_event_id: Optional[str] = Field(None, description="源事件ID (链式追踪)")
    trace_id: Optional[str] = Field(None, description="分布式追踪ID")

    # 离线标记
    is_offline_buffer: bool = Field(False, description="是否为离线缓存回放数据")
    buffered_at: Optional[str] = Field(None, description="离线缓存时间")


class BatchEventsRequest(BaseModel):
    """批量事件上报请求"""
    events: List[UnifiedEdgeEvent] = Field(..., min_items=1, max_items=100, description="事件列表 (1-100)")
    batch_id: Optional[str] = Field(None, description="批次ID (用于追踪)")
    device_heartbeat: Optional[Dict[str, Any]] = Field(None, description="附带设备心跳信息")


class BatchEventsResponse(BaseModel):
    """批量事件上报响应"""
    batch_id: str
    accepted: int                                      # 成功接受数
    rejected: int                                      # 拒绝数
    duplicates: int                                    # 重复(幂等)数
    event_ids: List[str]                               # 已分配的事件ID列表
    errors: List[Dict[str, str]]                       # 错误详情 [{event_index, reason}]
    processed_at: str                                  # 处理时间


# ── 内存级幂等去重 (生产应使用Redis) ──

_idempotency_store: Dict[str, float] = {}  # key -> timestamp
_IDEMPOTENCY_TTL_SECONDS = 3600  # 1小时


def _is_duplicate(idempotency_key: str) -> bool:
    """检查是否重复 (幂等)"""
    if not idempotency_key:
        return False
    now = time.time()
    if idempotency_key in _idempotency_store:
        if now - _idempotency_store[idempotency_key] < _IDEMPOTENCY_TTL_SECONDS:
            return True
        else:
            del _idempotency_store[idempotency_key]
    _idempotency_store[idempotency_key] = now
    return False


def _generate_event_id() -> str:
    """生成全局唯一事件ID"""
    return f"evt_{uuid.uuid4().hex[:12]}_{int(time.time() * 1000)}"


# ── API 端点 ──

@router.post("/api/v1/edge/events", response_model=BatchEventsResponse)
async def submit_edge_events(
    request: BatchEventsRequest,
    x_store_id: Optional[str] = Header(None, alias="X-Store-Id"),
    x_device_id: Optional[str] = Header(None, alias="X-Device-Id"),
    x_edge_version: Optional[str] = Header(None, alias="X-Edge-Version"),
    auth: AuthContext = Depends(get_auth_context),
):
    """
    统一边缘事件上报 (P0-B 核心端点)

    改造方案要求:
    - 批量支持: 单次最多100个事件
    - 幂等: 相同 idempotency_key 不重复处理
    - 证据: 支持 image/video/vlm_result 引用
    - 审计: 记录来源、版本、处理时间

    Example:
      POST /api/v1/edge/events
      {
        "events": [{
          "event_type": "waste_detected",
          "store_id": "store_jiaojiang",
          "device_id": "jetson_jiaojiang_001",
          "timestamp": "2026-08-05T01:00:00+08:00",
          "payload": {"waste_type": "food_waste", "estimated_weight_g": 150},
          "confidence": 0.92,
          "evidence_ref": {
            "type": "image",
            "camera_id": "cam_a1_main",
            "hash_sha256": "abc123..."
          }
        }]
      }
    """
    batch_id = request.batch_id or f"batch_{uuid.uuid4().hex[:8]}_{int(time.time() * 1000)}"
    accepted = 0
    rejected = 0
    duplicates = 0
    event_ids = []
    errors = []

    # 请求头、认证门店与每一条事件必须一致，禁止用一个设备凭证跨店写入。
    for event in request.events:
        if x_store_id and event.store_id != x_store_id:
            raise HTTPException(status_code=400, detail="X-Store-Id 与事件 store_id 不一致")
        if x_device_id and event.device_id != x_device_id:
            raise HTTPException(status_code=400, detail="X-Device-Id 与事件 device_id 不一致")
        enforce_store_write(auth, event.store_id)

    for idx, event in enumerate(request.events):
        idemp_key = ""
        try:
            # 1. 验证必填字段
            if not event.event_type or not event.store_id or not event.device_id or not event.timestamp:
                raise ValueError("缺少必填字段: event_type/store_id/device_id/timestamp")

            # 2. 幂等检查
            idemp_key = event.idempotency_key or f"{event.event_type}:{event.device_id}:{event.timestamp}:{hashlib.md5(json.dumps(event.payload, sort_keys=True).encode()).hexdigest()[:16]}"
            if _is_duplicate(idemp_key):
                duplicates += 1
                continue

            # 3. 分配事件ID
            evt_id = event.event_id or _generate_event_id()
            canonical_event = {
                "event_id": evt_id,
                "event_type": event.event_type.value,
                "store_id": event.store_id,
                "device_id": event.device_id,
                "timestamp": event.timestamp,
                "level": event.severity.value,
                "source": "edge",
                "confidence": event.confidence,
                "payload": event.payload,
                "metadata": {
                    "idempotency_key": idemp_key,
                    "trace_id": event.trace_id,
                    "source_event_id": event.source_event_id,
                    "offline_buffer": event.is_offline_buffer,
                    "buffered_at": event.buffered_at,
                    "edge_version": x_edge_version,
                    "evidence_ref": event.evidence_ref.model_dump() if event.evidence_ref else None,
                },
            }
            # 任务工厂、桌态等既有领域逻辑读取顶层字段；仅将允许的
            # 业务字段投影出来，不让任意 payload 覆盖身份/审计字段。
            for key in ("message", "table_id", "zone", "camera_id"):
                if key in event.payload:
                    canonical_event[key] = event.payload[key]

            # 4. 单一 Hub 主写：EventStore 的持久化钩子写 SQLite/PG。
            from hotpot_platform.cloud.event_hub import runtime
            from hotpot_platform.cloud.event_hub.task_factory import spawn_task_for_event

            if runtime.hub is None or runtime.db is None:
                raise RuntimeError("Event Hub runtime is not initialized")
            runtime.hub.get_store(event.store_id).add_event(canonical_event)
            spawn_task_for_event(runtime.db, event.store_id, canonical_event)
            event_ids.append(evt_id)
            accepted += 1

        except ValueError as ve:
            if idemp_key:
                _idempotency_store.pop(idemp_key, None)
            rejected += 1
            errors.append({"event_index": str(idx), "reason": str(ve)})
        except Exception as ex:
            # 仅在成功写入 Hub 后保留幂等键；失败请求必须可由 Edge 重试。
            if idemp_key:
                _idempotency_store.pop(idemp_key, None)
            rejected += 1
            errors.append({"event_index": str(idx), "reason": f"内部错误: {str(ex)}"})

    return BatchEventsResponse(
        batch_id=batch_id,
        accepted=accepted,
        rejected=rejected,
        duplicates=duplicates,
        event_ids=event_ids,
        errors=errors,
        processed_at=datetime.now(timezone.utc).isoformat(),
    )


@router.get("/api/v1/edge/events/schema")
async def get_event_schema(auth: AuthContext = Depends(get_auth_context)):
    """
    获取统一事件契约 Schema (供边缘设备校验使用)

    返回所有支持的 event_type、必填字段、枚举值等元信息
    """
    return {
        "version": "1.0.0",
        "contract_name": "hotpot_edge_events_v1",
        "updated_at": "2026-08-05T01:00:00+08:00",
        "event_types": [et.value for et in EventType],
        "severity_levels": [s.value for s in EventSeverity],
        "required_fields": ["event_type", "store_id", "device_id", "timestamp", "payload"],
        "recommended_fields": ["event_id", "idempotency_key", "severity", "confidence", "evidence_ref"],
        "evidence_types": ["image", "video", "vlm_result"],
        "idempotency_ttl_seconds": _IDEMPOTENCY_TTL_SECONDS,
        "batch_limits": {"min": 1, "max": 100},
        "headers": {
            "X-Store-Id": "门店ID (可选，覆盖body中的store_id)",
            "X-Device-Id": "设备ID (可选，用于审计)",
            "X-Edge-Version": "边缘端版本号 (可选，用于兼容性判断)",
        },
    }


@router.get("/api/v1/edge/events/idempotency/stats")
async def get_idempotency_stats(auth: AuthContext = Depends(get_auth_context)):
    """幂等去重统计 (运维用)"""
    now = time.time()
    active_keys = sum(1 for t in _idempotency_store.values() if now - t < _IDEMPOTENCY_TTL_SECONDS)
    return {
        "active_idempotency_keys": active_keys,
        "total_stored": len(_idempotency_store),
        "ttl_seconds": _IDEMPOTENCY_TTL_SECONDS,
    }


# ── 兼容性: 旧版 /v1/events 映射到新契约 ──

@router.post("/v1/events", response_model=BatchEventsResponse, deprecated=True)
async def post_events_legacy(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
):
    """
    [已废弃] 旧版事件接口

    改造方案要求: 统一迁移到 /api/v1/edge/events
    本端点保留向后兼容，自动转换为新契约格式
    """
    data = await request.json()

    # 尝试将旧格式转换为新契约
    events_data = data if isinstance(data, list) else [data]
    unified_events = []

    for evt in events_data:
        evt_type_str = evt.get("type", evt.get("event_type", "model_inference"))
        try:
            evt_type = EventType(evt_type_str)
        except ValueError:
            evt_type = EventType.MODEL_INFERENCE

        unified_events.append(UnifiedEdgeEvent(
            event_type=evt_type,
            store_id=evt.get("store_id", "unknown"),
            device_id=evt.get("device_id", evt.get("source", "unknown")),
            timestamp=evt.get("timestamp", evt.get("time", datetime.now(timezone.utc).isoformat())),
            payload=evt.get("payload", evt.get("data", evt)),
            severity=EventSeverity(evt.get("level", "info")) if evt.get("level") in ("info", "warning", "error", "critical") else EventSeverity.INFO,
            confidence=evt.get("confidence"),
        ))

    batch_request = BatchEventsRequest(events=unified_events)
    return await submit_edge_events(batch_request, auth=auth)
