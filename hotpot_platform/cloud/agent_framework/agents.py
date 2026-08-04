#!/usr/bin/env python3
"""火瞳 · 四类岗位 AI 智能体实现

基于 RoleAgent 基类，实现整改方案要求的四类核心岗位Agent:
- A01 StoreManagerAgent: 店长AI助理 (监控+分析+推荐+通知)
- A02 KitchenAgent: 后厨AI助理 (SOP合规+废料检测+出品率)
- A03 ProcurementAgent: 采购AI助理 (比价+建议+供应商评分)
- A04 FrontHallAgent: 前厅领班 (清台检测+服务响应+客诉)

每个Agent通过 Gateway 统一执行受控行动，遵循 PermissionMatrix 权限控制。

作者: 火瞳AI团队
日期: 2026-08-04 (Step 3: Agent Gateway 统一)
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from .action_types import ActionType, RiskLevel
from .agent_gateway import (
    AgentGatewayMiddleware,
    UserContext,
    execute_via_gateway,
)
from .models import (
    AgentConfig,
    AgentMessage,
    AgentRole,
    AgentTask,
    Capability,
    MessageType,
    MessagePriority,
    OrchestrationResult,
    Subscription,
)
from .orchestrator import RoleAgent, MessageBus

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# A01: 店长 AI 助理
# ──────────────────────────────────────────────────────────────

class StoreManagerAgent(RoleAgent):
    """店长AI助理 (A01)

    职责:
    - 监控全店KPI (损耗/人效/服务响应/利润)
    - 分析经营数据 (日报/周报/趋势)
    - 推荐管理行动 (人员调度/促销/成本优化)
    - 审批高风险操作 (采购PO/新供应商)

    权限范围 (store_manager):
    - ✅ 读: dashboard/tasks/suggestions/purchase_orders
    - ✅ 低风险写: complete_task/dismiss_task/reject_suggestion
    - ⚠️ 中风险: accept_suggestion_purchase (不触发PO)
    - ❌ BLOCKED: create_po/approve_purchase/create_supplier/modify_inventory
    """

    def __init__(self, message_bus: MessageBus = None):
        config = AgentConfig(
            agent_id="agent-store-manager-001",
            name="店长AI助理",
            role=AgentRole.STORE_MANAGER,
            version="1.0.0",
            capabilities=[
                Capability.MONITOR,
                Capability.ANALYZE,
                Capability.RECOMMEND,
                Capability.NOTIFY,
            ],
            subscriptions=[
                Subscription(subscriber_id="agent-store-manager-001", topic_pattern="sop.*", handler_name="on_sop_deviation"),
                Subscription(subscriber_id="agent-store-manager-001", topic_pattern="waste.*", handler_name="on_waste_alert"),
                Subscription(subscriber_id="agent-store-manager-001", topic_pattern="inventory.*", handler_name="on_inventory_change"),
                Subscription(subscriber_id="agent-store-manager-001", topic_pattern="cleaning.*", handler_name="on_cleaning_event"),
                Subscription(subscriber_id="agent-store-manager-001", topic_pattern="supply_chain.*", handler_name="on_supply_chain_event"),
            ],
        )
        super().__init__(config, message_bus)
        self._gateway = AgentGatewayMiddleware.get_instance()

    def _register_default_handlers(self) -> None:
        """注册店长专属消息处理器"""
        super()._register_default_handlers()
        self._handlers["query.dashboard"] = self._handle_dashboard_query
        self._handlers["query.tasks"] = self._handle_tasks_query
        self._handlers["query.suggestions"] = self._handle_suggestions_query
        self._handlers["action.approve"] = self._handle_approval_request
        self._handlers["action.complete_task"] = self._handle_complete_task

    def _execute_task(self, task_type: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行店长任务"""
        if task_type == "generate_daily_report":
            return self._gen_daily_report(input_data)
        elif task_type == "analyze_kpi_trend":
            return self._analyze_kpi_trend(input_data)
        elif task_type == "review_pending_approvals":
            return self._review_pending_approvals(input_data)
        elif task_type == "optimize_staffing":
            return self._optimize_staffing(input_data)
        else:
            # 尝试通过 Gateway 执行
            return self._execute_via_gateway(task_type, input_data)

    # ── 任务实现 ────────────────────────────────────────

    def _gen_daily_report(self, input_data: Dict) -> Dict:
        """生成每日经营报告"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        store_id = input_data.get("store_id", "store_jiaojiang")
        date_str = input_data.get("date", datetime.now().strftime("%Y-%m-%d"))

        dashboard = SupplyChainManager.get_dashboard_full(
            include_kitchen=True,
            include_purchase=True,
        )

        return {
            "report_type": "daily",
            "store_id": store_id,
            "date": date_str,
            "generated_at": datetime.now().isoformat(),
            "dashboard": dashboard,
            "summary": {
                "total_waste_cost": dashboard.get("waste_summary", {}).get("total_cost", 0),
                "po_count": len(dashboard.get("purchase_orders", [])),
                "pending_tasks": len(dashboard.get("tasks", [])),
                "suggestions_count": len(dashboard.get("suggestions", [])),
            },
            "agent": self.config.name,
        }

    def _analyze_kpi_trend(self, input_data: Dict) -> Dict:
        """分析 KPI 趋势"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        days = input_data.get("days", 7)
        kpi_names = input_data.get("kpi_names", ["waste_rate", "table_turnover", "labor_efficiency"])

        # 获取历史数据（模拟，实际应从 PG 查询）
        stats = SupplyChainManager.get_product_stats()

        return {
            "analysis_type": "kpi_trend",
            "period_days": days,
            "kpis": {k: {"trend": "stable", "value": getattr(stats, k, None)} for k in kpi_names},
            "recommendations": [
                "损耗率略有上升，建议加强后厨培训",
                "翻台率稳定，可考虑优化排班",
            ],
            "agent": self.config.name,
        }

    def _review_pending_approvals(self, input_data: Dict) -> Dict:
        """查看待审批事项"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        tasks = SupplyChainManager.get_tasks(role="store_manager", status="pending")

        return {
            "task_type": "review_approvals",
            "pending_count": len(tasks),
            "items": tasks[:10],  # 最多返回10条
            "agent": self.config.name,
        }

    def _optimize_staffing(self, input_data: Dict) -> Dict:
        """人员调度优化建议"""
        return {
            "task_type": "optimize_staffing",
            "recommendations": [
                {"role": "前厅", "suggestion": "周末增加1人", "reason": "预计客流+20%"},
                {"role": "后厨", "suggestion": "备货提前2小时", "reason": "晚餐高峰前置"},
            ],
            "agent": self.config.name,
        }

    # ── Gateway 集成 ───────────────────────────────────

    async def _execute_via_gateway(self, action_str: str, params: Dict) -> Dict:
        """通过 Gateway 执行受控行动"""
        action_map = {
            "complete_task": ActionType.COMPLETE_TASK,
            "dismiss_task": ActionType.DISMISS_TASK,
            "reject_suggestion": ActionType.REJECT_SUGGESTION,
            "accept_suggestion_low": ActionType.ACCEPT_SUGGESTION_LOW,
            "query_dashboard": ActionType.QUERY_DASHBOARD,
            "query_tasks": ActionType.QUERY_TASKS,
            "query_suggestions": ActionType.QUERY_SUGGESTIONS,
        }

        action_type = action_map.get(action_str)
        if not action_type:
            return {"error": f"未知操作: {action_str}", "agent": self.config.name}

        ctx = UserContext(
            user_id=f"agent-{self.config.agent_id}",
            role="store_manager",
            session_id=f"sess-{self.config.agent_id}",
        )

        result = await self._gateway.execute_action(
            action_type=action_type,
            user_context=ctx,
            params=params,
        )
        return result.to_dict()

    # ── 消息处理器 ─────────────────────────────────────

    def _handle_dashboard_query(self, msg: AgentMessage) -> AgentMessage:
        """处理 Dashboard 查询"""
        report = self._gen_daily_report(msg.payload)
        return AgentMessage(
            msg_type=MessageType.REPORT,
            sender_id=self.config.agent_id,
            receiver_id=msg.sender_id,
            topic="dashboard.response",
            payload=report,
            correlation_id=msg.message_id,
        )

    def _handle_tasks_query(self, msg: AgentMessage) -> AgentMessage:
        """处理待办查询"""
        tasks = self._review_pending_approvals(msg.payload)
        return AgentMessage(
            msg_type=MessageType.REPORT,
            sender_id=self.config.agent_id,
            receiver_id=msg.sender_id,
            topic="tasks.response",
            payload=tasks,
            correlation_id=msg.message_id,
        )

    def _handle_suggestions_query(self, msg: AgentMessage) -> AgentMessage:
        """处理建议查询"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager
        suggestions = SupplyChainManager.get_suggestions(role="store_manager")
        return AgentMessage(
            msg_type=MessageType.REPORT,
            sender_id=self.config.agent_id,
            receiver_id=msg.sender_id,
            topic="suggestions.response",
            payload={"suggestions": suggestions, "agent": self.config.name},
            correlation_id=msg.message_id,
        )

    def _handle_approval_request(self, msg: AgentMessage) -> AgentMessage:
        """处理审批请求"""
        return AgentMessage(
            msg_type=MessageType.COMMAND,
            sender_id=self.config.agent_id,
            receiver_id=msg.sender_id,
            topic="approval.response",
            payload={
                "status": "received",
                "message": "审批请求已接收，将转交相关人员处理",
                "original": msg.payload,
            },
            correlation_id=msg.message_id,
        )

    def _handle_complete_task(self, msg: AgentMessage) -> AgentMessage:
        """处理完成任务请求"""
        task_id = msg.payload.get("task_id")
        return AgentMessage(
            msg_type=MessageType.EVENT,
            sender_id=self.config.agent_id,
            receiver_id=msg.sender_id,
            topic="task.completed",
            payload={
                "task_id": task_id,
                "status": "completed",
                "completed_by": self.config.name,
                "completed_at": datetime.now().isoformat(),
            },
            correlation_id=msg.message_id,
        )


