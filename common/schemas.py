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
