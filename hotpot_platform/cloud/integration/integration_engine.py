"""
火瞳 · D3 集成引擎 — D1↔D2 事件驱动集成框架
================================================

架构: 同进程直接调用 + EventBus事件总线（混合模式）

5个核心集成点:
  IP-1: D1 ProductMaster → D2 Purchase Suggestions (采购建议)
  IP-2: D1 QualityCheckResult → D2 Kitchen Tasks (质检→后厨任务)
  IP-3: D1 PurchaseOrder → D2 PO Tracking (订单状态同步)
  IP-4: D1 SupplierScore → D2 Supplier Portal (评分同步)
  IP-5: D2 Suggestion Accept → D1 PO Creation (建议→自动建单)

使用方式:
  from integration_engine import IntegrationEngine
  engine = IntegrationEngine()
  engine.initialize()  # 注册所有事件处理器

  # D1数据变更时发布事件
  engine.publish("d1:receiving:approved", {"record_id": "RR-xxx", "quality_grade": "D"})

  # 或使用便捷方法
  engine.on_receiving_approved(record)
  engine.on_suggestion_accepted(suggestion_id)
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime
from typing import List, Dict, Any, Optional, Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


# =====================================================================
# 事件定义
# =====================================================================

class IntegrationEvent(str, Enum):
    """D3集成事件类型枚举"""

    # D1 → D2 数据推送事件
    D1_PRODUCT_UPDATED = "d1:product:updated"           # 产品数据变更
    D1_RECEIVING_SUBMITTED = "d1:receiving:submitted"    # 收货记录提交
    D1_RECEIVING_INSPECTED = "d1:receiving:inspected"    # 质检完成
    D1_RECEIVING_APPROVED = "d1:receiving:approved"      # 收货审批通过
    D1_PO_CREATED = "d1:po:created"                      # 采购订单创建
    D1_PO_STATUS_CHANGED = "d1:po:status_changed"        # 订单状态变更
    D1_SUPPLIER_SCORE_UPDATED = "d1:supplier:score_updated"  # 供应商评分更新
    D1_SUPPLIER_STATUS_CHANGED = "d1:supplier:status_changed"  # 供应商状态变更

    # D2 → D1 动作触发事件
    D2_SUGGESTION_ACCEPTED = "d2:suggestion:accepted"    # 建议被采纳
    D2_SUGGESTION_REJECTED = "d2:suggestion:rejected"     # 建议被拒绝
    D2_TASK_COMPLETED = "d2:task:completed"              # 待办已完成


@dataclass
class Event:
    """集成事件对象"""
    event_type: IntegrationEvent
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    source: str = "integration_engine"
    event_id: str = field(default="")

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"EVT-{datetime.now().strftime('%Y%m%d%H%M%S')}-{id(self):08x}"


# =====================================================================
# EventBus 事件总线
# =====================================================================

class EventBus:
    """
    轻量级事件总线 — 支持同步/异步订阅和发布

    特性:
    - 同步发布（适合同进程场景）
    - 优先级支持（数字越小优先级越高）
    - 异常隔离（单个handler异常不影响其他handler）
    """

    def __init__(self):
        self._handlers: Dict[str, List[Dict]] = {}
        self._lock = threading.Lock()
        self._event_history: List[Event] = []  # 最近100个事件（用于调试）
        self._max_history = 100

    def subscribe(
        self,
        event_type: str,
        handler: Callable,
        priority: int = 50,
        name: Optional[str] = None,
    ) -> None:
        """订阅事件

        Args:
            event_type: 事件类型字符串或IntegrationEvent枚举
            handler: 处理函数签名 (event: Event) -> None
            priority: 优先级 (0-100, 默认50, 数字越小越先执行)
            name: 处理器名称（用于日志和调试）
        """
        event_key = event_type.value if isinstance(event_type, IntegrationEvent) else event_type

        with self._lock:
            if event_key not in self._handlers:
                self._handlers[event_key] = []

            handler_record = {
                "handler": handler,
                "priority": priority,
                "name": name or handler.__name__,
            }
            self._handlers[event_key].append(handler_record)

            # 按优先级排序
            self._handlers[event_key].sort(key=lambda x: x["priority"])

        logger.debug(f"[EventBus] 已订阅: {event_key} -> {name or handler.__name__} (优先级={priority})")

    def unsubscribe(self, event_type: str, handler: Callable) -> bool:
        """取消订阅"""
        event_key = event_type.value if isinstance(event_type, IntegrationEvent) else event_type

        with self._lock:
            if event_key in self._handlers:
                original_len = len(self._handlers[event_key])
                self._handlers[event_key] = [
                    h for h in self._handlers[event_key]
                    if h["handler"] is not handler
                ]
                return len(self._handlers[event_key]) < original_len
        return False

    def publish(self, event: Event) -> int:
        """发布事件（同步执行所有订阅者）

        Returns:
            成功调用的handler数量
        """
        event_key = event.event_type.value if isinstance(event.event_type, IntegrationEvent) else str(event.event_type)

        # 记录事件历史
        with self._lock:
            self._event_history.append(event)
            if len(self._event_history) > self._max_history:
                self._event_history.pop(0)

        handlers = []
        with self._lock:
            handlers = self._handlers.get(event_key, []).copy()

        if not handlers:
            logger.debug(f"[EventBus] 事件无订阅者: {event_key}")
            return 0

        success_count = 0
        for record in handlers:
            try:
                logger.info(f"[EventBus] 执行处理器: {record['name']} <- {event_key}")
                record["handler"](event)
                success_count += 1
            except Exception as e:
                logger.error(f"[EventBus] 处理器异常: {record['name']} <- {event_key}: {e}", exc_info=True)

        return success_count

    def get_event_history(self, event_type: Optional[str] = None) -> List[Event]:
        """获取事件历史（用于调试）"""
        if event_type:
            key = event_type.value if isinstance(event_type, IntegrationEvent) else event_type
            return [e for e in self._event_history if e.event_type.value == key]
        return list(self._event_history)

    def get_subscribers(self, event_type: str) -> List[str]:
        """获取事件的订阅者列表"""
        key = event_type.value if isinstance(event_type, IntegrationEvent) else event_type
        with self._lock:
            return [h["name"] for h in self._handlers.get(key, [])]


# =====================================================================
# 集成引擎主类
# =====================================================================

class IntegrationEngine:
    """
    D3 集成引擎 — 统一管理D1↔D2的所有集成逻辑

    设计原则:
    1. 单例模式（全局唯一实例）
    2. 事件驱动解耦（通过EventBus）
    3. 显式集成点（每个IP有独立处理器）
    4. 可观测性（完整的事件日志和指标）
    """

    _instance: Optional[IntegrationEngine] = None
    _initialized: bool = False

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, '_event_bus') and self._event_bus:
            return  # 避免重复初始化

        self._event_bus = EventBus()
        self._manager = None  # 延迟绑定 SupplyChainManager
        self._metrics = {
            "events_published": 0,
            "events_processed": 0,
            "errors": 0,
            "ip1_calls": 0,  # IP-1 调用次数
            "ip2_calls": 0,
            "ip3_calls": 0,
            "ip4_calls": 0,
            "ip5_calls": 0,
        }

    @classmethod
    def get_instance(cls) -> IntegrationEngine:
        """获取单例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialize(self, manager=None) -> None:
        """初始化集成引擎，注册所有事件处理器

        Args:
            manager: SupplyChainManager 实例（可选，延迟绑定）
        """
        if self._initialized:
            logger.warning("[IntegrationEngine] 重复初始化，跳过")
            return

        self._manager = manager

        # 注册5个集成点的处理器
        self._register_ip1_handlers()   # 产品→采购建议
        self._register_ip2_handlers()   # 质检→后厨任务
        self._register_ip3_handlers()   # 订单→跟踪
        self._register_ip4_handlers()   # 评分→门户
        self._register_ip5_handlers()   # 建议→PO创建

        self._initialized = True
        logger.info("[IntegrationEngine] ✅ 初始化完成，已注册5个集成点处理器")

    def set_manager(self, manager) -> None:
        """延迟绑定SupplyChainManager"""
        self._manager = manager

    # =================================================================
    # 事件发布便捷方法
    # =================================================================

    def publish_event(self, event_type: IntegrationEvent, payload: Dict[str, Any]) -> int:
        """发布事件"""
        event = Event(event_type=event_type, payload=payload)
        self._metrics["events_published"] += 1
        processed = self._event_bus.publish(event)
        self._metrics["events_processed"] += processed
        return processed

    # --- IP-1: 产品数据变更 ---

    def on_product_updated(self, sku: str, product_data: Dict = None) -> int:
        """产品数据变更时调用"""
        return self.publish_event(IntegrationEvent.D1_PRODUCT_UPDATED, {
            "sku": sku,
            "product_data": product_data or {},
        })

    # --- IP-2: 收货质检完成 ---

    def on_receiving_inspected(self, record_id: str, quality_grades: List[Dict] = None) -> int:
        """收货质检完成时调用"""
        return self.publish_event(IntegrationEvent.D1_RECEIVING_INSPECTED, {
            "record_id": record_id,
            "quality_grades": quality_grades or [],
        })

    def on_receiving_approved(self, record_id: str, has_d_grade: bool = False) -> int:
        """收货审批通过时调用（含D级检测）"""
        return self.publish_event(IntegrationEvent.D1_RECEIVING_APPROVED, {
            "record_id": record_id,
            "has_d_grade": has_d_grade,
        })

    # --- IP-3: 采购订单变更 ---

    def on_po_created(self, po_id: str, order_no: str, supplier_name: str) -> int:
        """采购订单创建时调用"""
        return self.publish_event(IntegrationEvent.D1_PO_CREATED, {
            "po_id": po_id,
            "order_no": order_no,
            "supplier_name": supplier_name,
        })

    def on_po_status_changed(self, po_id: str, old_status: str, new_status: str) -> int:
        """订单状态变更时调用"""
        return self.publish_event(IntegrationEvent.D1_PO_STATUS_CHANGED, {
            "po_id": po_id,
            "old_status": old_status,
            "new_status": new_status,
        })

    # --- IP-4: 供应商评分/状态变更 ---

    def on_supplier_score_updated(self, supplier_id: str, score_data: Dict) -> int:
        """供应商评分更新时调用"""
        return self.publish_event(IntegrationEvent.D1_SUPPLIER_SCORE_UPDATED, {
            "supplier_id": supplier_id,
            "score_data": score_data,
        })

    def on_supplier_status_changed(self, supplier_id: str, old_status: str, new_status: str) -> int:
        """供应商状态变更时调用"""
        return self.publish_event(IntegrationEvent.D1_SUPPLIER_STATUS_CHANGED, {
            "supplier_id": supplier_id,
            "old_status": old_status,
            "new_status": new_status,
        })

    # --- IP-5: D2建议接受 ---

    def on_suggestion_accepted(self, suggestion_id: str) -> int:
        """AI建议被采纳时调用（核心集成点）"""
        return self.publish_event(IntegrationEvent.D2_SUGGESTION_ACCEPTED, {
            "suggestion_id": suggestion_id,
        })

    # =================================================================
    # 集成点处理器注册
    # =================================================================

    def _register_ip1_handlers(self):
        """IP-1: D1产品数据 → D2采购建议增强"""

        def handle_product_updated(event: Event):
            """产品数据变更时重新评估采购建议"""
            self._metrics["ip1_calls"] += 1
            sku = event.payload.get("sku")

            logger.info(f"[IP-1] 产品数据变更触发采购建议重评估: SKU={sku}")

            # TODO: 在后续步骤中实现智能采购建议生成逻辑
            # 这里先记录日志，实际逻辑在TC-001中完善
            pass

        self._event_bus.subscribe(
            IntegrationEvent.D1_PRODUCT_UPDATED,
            handle_product_updated,
            priority=10,
            name="ip1_product_to_suggestion",
        )

    def _register_ip2_handlers(self):
        """IP-2: D1质检结果 → D2后厨任务推送"""

        def handle_receiving_approved(event: Event):
            """收货审批通过后检查是否有D级品项，推送后厨处理任务"""
            self._metrics["ip2_calls"] += 1
            record_id = event.payload.get("record_id")
            has_d_grade = event.payload.get("has_d_grade", False)

            logger.info(f"[IP-2] 收货审批完成，D级检测: {record_id}, has_d={has_d_grade}")

            if has_d_grade and self._manager:
                # 自动生成后厨处理任务
                task = self._manager.create_kitchen_task_for_d_grade(record_id)
                if task:
                    logger.info(f"[IP-2] ✅ 已生成后厨任务: {task.get('id')}")

        self._event_bus.subscribe(
            IntegrationEvent.D1_RECEIVING_APPROVED,
            handle_receiving_approved,
            priority=10,
            name="ip2_quality_to_task",
        )

    def _register_ip3_handlers(self):
        """IP-3: D1采购订单 → D2订单跟踪同步"""

        def handle_po_status_changed(event: Event):
            """订单状态变更时同步到采购助理面板"""
            self._metrics["ip3_calls"] += 1
            po_id = event.payload.get("po_id")
            new_status = event.payload.get("new_status")

            logger.info(f"[IP-3] 订单状态变更同步: PO={po_id}, status={new_status}")

            # 状态变更时自动刷新相关待办
            if new_status == "submitted" and self._manager:
                self._manager.generate_po_confirmation_task(po_id)

        self._event_bus.subscribe(
            IntegrationEvent.D1_PO_STATUS_CHANGED,
            handle_po_status_changed,
            priority=10,
            name="ip3_po_tracking",
        )

    def _register_ip4_handlers(self):
        """IP-4: D1供应商评分 → D2供应商门户"""

        def handle_score_updated(event: Event):
            """供应商评分更新时同步到门户"""
            self._metrics["ip4_calls"] += 1
            supplier_id = event.payload.get("supplier_id")
            score_data = event.payload.get("score_data", {})
            overall = score_data.get("overall", 0)
            grade = score_data.get("grade", "C")

            logger.info(f"[IP-4] 供应商评分更新: SUP={supplier_id}, score={overall}, grade={grade}")

            # 低分预警：自动生成待办
            if overall < 70 and self._manager:
                self._manager.generate_supplier_alert_task(supplier_id, overall, grade)

        self._event_bus.subscribe(
            IntegrationEvent.D1_SUPPLIER_SCORE_UPDATED,
            handle_score_updated,
            priority=10,
            name="ip4_score_to_portal",
        )

    def _register_ip5_handlers(self):
        """IP-5: D2建议接受 → 生成待审批采购任务（符合最终方案要求）

        ⚠️ 重要设计决策（2026-08-02修正）:
        根据《火瞳餐饮AI智能体运营系统_最终方案》第六章明确规定:
        - "AI 不自动创建正式采购订单"
        - 采购Agent行动边界: "可生成建议和待办；**正式下单必须审批**"

        因此IP-5的正确流程是:
        用户采纳建议 → 生成待审批任务(Task) → 推送给采购负责人 → 人工审批 → 才创建正式PO
        """

        def handle_suggestion_accepted(event: Event):
            """AI采购建议被采纳后生成待审批采购任务（需人工确认后才创建PO）"""
            self._metrics["ip5_calls"] += 1
            suggestion_id = event.payload.get("suggestion_id")

            logger.info(f"[IP-5] 🎯 建议被采纳，生成待审批采购任务: SUG={suggestion_id}")

            if not self._manager:
                logger.error("[IP-5] ❌ Manager未绑定，无法创建任务")
                return

            # 获取建议详情
            suggestion = self._manager.get_suggestion_detail(suggestion_id)
            if not suggestion:
                logger.error(f"[IP-5] ❌ 建议不存在: {suggestion_id}")
                return

            # 只处理采购类型的建议
            if suggestion.get("suggestion_type") != "purchase_order":
                logger.info(f"[IP-5] 跳过非采购建议: type={suggestion.get('suggestion_type')}")
                return

            # 提取参数
            action_params = suggestion.get("action_params", {})
            sku = action_params.get("sku")
            qty = action_params.get("qty", 10)
            supplier_id = action_params.get("supplier_id")

            if not sku:
                logger.error("[IP-5] ❌ 缺少SKU参数")
                return

            try:
                # ✅ 修正后：不再直接创建PO，而是生成待审批任务
                task = self._manager.create_purchase_approval_task(
                    suggestion_id=suggestion_id,
                    sku=sku,
                    qty=qty,
                    supplier_id=supplier_id,
                    target_role="purchaser",  # 推送给采购负责人
                    priority="high",
                    title=f"审批采购: {sku} x{qty}",
                    description=f"AI建议采购{sku}，数量{qty}，请审批后创建正式采购订单。来源建议ID: {suggestion_id}",
                )

                if task:
                    logger.info(f"[IP-5] ✅ 已生成待审批采购任务: {task['id']} (需人工审批后才创建PO)")

                    # 发布任务创建事件（通知相关角色）
                    self.publish_event(IntegrationEvent.D2_TASK_CREATED, {
                        "task_id": task["id"],
                        "task_type": "purchase_approval",
                        "target_role": task.get("target_role"),
                        "suggestion_id": suggestion_id,
                        "requires_approval": True,  # 标记需要审批
                    })
                else:
                    logger.error("[IP-5] ❌ 创建待审批任务失败")
                    self._metrics["errors"] += 1

            except Exception as e:
                logger.error(f"[IP-5] ❌ 处理建议接受事件失败: {e}", exc_info=True)
                self._metrics["errors"] += 1

        self._event_bus.subscribe(
            IntegrationEvent.D2_SUGGESTION_ACCEPTED,
            handle_suggestion_accepted,
            priority=5,  # 最高优先级
            name="ip5_suggestion_to_po",
        )

    # =================================================================
    # 查询与调试接口
    # =================================================================

    def get_metrics(self) -> Dict[str, Any]:
        """获取集成引擎运行指标"""
        return {
            **self._metrics,
            "initialized": self._initialized,
            "subscribers": {
                event_type: self._event_bus.get_subscribers(event_type)
                for event_type in [e.value for e in IntegrationEvent]
                if self._event_bus.get_subscribers(event_type)
            },
            "recent_events": len(self._event_bus.get_event_history()),
        }

    def get_event_log(self, event_type: Optional[IntegrationEvent] = None) -> List[Dict]:
        """获取事件日志"""
        events = self._event_bus.get_event_history(event_type)
        return [
            {
                "event_id": e.event_id,
                "type": e.event_type.value,
                "payload": e.payload,
                "timestamp": e.timestamp,
            }
            for e in events[-20:]  # 最近20条
        ]

    def reset_metrics(self) -> None:
        """重置指标（测试用）"""
        for key in self._metrics:
            if isinstance(self._metrics[key], int):
                self._metrics[key] = 0


# =====================================================================
# 全局单例访问
# =====================================================================

_integration_engine: Optional[IntegrationEngine] = None


def get_integration_engine() -> IntegrationEngine:
    """获取全局集成引擎单例"""
    global _integration_engine
    if _integration_engine is None:
        _integration_engine = IntegrationEngine()
    return _integration_engine