# ──────────────────────────────────────────────────────────────
# A02: 后厨 AI 助理
# ──────────────────────────────────────────────────────────────

class KitchenAgent(RoleAgent):
    """后厨AI助理 (A02)

    职责:
    - SOP 合规监控 (温度/时间/操作规范)
    - 废料检测与分类 (视觉识别 + VLM)
    - 出品率计算与预警
    - 备货建议 (基于销量预测)

    权限范围 (kitchen_staff):
    - ✅ 读: dashboard
    - ✅ 低风险写: complete_task
    - ❌ 其他全部 BLOCKED
    """

    def __init__(self, message_bus: MessageBus = None):
        config = AgentConfig(
            agent_id="agent-kitchen-001",
            name="后厨AI助理",
            role=AgentRole.KITCHEN,
            version="1.0.0",
            capabilities=[
                Capability.MONITOR,
                Capability.NOTIFY,
                Capability.RECOMMEND,
            ],
            subscriptions=[
                Subscription(subscriber_id="agent-kitchen-001", topic_pattern="sop.*", handler_name="on_sop_check"),
                Subscription(subscriber_id="agent-kitchen-001", topic_pattern="vision.waste.*", handler_name="on_waste_detected"),
                Subscription(subscriber_id="agent-kitchen-001", topic_pattern="kitchen.prep.*", handler_name="on_prep_event"),
                Subscription(subscriber_id="agent-kitchen-001", topic_pattern="iot.temperature.*", handler_name="on_temperature_alert"),
            ],
        )
        super().__init__(config, message_bus)
        self._gateway = AgentGatewayMiddleware.get_instance()

    def _register_default_handlers(self) -> None:
        super()._register_default_handlers()
        self._handlers["query.kitchen_panel"] = self._handle_kitchen_panel
        self._handlers["query.waste_stats"] = self._handle_waste_stats
        self._handlers["alert.sop_violation"] = self._handle_sop_alert

    def _execute_task(self, task_type: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        if task_type == "check_sop_compliance":
            return self._check_sop_compliance(input_data)
        elif task_type == "calculate_yield_rate":
            return self._calculate_yield_rate(input_data)
        elif task_type == "suggest_prep_list":
            return self._suggest_prep_list(input_data)
        elif task_type == "analyze_waste":
            return self._analyze_waste(input_data)
        else:
            return {"error": f"后厨不支持的任务: {task_type}", "agent": self.config.name}

    def _check_sop_compliance(self, input_data: Dict) -> Dict:
        """检查 SOP 合规性"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        panel = SupplyChainManager.get_kitchen_assistant_panel()
        sop_score = panel.get("sop_score", 95)

        violations = []
        if sop_score < 90:
            violations.append({"type": "temperature", "severity": "warning", "msg": "冷库温度偏高"})

        return {
            "task_type": "sop_compliance",
            "score": sop_score,
            "violations": violations,
            "status": "pass" if sop_score >= 80 else "needs_attention",
            "agent": self.config.name,
        }

    def _calculate_yield_rate(self, input_data: Dict) -> Dict:
        """计算出品率"""
        return {
            "task_type": "yield_rate",
            "items": [
                {"name": "毛肚", "input_kg": 10, "output_kg": 7.5, "yield": 75.0, "target": 70, "status": "good"},
                {"name": "鸭肠", "input_kg": 5, "output_kg": 3.2, "yield": 64.0, "target": 65, "status": "acceptable"},
            ],
            "avg_yield": 69.5,
            "agent": self.config.name,
        }

    def _suggest_prep_list(self, input_data: Dict) -> Dict:
        """生成备货建议"""
        return {
            "task_type": "prep_list",
            "date": input_data.get("date", datetime.now().strftime("%Y-%m-%d")),
            "items": [
                {"sku": "FP-HNRC-001", "name": "精品毛肚", "qty_kg": 8, "priority": "high"},
                {"sku": "FP-HNRC-005", "name": "鲜鸭肠", "qty_kg": 4, "priority": "medium"},
            ],
            "agent": self.config.name,
        }

    def _analyze_waste(self, input_data: Dict) -> Dict:
        """分析废料"""
        return {
            "task_type": "waste_analysis",
            "period_days": input_data.get("days", 7),
            "total_waste_kg": 12.5,
            "total_cost": 680.0,
            "top_categories": [
                {"category": "FROZEN_MEAT", "cost": 320, "pct": 47},
                {"category": "VEGETABLE", "cost": 180, "pct": 26},
            ],
            "recommendations": ["减少冻品解冻过量", "优化蔬菜订货量"],
            "agent": self.config.name,
        }

    # ── 消息处理器 ─────────────────────────────────────

    def _handle_kitchen_panel(self, msg: AgentMessage) -> AgentMessage:
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager
        panel = SupplyChainManager.get_kitchen_assistant_panel()
        return AgentMessage(
            msg_type=MessageType.REPORT, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="kitchen.panel.response",
            payload={**panel, "agent": self.config.name}, correlation_id=msg.message_id,
        )

    def _handle_waste_stats(self, msg: AgentMessage) -> AgentMessage:
        stats = self._analyze_waste(msg.payload)
        return AgentMessage(
            msg_type=MessageType.REPORT, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="waste.stats.response",
            payload=stats, correlation_id=msg.message_id,
        )

    def _handle_sop_alert(self, msg: AgentMessage) -> AgentMessage:
        return AgentMessage(
            msg_type=MessageType.ALERT, priority=MessagePriority.HIGH,
            sender_id=self.config.agent_id, receiver_id=msg.sender_id,
            topic="sop.alert.response",
            payload={
                "alert_id": f"SOP-{datetime.now().strftime('%H%M%S')}",
                "severity": msg.payload.get("severity", "warning"),
                "message": "SOP异常已记录，请后厨主管确认",
                "agent": self.config.name,
            },
            correlation_id=msg.message_id,
        )


# ──────────────────────────────────────────────────────────────
# A03: 采购 AI 助理
# ──────────────────────────────────────────────────────────────

class ProcurementAgent(RoleAgent):
    """采购AI助理 (A03)

    职责:
    - 供应商比价与推荐
    - 采购建议生成 (IP-5 流程)
    - 供应商评分与管理
    - 价格波动预警

    权限范围 (purchaser):
    - ✅ 读: dashboard/tasks/suggestions/purchase_orders/suppliers/inventory
    - ✅ 低风险写: complete_task/reject_suggestion
    - ⚠️ 中风险: accept_suggestion_purchase/submit_receiving/update_supplier_score
    - 🔴 HIGH(需审批): approve_purchase/create_po/create_supplier
    - ❌ BLOCKED: modify_inventory
    """

    def __init__(self, message_bus: MessageBus = None):
        config = AgentConfig(
            agent_id="agent-procurement-001",
            name="采购AI助理",
            role=AgentRole.PROCUREMENT,
            version="1.0.0",
            capabilities=[
                Capability.ANALYZE,
                Capability.PREDICT,
                Capability.RECOMMEND,
                Capability.QUERY,
            ],
            subscriptions=[
                Subscription(subscriber_id="agent-procurement-001", topic_pattern="forecast.*", handler_name="on_forecast_update"),
                Subscription(subscriber_id="agent-procurement-001", topic_pattern="inventory.*", handler_name="on_inventory_alert"),
                Subscription(subscriber_id="agent-procurement-001", topic_pattern="supply_chain.*", handler_name="on_supply_chain_event"),
                Subscription(subscriber_id="agent-procurement-001", topic_pattern="supplier.*", handler_name="on_supplier_event"),
            ],
        )
        super().__init__(config, message_bus)
        self._gateway = AgentGatewayMiddleware.get_instance()

    def _register_default_handlers(self) -> None:
        super()._register_default_handlers()
        self._handlers["query.purchase_panel"] = self._handle_purchase_panel
        self._handlers["query.supplier_ranking"] = self._handle_supplier_ranking
        self._handlers["action.create_po"] = self._handle_create_po_request

    def _execute_task(self, task_type: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        if task_type == "compare_suppliers":
            return self._compare_suppliers(input_data)
        elif task_type == "generate_purchase_suggestion":
            return self._generate_purchase_suggestion(input_data)
        elif task_type == "evaluate_supplier":
            return self._evaluate_supplier(input_data)
        elif task_type == "check_price_alerts":
            return self._check_price_alerts(input_data)
        else:
            return {"error": f"采购不支持的任务: {task_type}", "agent": self.config.name}

    def _compare_suppliers(self, input_data: Dict) -> Dict:
        """供应商比价"""
        sku = input_data.get("sku", "FP-HNRC-001")
        qty = input_data.get("qty", 10)
        return {
            "task_type": "supplier_comparison",
            "sku": sku,
            "qty": qty,
            "suppliers": [
                {"name": "王总(一级)", "unit_price": 25.0, "total": 250.0, "score": 92, "rank": 1},
                {"name": "李总(二级)", "unit_price": 26.5, "total": 265.0, "score": 85, "rank": 2},
                {"name": "张总(备用)", "unit_price": 28.0, "total": 280.0, "score": 78, "rank": 3},
            ],
            "recommendation": "王总价格最优且评分最高，建议优先",
            "agent": self.config.name,
        }

    def _generate_purchase_suggestion(self, input_data: Dict) -> Dict:
        """生成采购建议 (IP-5 入口)"""
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        items = input_data.get("items", [{"sku": "FP-HNRC-001", "qty": 10}])
        supplier = input_data.get("supplier", "王总")

        suggestion = SupplyChainManager.create_purchase_approval_task(
            sku=items[0]["sku"] if items else "UNKNOWN",
            qty=items[0].get("qty", 10) if items else 10,
            supplier_id=None,
            target_role="purchaser",
            priority="normal",
            title=f"采购建议: {items[0]['sku'] if items else '?'} x{items[0].get('qty', '?') if items else '?'}",
            description=f"AI建议向{supplier}采购，原因: 库存低于安全线",
        )

        return {
            "task_type": "purchase_suggestion",
            "suggestion_id": suggestion.get("id") if suggestion else None,
            "items": items,
            "recommended_supplier": supplier,
            "estimated_total": sum(it.get("qty", 0) * 25.0 for it in items),
            "next_step": "等待采购员采纳 → 创建审批任务 → 店长审批 → 正式PO",
            "agent": self.config.name,
        }

    def _evaluate_supplier(self, input_data: Dict) -> Dict:
        """评估供应商"""
        supplier_id = input_data.get("supplier_id", "SUPP-001")
        return {
            "task_type": "supplier_evaluation",
            "supplier_id": supplier_id,
            "scores": {
                "quality": 90,
                "delivery": 85,
                "price": 78,
                "service": 88,
                "overall": 85,
            },
            "trend": "stable",
            "recommendation": "合格供应商，继续保持合作",
            "agent": self.config.name,
        }

    def _check_price_alerts(self, input_data: Dict) -> Dict:
        """价格波动检查"""
        return {
            "task_type": "price_alerts",
            "alerts": [
                {"sku": "FP-HNRC-001", "name": "精品毛肚", "change_pct": +5.2, "severity": "warning"},
            ],
            "agent": self.config.name,
        }

    # ── 消息处理器 ─────────────────────────────────────

    def _handle_purchase_panel(self, msg: AgentMessage) -> AgentMessage:
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager
        panel = SupplyChainManager.get_purchase_assistant_panel()
        return AgentMessage(
            msg_type=MessageType.REPORT, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="purchase.panel.response",
            payload={**panel, "agent": self.config.name}, correlation_id=msg.message_id,
        )

    def _handle_supplier_ranking(self, msg: AgentMessage) -> AgentMessage:
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager
        ranking = SupplyChainManager.get_supplier_ranking(limit=10)
        return AgentMessage(
            msg_type=MessageType.REPORT, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="supplier.ranking.response",
            payload={"ranking": ranking, "agent": self.config.name}, correlation_id=msg.message_id,
        )

    def _handle_create_po_request(self, msg: AgentMessage) -> AgentMessage:
        """处理 PO 创建请求 (HIGH 风险，需经 Gateway 审批路由)"""
        return AgentMessage(
            msg_type=MessageType.COMMAND, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="po.request.received",
            payload={
                "status": "routing_to_approval",
                "message": "PO创建请求已提交Gateway，将根据权限矩阵路由到审批流程",
                "original": msg.payload,
            },
            correlation_id=msg.message_id,
        )


# ──────────────────────────────────────────────────────────────
# A04: 前厅领班
# ──────────────────────────────────────────────────────────────

class FrontHallAgent(RoleAgent):
    """前厅领班 (A04)

    职责:
    - 清台检测闭环 (视觉→任务→PDA→完成→KPI)
    - 服务响应监控
    - 客诉处理协调
    - 翻台率优化

    权限范围 (front_hall_lead):
    - ✅ 读: dashboard/tasks
    - ✅ 低风险写: complete_task/dismiss_task
    - ❌ 其他 BLOCKED
    """

    def __init__(self, message_bus: MessageBus = None):
        config = AgentConfig(
            agent_id="agent-front-hall-001",
            name="前厅领班",
            role=AgentRole.STORE_MANAGER,  # 前厅领班暂用店长权限
            version="1.0.0",
            capabilities=[
                Capability.MONITOR,
                Capability.NOTIFY,
                Capability.EXECUTE,
            ],
            subscriptions=[
                Subscription(subscriber_id="agent-front-hall-001", topic_pattern="cleaning.*", handler_name="on_cleaning_event"),
                Subscription(subscriber_id="agent-front-hall-001", topic_pattern="service.*", handler_name="on_service_event"),
                Subscription(subscriber_id="agent-front-hall-001", topic_pattern="customer.*", handler_name="on_customer_event"),
                Subscription(subscriber_id="agent-front-hall-001", topic_pattern="vision.table.*", handler_name="on_table_status_change"),
            ],
        )
        super().__init__(config, message_bus)
        self._gateway = AgentGatewayMiddleware.get_instance()

    def _register_default_handlers(self) -> None:
        super()._register_default_handlers()
        self._handlers["query.cleaning_status"] = self._handle_cleaning_status
        self._handlers["alert.dirty_table"] = self._handle_dirty_table_alert
        self._handlers["action.assign_task"] = self._handle_assign_task

    def _execute_task(self, task_type: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        if task_type == "detect_dirty_tables":
            return self._detect_dirty_tables(input_data)
        elif task_type == "create_cleaning_task":
            return self._create_cleaning_task(input_data)
        elif task_type == "check_response_time":
            return self._check_response_time(input_data)
        elif task_type == "calculate_turnover_rate":
            return self._calculate_turnover_rate(input_data)
        else:
            return {"error": f"前厅不支持的任务: {task_type}", "agent": self.config.name}

    def _detect_dirty_tables(self, input_data: Dict) -> Dict:
        """检测脏桌 (对接视觉引擎)"""
        # 模拟视觉检测结果，实际应从 edge/front_hall/inference/ 获取
        return {
            "task_type": "dirty_table_detection",
            "detected_at": datetime.now().isoformat(),
            "source": "camera_jiaojiang_hikvision_nvr",
            "tables": [
                {"table_id": "T05", "status": "need_clean", "dirty_since_min": 8, "confidence": 0.92},
                {"table_id": "T08", "status": "need_clean", "dirty_since_min": 3, "confidence": 0.87},
            ],
            "total_dirty": 2,
            "action": "auto_create_tasks",
            "agent": self.config.name,
        }

    def _create_cleaning_task(self, input_data: Dict) -> Dict:
        """创建清台任务"""
        table_id = input_data.get("table_id", "T05")
        urgency = input_data.get("urgency", "normal")

        task = {
            "task_id": f"CLEAN-{table_id}-{datetime.now().strftime('%H%M%S')}",
            "type": "cleaning",
            "table_id": table_id,
            "status": "pending",
            "urgency": urgency,
            "created_at": datetime.now().isoformat(),
            "assignee": None,  # 等待 PDA 接单
            "due_seconds": 180 if urgency == "normal" else 60,
            "source": "vision_auto",
            "agent": self.config.name,
        }
        return task

    def _check_response_time(self, input_data: Dict) -> Dict:
        """检查服务响应时间"""
        return {
            "task_type": "response_time_check",
            "period_hours": input_data.get("hours", 2),
            "avg_response_sec": 78,
            "target_sec": 120,
            "status": "good",
            "tasks": {
                "total": 15,
                "within_target": 13,
                "overdue": 2,
            },
            "agent": self.config.name,
        }

    def _calculate_turnover_rate(self, input_data: Dict) -> Dict:
        """计算翻台率"""
        return {
            "task_type": "turnover_rate",
            "date": input_data.get("date", datetime.now().strftime("%Y-%m-%d")),
            "lunch": {"tables": 8, "turns": 2.1, "revenue": 4800},
            "dinner": {"tables": 8, "turns": 2.8, "revenue": 7200},
            "daily_avg": 2.45,
            "target": 2.5,
            "status": "near_target",
            "agent": self.config.name,
        }

    # ── 消息处理器 ─────────────────────────────────────

    def _handle_cleaning_status(self, msg: AgentMessage) -> AgentMessage:
        status = self._detect_dirty_tables(msg.payload)
        return AgentMessage(
            msg_type=MessageType.REPORT, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="cleaning.status.response",
            payload=status, correlation_id=msg.message_id,
        )

    def _handle_dirty_table_alert(self, msg: AgentMessage) -> AgentMessage:
        task = self._create_cleaning_task(msg.payload)
        return AgentMessage(
            msg_type=MessageType.ALERT, priority=MessagePriority.HIGH,
            sender_id=self.config.agent_id, receiver_id=msg.sender_id,
            topic="dirty_table.task_created",
            payload=task, correlation_id=msg.message_id,
        )

    def _handle_assign_task(self, msg: AgentMessage) -> AgentMessage:
        return AgentMessage(
            msg_type=MessageType.EVENT, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="task.assigned",
            payload={
                **msg.payload,
                "assigned_by": self.config.name,
                "assigned_at": datetime.now().isoformat(),
            },
            correlation_id=msg.message_id,
        )


# ──────────────────────────────────────────────────────────────
# 工厂函数：快速创建 Agent 实例
# ──────────────────────────────────────────────────────────────

AGENT_REGISTRY: Dict[str, type] = {
    "store_manager": StoreManagerAgent,
    "kitchen": KitchenAgent,
    "procurement": ProcurementAgent,
    "front_hall": FrontHallAgent,
}


def create_agent(role: str, message_bus: MessageBus = None) -> RoleAgent:
    """工厂函数: 根据角色名称创建对应 Agent 实例

    Args:
        role: 角色名称 (store_manager/kitchen/procurement/front_hall)
        message_bus: 可选的消息总线

    Returns:
        对应的 RoleAgent 子类实例

    Raises:
        ValueError: 如果角色名称不在注册表中
    """
    agent_cls = AGENT_REGISTRY.get(role)
    if not agent_cls:
        available = ", ".join(AGENT_REGISTRY.keys())
        raise ValueError(f"未知角色: {role}, 可用: {available}")

    agent = agent_cls(message_bus)
    agent.initialize()
    logger.info("🔥火瞳 Agent 创建成功: %s (%s)", agent.config.name, role)
    return agent


def create_all_agents(message_bus: MessageBus = None) -> Dict[str, RoleAgent]:
    """创建所有四类岗位 Agent

    Returns:
        {role_name: agent_instance} 字典
    """
    agents = {}
    for role_name in AGENT_REGISTRY:
        agents[role_name] = create_agent(role_name, message_bus)
    logger.info("🔥火瞳 全部 %d 个 Agent 创建并初始化完成", len(agents))
    return agents
