"""Event and data schemas for hotpot smart ops."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import uuid


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


class EventLevel(str, Enum):
    INFO = "info"
    WARN = "warn"
    CRITICAL = "critical"


class EventSource(str, Enum):
    VISION = "vision"
    IOT = "iot"
    POS = "pos"
    SYSTEM = "system"


class SourceStatus(str, Enum):
    """数据来源状态枚举 — 标识事件的生成方式，用于数据血缘追踪。

    所有生产环境事件必须标注 REAL；模拟/桩/混合来源的测试数据不得混入生产分析。
    """
    REAL = "real"           # 真实设备/系统产生
    SIMULATED = "simulated" # 模拟器产生(如 sensor_simulator)
    STUB = "stub"           # 桩桥接产生(如 iot_stub_bridge)
    MOCK = "mock"           # Mock/假数据(如 vision mock backend, vlm mock)
    HYBRID = "hybrid"       # 混合来源


@dataclass
class OpsEvent:
    event_type: str
    source: str
    level: str
    store_id: str
    message: str
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=utc_now_iso)
    zone: str = ""
    table_id: str = ""
    confidence: float = 1.0
    source_status: str = SourceStatus.REAL.value
    tenant_id: str = ""
    brand_id: str = ""
    region_id: str = ""
    device_id: str = ""
    operator_id: str = ""
    session_id: str = ""
    trace_id: str = ""
    parent_event_id: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TableState:
    table_id: str
    state: str  # empty | dining | need_clean | checkout
    confidence: float = 1.0
    updated_at: str = field(default_factory=utc_now_iso)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


TABLE_STATES = ("empty", "dining", "need_clean", "checkout")

KITCHEN_VIOLATIONS = ("kitchen_no_hat", "kitchen_no_mask", "kitchen_smoke")

IOT_ALERT_TYPES = ("cold_chain_high", "cold_chain_low", "gas_leak", "humidity_high")

SOP_EVENT_TYPES = ("sop_completed", "sop_violation", "sop_overdue")

COST_EVENT_TYPES = (
    "cost_price_over",
    "cost_weight_short",
    "cost_yield_low",
    "cost_quality_reject",
    "cost_near_expiry",
)

IOT_LIFECYCLE_EVENTS = (
    "iot_weight_short",
    "iot_temp_abnormal",
    "iot_door_open_timeout",
    "iot_rfid_missing",
    "iot_fefo_violation",
    "iot_thaw_overtime",
    "iot_humidity_abnormal",
)
