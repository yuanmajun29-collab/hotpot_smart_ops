"""
事件上下文组装层 — 为 Agent 准备有限、可靠、可追溯的输入

不是把所有传感器读数都扔给 Agent。
而是：识别到有业务意义的变化 → 组装一个结构化的事件上下文包 → 交给 Agent。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class StateSnapshot:
    """单个传感器的状态快照，带新鲜度标记。"""
    value: Any
    unit: str = ""
    observed_at: str = ""       # 设备实际采集时间
    processed_at: str = ""      # 平台处理时间
    freshness_seconds: float = 0  # 数据新鲜度
    source: str = "sensor"       # 数据来源
    quality: str = "ok"          # 质量标记: ok / stale / estimated / unknown

    def to_dict(self) -> Dict[str, Any]:
        return {
            "value": self.value,
            "unit": self.unit,
            "observed_at": self.observed_at,
            "processed_at": self.processed_at,
            "freshness_seconds": round(self.freshness_seconds, 1),
            "source": self.source,
            "quality": self.quality,
        }


@dataclass
class ChangeRecord:
    """流处理算出的变化记录。"""
    description: str
    start_value: Any = None
    end_value: Any = None
    duration_seconds: float = 0
    trend: str = "stable"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "description": self.description,
            "start_value": self.start_value,
            "end_value": self.end_value,
            "duration_seconds": round(self.duration_seconds, 1),
            "trend": self.trend,
        }


@dataclass
class EvidenceItem:
    """每条证据带来源和时间。"""
    fact: str
    source: str
    observed_at: str

    def to_dict(self) -> Dict[str, Any]:
        return {
            "fact": self.fact,
            "source": self.source,
            "observed_at": self.observed_at,
        }


@dataclass
class AllowedAction:
    """带风险等级和审批要求的动作描述。"""
    name: str
    description: str = ""
    risk: str = "low"           # low / medium / high
    approval_required: bool = False
    parameters: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "description": self.description,
            "risk": self.risk,
            "approval_required": self.approval_required,
            "parameters": self.parameters,
        }


@dataclass
class EventContext:
    """事件上下文包 — Agent 的标准输入格式。"""
    case_id: str
    trigger: Dict[str, Any]                   # 由什么触发
    entity: Dict[str, Any]                    # 涉及哪个设备/业务对象
    state_snapshot: Dict[str, StateSnapshot]  # 当前状态快照（带新鲜度）
    recent_changes: List[ChangeRecord]        # 最近发生了哪些变化
    business_context: Dict[str, Any]          # 货品要求·维修记录·作业计划
    evidence: List[EvidenceItem]              # 证据清单（每条带来源）
    allowed_actions: List[AllowedAction]      # 允许申请的动作（带风险等级）
    missing_context: List[str]                # 标记缺失的信息

    def to_dict(self) -> Dict[str, Any]:
        return {
            "case_id": self.case_id,
            "trigger": self.trigger,
            "entity": self.entity,
            "state_snapshot": {k: v.to_dict() for k, v in self.state_snapshot.items()},
            "recent_changes": [c.to_dict() for c in self.recent_changes],
            "business_context": self.business_context,
            "evidence": [e.to_dict() for e in self.evidence],
            "allowed_actions": [a.to_dict() for a in self.allowed_actions],
            "missing_context": self.missing_context,
        }


class ContextAssembler:
    """
    上下文组装器。

    用法:
        assembler = ContextAssembler(store_id="store_001")
        ctx = assembler.assemble(
            trigger={"type": "temperature_above_range", "rule": "temperature > 8C for 10m"},
            device_id="fridge-2",
            window=temp_window,
            state_machine=fridge_sm,
        )
    """

    def __init__(self, store_id: str, device_id: str = ""):
        self.store_id = store_id
        self.device_id = device_id
        self._case_counter = 0

    def _next_case_id(self) -> str:
        self._case_counter += 1
        return f"case-{self.store_id}-{int(time.monotonic())}-{self._case_counter:04d}"

    def build_state_snapshot(
        self,
        readings: List[Dict[str, Any]],
        *,
        max_freshness_sec: float = 300,
    ) -> Dict[str, StateSnapshot]:
        """从读数列表构建状态快照，标记新鲜度。"""
        now = time.monotonic()
        snapshot: Dict[str, StateSnapshot] = {}
        for r in readings:
            sid = r.get("sensor_id", "unknown")
            recorded_at = r.get("recorded_at", utc_now_iso())
            # 计算新鲜度
            observed_ts = r.get("observed_ts")
            if observed_ts:
                age = max(0, now - observed_ts)
            else:
                age = 0
            quality = "ok" if age < max_freshness_sec else "stale"
            snapshot[sid] = StateSnapshot(
                value=r.get("value"),
                unit=r.get("unit", ""),
                observed_at=recorded_at,
                processed_at=utc_now_iso(),
                freshness_seconds=age,
                source=r.get("source", "sensor"),
                quality=quality,
            )
        return snapshot

    def assemble(
        self,
        trigger: Dict[str, Any],
        entity: Dict[str, Any],
        state_snapshot: Dict[str, StateSnapshot],
        recent_changes: Optional[List[ChangeRecord]] = None,
        business_context: Optional[Dict[str, Any]] = None,
        evidence: Optional[List[EvidenceItem]] = None,
        allowed_actions: Optional[List[AllowedAction]] = None,
        missing_context: Optional[List[str]] = None,
    ) -> EventContext:
        """组装完整的事件上下文包。"""
        return EventContext(
            case_id=self._next_case_id(),
            trigger=trigger,
            entity=entity or {"id": self.device_id, "store_id": self.store_id},
            state_snapshot=state_snapshot,
            recent_changes=recent_changes or [],
            business_context=business_context or {},
            evidence=evidence or [],
            allowed_actions=allowed_actions or self._default_actions(),
            missing_context=missing_context or [],
        )

    @staticmethod
    def _default_actions() -> List[AllowedAction]:
        return [
            AllowedAction("request_manual_inspection", "请求人工巡检", "low", False),
            AllowedAction("acknowledge_alert", "确认告警", "low", False),
            AllowedAction("create_work_order", "创建维修工单", "medium", True),
            AllowedAction("set_target_temperature", "调整目标温度", "medium", True),
        ]


def build_cold_chain_context(
    assembler: ContextAssembler,
    device_id: str,
    readings: List[Dict[str, Any]],
    window: Any,  # SensorWindow
    state_machine: Any,  # DeviceStateMachine
    thresholds: Dict[str, Any],
    business: Optional[Dict[str, Any]] = None,
) -> EventContext:
    """
    快捷方法: 为冷柜持续升温场景组装上下文。
    这是文章推荐的"先做一个高频、边界清楚的异常"最小落地路径。
    """
    # 1. 触发条件
    trigger = {
        "type": "temperature_above_range",
        "event_time": utc_now_iso(),
        "rule": f"temperature > {thresholds.get('warn_high', 8)}C for {thresholds.get('consecutive_min', 3)} consecutive readings",
    }

    # 2. 实体
    entity = {
        "id": device_id,
        "type": "cold_storage_unit",
        "store_id": assembler.store_id,
    }

    # 3. 状态快照
    snapshot = assembler.build_state_snapshot(readings)

    # 4. 变化记录
    changes = []
    if window and window.count >= 3:
        changes.append(ChangeRecord(
            description=f"温度从 {window.min_val}°C 升至 {window.max_val}°C ({window.count} 个读数)",
            start_value=window.min_val,
            end_value=window.max_val,
            duration_seconds=window.window_sec,
            trend=window.trend(),
        ))

    # 5. 证据
    evidence = []
    for r in readings:
        evidence.append(EvidenceItem(
            fact=f"{r.get('sensor_id')}: {r.get('value')}{r.get('unit', '')}",
            source=r.get('sensor_id', 'unknown'),
            observed_at=r.get('recorded_at', utc_now_iso()),
        ))

    # 6. 缺失上下文标记
    missing = []
    if not business:
        missing.append("cargo_requirements")
        missing.append("last_maintenance_record")
    if not any(r.get("sensor_id") == "door" for r in readings):
        missing.append("door_status")

    return assembler.assemble(
        trigger=trigger,
        entity=entity,
        state_snapshot=snapshot,
        recent_changes=changes,
        business_context=business or {},
        evidence=evidence,
        missing_context=missing,
    )
