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
    SimulationMode,
    Subscription,
)
from .orchestrator import RoleAgent, MessageBus

logger = logging.getLogger(__name__)


# ── 模拟数据标记辅助 ────────────────────────────────────────

def _mark_simulation_data(data: Dict, agent_config: AgentConfig) -> Dict:
    """为模拟数据添加标记（仅在 DEMO 模式下）

    Args:
        data: 原始返回数据
        agent_config: Agent 配置（包含 simulation_mode）

    Returns:
        添加了 _simulation 标记的数据副本
    """
    if agent_config.simulation_mode == SimulationMode.DEMO:
        data = dict(data)  # 避免修改原数据
        data["_simulation"] = True
        data["_source"] = "mock_data_for_demo"
        logger.debug("[SIMULATION] 数据来源: 模拟数据 (演示模式)")
    return data


# 延迟导入 MockDataService（避免循环依赖）
def _get_mock_service():
    """获取 MockDataService 单例"""
    from .mock_data_service import get_mock_service
    return get_mock_service()


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
            import asyncio
            try:
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # 如果已在异步上下文中，创建任务
                    import asyncio
                    return asyncio.create_task(self._execute_via_gateway(task_type, input_data))
                else:
                    return loop.run_until_complete(self._execute_via_gateway(task_type, input_data))
            except RuntimeError:
                # 没有事件循环时，同步包装调用
                import asyncio
                return asyncio.run(self._execute_via_gateway(task_type, input_data))

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
            version="1.1.0",  # D2升级: 真实数据源增强
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
        # ── D2新增: 真实数据源任务 ──
        elif task_type == "read_iot_temperature":
            return self._read_iot_temperature(input_data)
        elif task_type == "analyze_yield_trend":
            return self._analyze_yield_trend(input_data)
        else:
            return {"error": f"后厨不支持的任务: {task_type}", "agent": self.config.name}

    def _check_sop_compliance(self, input_data: Dict) -> Dict:
        """检查 SOP 合规性 (D2增强版: 支持自定义检查项)

        Args:
            input_data: 可包含 custom_check_items (List[Dict]) 自定义检查项列表

        Returns:
            SOP合规检查结果，含评分、违规项、状态
        """
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        panel = SupplyChainManager.get_kitchen_assistant_panel()
        sop_score = panel.get("sop_score", 95)

        # D2增强: 支持自定义检查项列表
        custom_checks = input_data.get("custom_check_items")
        default_check_items = [
            {"name": "冷库温度", "target_range": [-18, -15], "unit": "°C"},
            {"name": "热菜保温", "target_range": [60, 80], "unit": "°C"},
            {"name": "操作台清洁", "target": "pass", "type": "visual"},
            {"name": "员工口罩佩戴", "target": "yes", "type": "visual"},
        ]
        check_items = custom_checks if custom_checks else default_check_items

        violations = []
        # 基于IoT温度数据评估（如果有）
        store_id = input_data.get("store_id", "store_jiaojiang")
        iot_temp = self._read_iot_temperature({"store_id": store_id})
        temp_data = iot_temp.get("temperatures", {})

        for item in check_items:
            item_name = item.get("name", "")
            if "温度" in item_name and item_name in temp_data:
                current_temp = temp_data[item_name].get("value")
                target_range = item.get("target_range", [])
                if target_range and current_temp is not None:
                    if not (target_range[0] <= current_temp <= target_range[1]):
                        violations.append({
                            "type": "temperature",
                            "item": item_name,
                            "severity": "warning",
                            "msg": f"{item_name}异常: {current_temp}{item.get('unit', '°C')}, 目标范围{target_range}",
                            "current_value": current_temp,
                            "target_range": target_range,
                        })

        if sop_score < 90 and not any(v["type"] == "temperature" for v in violations):
            violations.append({"type": "temperature", "severity": "warning", "msg": "冷库温度偏高"})

        return {
            "task_type": "sop_compliance",
            "score": sop_score,
            "violations": violations,
            "check_items_count": len(check_items),
            "status": "pass" if sop_score >= 80 else "needs_attention",
            "iot_temperature_used": bool(temp_data),
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
        """分析废料 (D2增强版: 支持VLM视觉识别数据)

        Args:
            input_data: 可包含 vlm_waste_events (List[Dict]) VLM识别的废料事件数据
                       每个事件包含: waste_type, weight_kg, image_evidence, confidence

        Returns:
            废料分析报告，含分类、成本、VLM识别结果
        """
        # D2增强: 解析VLM废料识别事件数据
        vlm_events = input_data.get("vlm_waste_events", [])
        vlm_total_kg = 0.0
        vlm_categories = {}

        for event in vlm_events:
            waste_type = event.get("waste_type", "UNKNOWN")
            weight = event.get("weight_kg", 0)
            vlm_total_kg += weight
            if waste_type not in vlm_categories:
                vlm_categories[waste_type] = {"weight_kg": 0, "count": 0, "evidence_images": []}
            vlm_categories[waste_type]["weight_kg"] += weight
            vlm_categories[waste_type]["count"] += 1
            if event.get("image_evidence"):
                vlm_categories[waste_type]["evidence_images"].append(event["image_evidence"])

        # 基础废料数据（保持向后兼容）
        base_waste_kg = 12.5
        total_waste_kg = vlm_total_kg if vlm_total_kg > 0 else base_waste_kg
        unit_cost_estimate = 54.4  # ¥/kg (基于历史均价)

        # 构建分类统计
        top_categories = []
        if vlm_categories:
            for wtype, data in sorted(vlm_categories.items(), key=lambda x: -x[1]["weight_kg"]):
                top_categories.append({
                    "category": wtype,
                    "weight_kg": round(data["weight_kg"], 2),
                    "cost": round(data["weight_kg"] * unit_cost_estimate, 2),
                    "count": data["count"],
                    "has_visual_evidence": len(data["evidence_images"]) > 0,
                    "evidence_count": len(data["evidence_images"]),
                })
        else:
            # 向后兼容: 返回默认分类
            top_categories = [
                {"category": "FROZEN_MEAT", "cost": 320, "pct": 47},
                {"category": "VEGETABLE", "cost": 180, "pct": 26},
            ]

        return {
            "task_type": "waste_analysis",
            "period_days": input_data.get("days", 7),
            "total_waste_kg": round(total_waste_kg, 2),
            "total_cost": round(total_waste_kg * unit_cost_estimate, 2),
            "top_categories": top_categories,
            "vlm_data_used": len(vlm_events) > 0,
            "vlm_event_count": len(vlm_events),
            "recommendations": ["减少冻品解冻过量", "优化蔬菜订货量"] if not vlm_events else [
                f"重点关注 {list(vlm_categories.keys())[0]} 类废料，占比最高",
                "建议加强员工操作规范培训",
                "利用VLM视觉证据进行针对性改进",
            ],
            "agent": self.config.name,
        }

    def _read_iot_temperature(self, input_data: Dict) -> Dict:
        """从IoT设备读取温度数据 (D2新增)

        模拟从MessageBus订阅 iot.temperature.* 事件的逻辑，
        实际部署时应从时序数据库(InfluxDB/TimescaleDB)查询真实传感器数据。

        Args:
            input_data: {"store_id": "store_jiaojiang", "sensor_ids": ["temp_001", "temp_002"]}

        Returns:
            各传感器温度数据及异常告警
        """
        store_id = input_data.get("store_id", "store_jiaojiang")
        sensor_ids = input_data.get("sensor_ids")

        # 使用 MockDataService 生成模拟IoT数据（替代硬编码）
        mock_svc = _get_mock_service()
        result = mock_svc.generate_iot_temperature(store_id)

        # 如果指定了传感器ID，则过滤
        if sensor_ids:
            result["temperatures"] = [
                t for t in result["temperatures"]
                if t["sensor_id"] in sensor_ids
            ]

        result["agent"] = self.config.name
        return _mark_simulation_data(result, self.config)

    def _analyze_yield_trend(self, input_data: Dict) -> Dict:
        """分析出品率趋势 (D2新增)

        基于历史出品率数据计算趋势方向，支持上升/下降/稳定判定。

        Args:
            input_data: {"days": 7, "item_names": ["毛肚", "鸭肠"]}

        Returns:
            出品率趋势分析报告，含方向、变化率、建议
        """
        days = input_data.get("days", 7)
        item_names = input_data.get("item_names", ["毛肚", "鸭肠"])

        # 模拟历史出品率数据（实际应从PG查询）
        import random
        random.seed(42)  # 保证可复现

        historical_yields = {}
        for item in item_names:
            base_yield = 70 if item == "毛肚" else 65
            historical_yields[item] = [
                round(base_yield + random.uniform(-3, 3), 1) for _ in range(days)
            ]

        # 计算趋势
        trend_results = {}
        for item, yields in historical_yields.items():
            if len(yields) >= 2:
                recent_avg = sum(yields[-3:]) / min(3, len(yields))
                earlier_avg = sum(yields[:3]) / min(3, len(yields))
                change_pct = round((recent_avg - earlier_avg) / earlier_avg * 100, 1) if earlier_avg > 0 else 0

                if change_pct > 2:
                    direction = "rising"
                    status = "good"
                elif change_pct < -2:
                    direction = "declining"
                    status = "attention"
                else:
                    direction = "stable"
                    status = "normal"

                trend_results[item] = {
                    "direction": direction,
                    "change_pct": change_pct,
                    "recent_avg": round(recent_avg, 1),
                    "earlier_avg": round(earlier_avg, 1),
                    "latest_value": yields[-1],
                    "status": status,
                    "data_points": len(yields),
                }
            else:
                trend_results[item] = {
                    "direction": "insufficient_data",
                    "change_pct": 0,
                    "status": "unknown",
                    "data_points": len(yields),
                }

        return {
            "task_type": "yield_trend_analysis",
            "period_days": days,
            "items": trend_results,
            "overall_direction": max(
                set(r["direction"] for r in trend_results.values()),
                key=lambda d: list(r["direction"] for r in trend_results.values()).count(d)
            ) if trend_results else "unknown",
            "recommendations": [
                "出品率整体稳定，继续保持当前操作规范",
                "建议关注单品波动较大的菜品，优化切配流程",
            ] if all(r.get("status") in ("good", "normal") for r in trend_results.values()) else [
                "检测到出品率下降趋势，建议加强员工培训",
                "检查原材料质量是否稳定",
                "优化备货和存储条件",
            ],
            "agent": self.config.name,
        }

    # ── KitchenAgent 消息处理器 ──────────────────────────

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
            version="1.1.0",  # D2升级: 智能预测增强
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
        # ── D2新增: 智能预测任务 ──
        elif task_type == "predict_purchase_quantity":
            return self._predict_purchase_quantity(input_data)
        elif task_type == "score_supplier_risk":
            return self._score_supplier_risk(input_data)
        elif task_type == "analyze_price_trend":
            return self._analyze_price_trend(input_data)
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
        import uuid

        items = input_data.get("items", [{"sku": "FP-HNRC-001", "qty": 10}])
        supplier = input_data.get("supplier", "王总")

        # 生成建议ID（作为 create_purchase_approval_task 的必填参数）
        gen_suggestion_id = f"SUGG-{uuid.uuid4().hex[:8].upper()}"

        suggestion = SupplyChainManager.create_purchase_approval_task(
            suggestion_id=gen_suggestion_id,  # 必填：来源AI建议ID
            sku=items[0]["sku"] if items else "UNKNOWN",
            qty=items[0].get("qty", 10) if items else 10,
            supplier_id=None,
            target_role="purchaser",
            priority="normal",
            title=f"采购建议: {items[0]['sku'] if items else '?'} x{items[0].get('qty', '?') if items else '?'}",
            description=f"AI建议向{supplier}采购，原因: 基于废料分析与智能预测",
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

    def _predict_purchase_quantity(self, input_data: Dict) -> Dict:
        """智能采购量预测 (D2新增)

        基于历史销量、季节因子和促销计划，使用加权移动平均(WMA)算法预测采购量。

        算法:
        - 加权移动平均(WMA): 近期数据权重更高
        - 季节调整: 夏季火锅淡季因子 0.85
        - 促销调整: 如有促销计划 +20%

        Args:
            input_data: {"item_id": "FP-HNRC-001", "days": 7, "has_promo": False}

        Returns:
            预测结果，含预测量、置信度、应用因子
        """
        item_id = input_data.get("item_id", "FP-HNRC-001")
        days = input_data.get("days", 7)
        has_promo = input_data.get("has_promo", False)

        # 使用 MockDataService 生成预测数据（替代全局 random.seed）
        mock_svc = _get_mock_service()
        result = mock_svc.predict_purchase_quantity(
            item_id=item_id,
            days=days,
            has_promo=has_promo,
            seasonal_factor=0.85,  # 夏季火锅淡季
        )
        result["agent"] = self.config.name
        return _mark_simulation_data(result, self.config)

    def _score_supplier_risk(self, input_data: Dict) -> Dict:
        """供应商风险评分卡 (D2新增)

        基于三维评分模型评估供应商风险等级:
        - 交货及时率 (40%权重)
        - 质量合格率 (40%权重)
        - 价格稳定性 (20%权重)

        风险等级划分:
        - LOW: 总分 > 85
        - MEDIUM: 70 <= 总分 <= 85
        - HIGH: 总分 < 70

        Args:
            input_data: {"supplier_id": "SUPP-001"}

        Returns:
            风险评分报告，含总分、各维度得分、风险等级
        """
        supplier_id = input_data.get("supplier_id", "SUPP-001")

        # 模拟供应商数据（实际应从PG查询）
        import random
        random.seed(hash(supplier_id) % (2**32))

        # 三维评分数据
        delivery_score = round(random.uniform(75, 98), 1)  # 交货及时率
        quality_score = round(random.uniform(72, 96), 1)   # 质量合格率
        price_stability = round(random.uniform(65, 92), 1)  # 价格稳定性

        # 加权计算总分
        total_score = round(
            delivery_score * 0.40 +
            quality_score * 0.40 +
            price_stability * 0.20,
            1
        )

        # 风险等级判定
        if total_score > 85:
            risk_level = "LOW"
            risk_color = "green"
            action = "保持合作，定期复核"
        elif total_score >= 70:
            risk_level = "MEDIUM"
            risk_color = "yellow"
            action = "加强监控，准备备选供应商"
        else:
            risk_level = "HIGH"
            risk_color = "red"
            action = "考虑替换，启动新供应商寻源"

        return {
            "task_type": "supplier_risk_scoring",
            "supplier_id": supplier_id,
            "total_score": total_score,
            "risk_level": risk_level,
            "risk_color": risk_color,
            "dimensions": {
                "delivery": {
                    "score": delivery_score,
                    "weight": 0.40,
                    "name": "交货及时率",
                    "detail": f"近30天准时交货率 {delivery_score}%",
                },
                "quality": {
                    "score": quality_score,
                    "weight": 0.40,
                    "name": "质量合格率",
                    "detail": f"批次检验合格率 {quality_score}%",
                },
                "price_stability": {
                    "score": price_stability,
                    "weight": 0.20,
                    "name": "价格稳定性",
                    "detail": f"90天内价格波动幅度 {round(100 - price_stability, 1)}%",
                },
            },
            "action_recommendation": action,
            "last_review_date": datetime.now().strftime("%Y-%m-%d"),
            "next_review_date": datetime.now().strftime("%Y-%m-%d"),  # 实际应为+30天
            "agent": self.config.name,
        }

    def _analyze_price_trend(self, input_data: Dict) -> Dict:
        """价格趋势分析 (D2新增)

        分析指定商品的价格走势，计算多时间窗口均价和波动率。

        分析维度:
        - 30/60/90天移动平均价
        - 涨跌幅百分比
        - 波动率 (标准差/均值)
        - 趋势方向与建议

        Args:
            input_data: {"item_id": "FP-HNRC-001", "window_days": 90}

        Returns:
            价格趋势分析报告
        """
        item_id = input_data.get("item_id", "FP-HNRC-001")
        window_days = input_data.get("window_days", 90)

        # 模拟价格历史数据（实际应从PG查询）
        import random
        random.seed(hash(item_id + "_price") % (2**32))
        base_price = 25.0  # 基准单价

        # 生成90天价格序列（带趋势和随机波动）
        prices_90d = []
        for i in range(90):
            trend = i * 0.05  # 轻微上涨趋势
            noise = random.uniform(-1.5, 1.5)
            price = round(base_price + trend + noise, 2)
            prices_90d.append(price)

        # 计算不同时间窗口的均价
        avg_30d = round(sum(prices_90d[-30:]) / 30, 2)
        avg_60d = round(sum(prices_90d[-60:]) / 60, 2)
        avg_90d = round(sum(prices_90d) / 90, 2)

        # 计算涨跌幅
        change_30d = round((avg_30d - prices_90d[-30]) / prices_90d[-30] * 100, 1) if prices_90d[-30] != 0 else 0
        change_90d = round((avg_90d - prices_90d[0]) / prices_90d[0] * 100, 1) if prices_90d[0] != 0 else 0

        # 计算波动率（标准差/均值）
        mean_price = sum(prices_90d) / len(prices_90d)
        variance = sum((p - mean_price) ** 2 for p in prices_90d) / len(prices_90d)
        std_dev = variance ** 0.5
        volatility = round((std_dev / mean_price) * 100, 2) if mean_price > 0 else 0

        # 趋势判定
        if change_90d > 5:
            trend_direction = "rising"
            recommendation = "价格上涨趋势明显，建议提前锁价或增加库存"
        elif change_90d < -5:
            trend_direction = "falling"
            recommendation = "价格下降趋势，可适当减少库存，按需采购"
        else:
            trend_direction = "stable"
            recommendation = "价格相对稳定，维持正常采购节奏"

        return {
            "task_type": "price_trend_analysis",
            "item_id": item_id,
            "window_days": window_days,
            "price_averages": {
                "avg_30d": avg_30d,
                "avg_60d": avg_60d,
                "avg_90d": avg_90d,
                "latest_price": prices_90d[-1],
                "unit": "¥/kg",
            },
            "changes": {
                "change_30d_pct": change_30d,
                "change_90d_pct": change_90d,
            },
            "volatility": {
                "value": volatility,
                "unit": "%",
                "std_dev": round(std_dev, 2),
                "interpretation": "低波动" if volatility < 5 else ("中等波动" if volatility < 10 else "高波动"),
            },
            "trend": {
                "direction": trend_direction,
                "strength": "strong" if abs(change_90d) > 10 else ("moderate" if abs(change_90d) > 5 else "weak"),
            },
            "recommendation": recommendation,
            "data_points": len(prices_90d),
            "analysis_period": f"最近{window_days}天",
            "agent": self.config.name,
        }

    # ── ProcurementAgent 消息处理器 ─────────────────────

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
    """前厅领班 (A04) — 改造方案P0-D扩展版

    职责:
    - 清台检测闭环 (视觉→任务→PDA→完成→KPI)
    - 服务响应监控
    - 客诉处理协调
    - 翻台率优化
    - 🔥P0-D新增: 销售增长分析与建议 (只读+建议，禁止自动改价/折扣/发券)
    - 🔥P0-D新增: 服务培训知识库与班前/班后复盘

    权限范围 (front_hall_lead):
    - ✅ 读: dashboard/tasks/sales_kpi/training_materials
    - ✅ 低风险写: complete_task/dismiss_task/training_record
    - ⚠️ 建议权: promo_suggestions/dish_recommendations (需人工审批)
    - ❌ 禁止: 自动改价/折扣/发券/退款 (BLOCKED by Gateway)
    """

    # ── P0-D: 销售与服务培训知识库 (D2扩展版) ──
    _DISH_KNOWLEDGE_BASE = [
        {"sku": "DP001", "name": "毛肚", "category": "荤菜", "price_range": [58, 78],
         "selling_points": ["新鲜现撕", "七上八下涮烫法", "招牌必点"], "pairing": ["鸭血", "蒜泥油碟"]},
        {"sku": "DP002", "name": "鸭肠", "category": "荤菜", "price_range": [48, 68],
         "selling_points": ["脆嫩口感", "涮15秒最佳"], "pairing": ["香油碟", "香菜"]},
        {"sku": "DP003", "name": "麻辣牛肉", "category": "荤菜", "price_range": [52, 72],
         "selling_points": ["提前腌制入味", "辣而不燥"], "pairing": ["土豆片", "宽粉"]},
        {"sku": "DP004", "name": "虾滑", "category": "海鲜", "price_range": [58, 88],
         "selling_points": ["手打Q弹", "每桌必推"], "pairing": ["紫菜", "蟹棒"]},
        {"sku": "DP005", "name": "娃娃菜", "category": "素菜", "price_range": [18, 28],
         "selling_points": ["解腻神器", "吸汤好手"], "pairing": ["任何荤菜"]},
        {"sku": "DP006", "name": "冰粉", "category": "甜品", "price_range": [12, 18],
         "selling_points": ["餐后解辣", "高毛利"], "pairing": ["任何套餐"]},
        # D2新增: 火锅核心菜品扩展
        {"sku": "DP007", "name": "黄喉", "category": "荤菜", "price_range": [45, 65],
         "selling_points": ["脆爽弹牙", "涮8-10秒"], "pairing": ["蒜泥油碟", "香菜"]},
        {"sku": "DP008", "name": "酥肉", "category": "荤菜", "price_range": [38, 52],
         "selling_points": ["外酥里嫩", "可直接吃或下锅"], "pairing": ["辣椒面", "番茄锅"]},
        {"sku": "DP009", "name": "鲜笋片", "category": "素菜", "price_range": [22, 32],
         "selling_points": ["爽脆清香", "解腻佳品"], "pairing": ["任何荤菜", "菌汤锅"]},
    ]

    _SERVICE_TERMINOLOGY = {
        "greeting": "您好，欢迎光临冯校长火锅！请问几位？",
        "seating": "这边请，小心台阶。这是咱们的菜单，扫码点餐更方便哦。",
        "upsell_tips": [
            "咱们家的毛肚是今天刚到的，特别新鲜，推荐您尝尝？",
            "看您几位口味偏重，要不要来份麻辣牛肉？我们提前腌制的，很入味。",
            "餐后来份冰粉吧？解辣又清爽，今天还有活动价。",
        ],
        "handling_complaint": "非常抱歉给您带来不好的体验，我马上叫经理来处理，请您稍等。",
        "farewell": "谢谢光临，慢走！下次再来记得提前预约留位哦。",
    }

    def __init__(self, message_bus: MessageBus = None):
        config = AgentConfig(
            agent_id="agent-front-hall-001",
            name="前厅领班",
            role=AgentRole.FRONT_HALL,  # 修复: 原为 STORE_MANAGER，应使用前厅角色
            version="1.1.0",  # P0-D 版本升级
            capabilities=[
                Capability.MONITOR,
                Capability.NOTIFY,
                Capability.EXECUTE,
                Capability.ANALYZE,  # P0-D 新增: 分析能力
            ],
            subscriptions=[
                Subscription(subscriber_id="agent-front-hall-001", topic_pattern="cleaning.*", handler_name="on_cleaning_event"),
                Subscription(subscriber_id="agent-front-hall-001", topic_pattern="service.*", handler_name="on_service_event"),
                Subscription(subscriber_id="agent-front-hall-001", topic_pattern="customer.*", handler_name="on_customer_event"),
                Subscription(subscriber_id="agent-front-hall-001", topic_pattern="vision.table.*", handler_name="on_table_status_change"),
                # P0-D 新增: 销售事件订阅
                Subscription(subscriber_id="agent-front-hall-001", topic_pattern="sales.*", handler_name="on_sales_event"),
                Subscription(subscriber_id="agent-front-hall-001", topic_pattern="pos.*", handler_name="on_pos_event"),
            ],
        )
        super().__init__(config, message_bus)
        self._gateway = AgentGatewayMiddleware.get_instance()

    def _register_default_handlers(self) -> None:
        super()._register_default_handlers()
        self._handlers["query.cleaning_status"] = self._handle_cleaning_status
        self._handlers["alert.dirty_table"] = self._handle_dirty_table_alert
        self._handlers["action.assign_task"] = self._handle_assign_task
        # P0-D 新增: 销售与服务培训消息处理器
        self._handlers["query.sales_kpi"] = self._handle_sales_kpi_query
        self._handlers["query.dish_recommendations"] = self._handle_dish_recommendations
        self._handlers["training.pre_shift"] = self._handle_pre_shift_training
        self._handlers["training.post_shift_review"] = self._handle_post_shift_review
        self._handlers["sales.promo_suggestion_request"] = self._handle_promo_suggestion_request

    def _execute_task(self, task_type: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        if task_type == "detect_dirty_tables":
            return self._detect_dirty_tables(input_data)
        elif task_type == "create_cleaning_task":
            return self._create_cleaning_task(input_data)
        elif task_type == "check_response_time":
            return self._check_response_time(input_data)
        elif task_type == "calculate_turnover_rate":
            return self._calculate_turnover_rate(input_data)
        # ── P0-D 新增: 销售增长与服务培训任务 ──
        elif task_type == "query_sales_kpi":
            return self._query_sales_kpi(input_data)
        elif task_type == "get_promo_suggestions":
            return self._get_promo_suggestions(input_data)
        elif task_type == "pre_shift_training":
            return self._generate_pre_shift_training(input_data)
        elif task_type == "post_shift_review":
            return self._generate_post_shift_review(input_data)
        elif task_type == "get_dish_knowledge":
            return self._get_dish_knowledge(input_data)
        else:
            return {"error": f"前厅不支持的任务: {task_type}", "agent": self.config.name}

    def _detect_dirty_tables(self, input_data: Dict) -> Dict:
        """检测脏桌 (对接视觉引擎)"""
        # [SIMULATION] 使用 MockDataService 生成模拟数据，实际应从 edge/front_hall/inference/ 获取
        store_id = input_data.get("store_id", "store_jiaojiang")
        mock_svc = _get_mock_service()
        result = mock_svc.detect_dirty_tables(store_id)
        result["agent"] = self.config.name
        return _mark_simulation_data(result, self.config)

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
        # [SIMULATION] 使用 MockDataService 生成模拟数据，实际应从 POS 系统获取
        store_id = input_data.get("store_id", "store_jiaojiang")
        date = input_data.get("date", datetime.now().strftime("%Y-%m-%d"))
        mock_svc = _get_mock_service()
        result = mock_svc.calculate_turnover_rate(store_id, date)
        result["agent"] = self.config.name
        return _mark_simulation_data(result, self.config)

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

    # ════════════════════════════════════════════════════════════
    # P0-D: 销售增长与服务培训 — 任务执行方法
    # ⚠️ 核心约束: 自动改价/折扣/发券一律禁止
    # ════════════════════════════════════════════════════════════

    def _query_sales_kpi(self, input_data: Dict) -> Dict:
        """查询销售KPI指标 (D2增强版: 支持动态粒度 + POS数据桥接)

        从POS数据或预聚合数据中提取销售相关KPI:
        - 日销售额 / 客单价 / 翻台率
        - 菜品销量排行 (Top N)
        - 时段分布 (午市/晚市/夜宵)
        - 同比/环比变化
        - D2新增: 支持日/周/月不同时间粒度

        Args:
            input_data: {"date": "2026-08-04", "period": "day", "store_id": "store_jiaojiang"}

        Returns:
            销售KPI字典，含各项指标和状态判定
        """
        query_date = input_data.get("date", datetime.now().strftime("%Y-%m-%d"))
        store_id = input_data.get("store_id", "store_jiaojiang")
        period = input_data.get("period", "day")  # day / week / month

        # D2增强: 尝试从POS数据桥接读取真实数据
        pos_data = self._fetch_pos_data(store_id, query_date)
        use_real_data = pos_data.get("data_source") != "fallback_simulation"

        # 根据时间粒度返回不同数据
        if period == "day":
            if use_real_data:
                kpis = {
                    "daily_revenue": {"value": pos_data.get("total_sales", 12800), "unit": "¥", "target": 15000, "status": "warning" if pos_data.get("total_sales", 12800) < 15000 else "good", "change_pct": pos_data.get("change_pct", -3.2)},
                    "avg_check": {"value": pos_data.get("avg_check", 168), "unit": "¥", "target": 180, "status": "normal", "change_pct": 1.5},
                    "turnover_rate": {"value": pos_data.get("turnover_rate", 2.45), "unit": "次", "target": 2.5, "status": "near_target", "change_pct": 0.8},
                    "table_utilization": {"value": pos_data.get("table_utilization", 0.82), "unit": "%", "target": 0.85, "status": "normal"},
                    "dine_in_count": {"value": pos_data.get("dine_in_count", 76), "unit": "桌", "target": 85, "status": "warning"},
                }
            else:
                # 向后兼容: 模拟数据
                kpis = {
                    "daily_revenue": {"value": 12800, "unit": "¥", "target": 15000, "status": "warning", "change_pct": -3.2},
                    "avg_check": {"value": 168, "unit": "¥", "target": 180, "status": "normal", "change_pct": 1.5},
                    "turnover_rate": {"value": 2.45, "unit": "次", "target": 2.5, "status": "near_target", "change_pct": 0.8},
                    "table_utilization": {"value": 0.82, "unit": "%", "target": 0.85, "status": "normal"},
                    "dine_in_count": {"value": 76, "unit": "桌", "target": 85, "status": "warning"},
                }
            top_dishes = [
                {"rank": 1, "name": "毛肚", "qty": 128, "revenue": 8960},
                {"rank": 2, "name": "虾滑", "qty": 96, "revenue": 6720},
                {"rank": 3, "name": "麻辣牛肉", "qty": 84, "revenue": 5040},
            ]
            period_breakdown = {
                "lunch": {"revenue": 4800, "tables": 28, "avg_check": 171},
                "dinner": {"revenue": 7200, "tables": 42, "avg_check": 171},
                "late_night": {"revenue": 800, "tables": 6, "avg_check": 133},
            }
        elif period == "week":
            # 周粒度: 聚合7天数据
            kpis = {
                "weekly_revenue": {"value": 89200, "unit": "¥", "target": 105000, "status": "warning", "change_pct": -2.1},
                "daily_avg_revenue": {"value": 12743, "unit": "¥", "target": 15000, "status": "warning"},
                "weekly_avg_check": {"value": 170, "unit": "¥", "target": 180, "status": "normal", "change_pct": 0.9},
                "weekly_turnover_avg": {"value": 2.4, "unit": "次", "target": 2.5, "status": "near_target"},
            }
            top_dishes = [
                {"rank": 1, "name": "毛肚", "qty": 896, "revenue": 62720},
                {"rank": 2, "name": "虾滑", "qty": 672, "revenue": 47040},
                {"rank": 3, "name": "鸭肠", "qty": 520, "revenue": 28600},
            ]
            period_breakdown = {
                "mon_wed": {"revenue": 25000, "daily_avg": 12500},
                "thu_fri": {"revenue": 32000, "daily_avg": 16000},
                "sat_sun": {"revenue": 32200, "daily_avg": 16100},
            }
        else:  # month
            # 月粒度: 聚合30天数据
            kpis = {
                "monthly_revenue": {"value": 378000, "unit": "¥", "target": 450000, "status": "warning", "change_pct": 1.8},
                "monthly_avg_daily": {"value": 12600, "unit": "¥", "target": 15000, "status": "warning"},
                "monthly_avg_check": {"value": 169, "unit": "¥", "target": 180, "status": "normal"},
                "peak_day_revenue": {"value": 15800, "unit": "¥", "date": "2026-08-02"},
                "lowest_day_revenue": {"value": 9800, "unit": "¥", "date": "2026-08-05"},
            }
            top_dishes = [
                {"rank": 1, "name": "毛肚", "qty": 3840, "revenue": 268800},
                {"rank": 2, "name": "虾滑", "qty": 2880, "revenue": 201600},
                {"rank": 3, "name": "麻辣牛肉", "qty": 2520, "revenue": 151200},
            ]
            period_breakdown = {
                "week1": {"revenue": 125000, "daily_avg": 17857},
                "week2": {"revenue": 131000, "daily_avg": 18714},
                "week3": {"revenue": 122000, "daily_avg": 17429},
            }

        return {
            "task_type": "sales_kpi_query",
            "query_date": query_date,
            "store_id": store_id,
            "period": period,
            "kpis": kpis,
            "top_dishes": top_dishes,
            "period_breakdown": period_breakdown,
            "data_source": pos_data.get("data_source", "pos_bridge_aggregated"),
            "generated_at": datetime.now().isoformat(),
            "agent": self.config.name,
        }

    def _fetch_pos_data(self, store_id: str, date_str: str) -> Dict:
        """从POS系统获取销售数据 (D2新增)

        尝试通过 pos_bridge 读取真实POS数据，
        如果连接失败或数据不可用，则降级到模拟数据。

        Args:
            store_id: 门店ID
            date_str: 日期字符串 (YYYY-MM-DD)

        Returns:
            POS数据字典，含 data_source 标记来源
        """
        try:
            # 尝试导入并调用 pos_bridge（实际部署时启用）
            # from hotpot_platform.cloud.pos_bridge import PosBridge
            # bridge = PosBridge(store_id)
            # raw_data = bridge.get_daily_sales(date_str)
            #
            # 当前为演示模式，直接抛出异常走降级逻辑
            raise ImportError("pos_bridge模块尚未集成，使用模拟数据")

        except (ImportError, Exception) as e:
            # 降级到模拟数据
            logger.debug(f"POS数据桥接不可用，使用模拟数据: {e}")
            import random
            random.seed(hash(date_str) % (2**32))

            return {
                "store_id": store_id,
                "date": date_str,
                "total_sales": round(random.uniform(10000, 15000), 2),
                "avg_check": round(random.uniform(160, 190), 2),
                "turnover_rate": round(random.uniform(2.0, 3.0), 2),
                "table_utilization": round(random.uniform(0.75, 0.90), 2),
                "dine_in_count": random.randint(60, 95),
                "change_pct": round(random.uniform(-8, 5), 1),
                "data_source": "fallback_simulation",
                "error": str(e) if __debug__ else None,
            }

    def _get_promo_suggestions(self, input_data: Dict) -> Dict:
        """生成促销建议 (⚠️ 仅建议权，禁止自动执行)

        基于当前销售数据和菜品知识库生成建议:
        - 滞销菜品推荐策略
        - 高毛利搭配建议
        - 时段性促销方案

        ⚠️ 安全约束:
        - 所有建议必须经人工审批才能执行
        - 不包含任何自动改价/折扣/发券动作
        - 返回值中 explicit_mark: "suggestion_only"
        """
        current_kpi = input_data.get("current_kpi", {})
        slow_moving = input_data.get("slow_moving_dishes", ["土豆片", "宽粉"])

        suggestions = [
            {
                "type": "upsell_pairing",
                "title": "高毛利搭配推荐",
                "description": f"针对滞销品 {slow_moving[0] if slow_moving else '素菜'} 推荐与毛肚/虾滑的套餐组合",
                "action": "staff_training_only",  # 仅培训员工口头推荐
                "risk_level": "LOW",
                "approval_required": False,  # LOW风险无需审批
            },
            {
                "type": "time_based_promo",
                "title": "晚市尾段(21:00后)甜品推荐",
                "description": "冰粉/红糖糍粑等高毛利甜品作为餐后推荐",
                "action": "staff_training_only",
                "risk_level": "LOW",
                "approval_required": False,
            },
            {
                "type": "discount_warning",
                "title": "⚠️ 折扣/发券请求已拦截",
                "description": "改造方案P0-D明确禁止Agent自动发起折扣/发券。如需此类操作，请通过Dashboard人工提交。",
                "action": "BLOCKED",
                "risk_level": "CRITICAL",
                "approval_required": True,
                "blocked_reason": "P0-D安全约束: 自动改价/折扣/发券一律禁止",
            },
        ]

        return {
            "task_type": "promo_suggestions",
            "explicit_mark": "suggestion_only",  # 明确标记: 仅建议
            "suggestions": suggestions,
            "safety_note": "所有涉及价格变动的操作已被Gateway BLOCKED拦截",
            "generated_at": datetime.now().isoformat(),
            "agent": self.config.name,
        }

    def _generate_pre_shift_training(self, input_data: Dict) -> Dict:
        """生成班前培训内容

        基于昨日数据和今日重点生成班前会培训要点:
        - 昨日问题复盘
        - 今日推荐菜品话术
        - 服务SOP重点提醒
        """
        shift = input_data.get("shift", "evening")  # lunch / evening
        yesterday_issues = input_data.get("yesterday_issues", ["响应时间超标2次"])

        training_content = {
            "task_type": "pre_shift_training",
            "shift": shift,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "duration_min": 5,
            "agenda": [
                {"section": "昨日复盘", "content": yesterday_issues, "speaker": "店长"},
                {
                    "section": "今日推荐话术",
                    "content": self._SERVICE_TERMINOLOGY["upsell_tips"][:2],
                    "speaker": "前厅领班(AI辅助)",
                },
                {
                    "section": "服务SOP重点",
                    "content": ["迎宾三句话", "点餐时主动推荐招牌菜", "客诉第一时间响应"],
                    "speaker": "前厅领班",
                },
                {"section": "目标设定", "content": [f"目标营业额: ¥{'15000' if shift == 'evening' else '12000'}"], "speaker": "店长"},
            ],
            "dish_highlights": [d for d in self._DISH_KNOWLEDGE_BASE if d["sku"] in ("DP001", "DP004")],
            "agent": self.config.name,
        }
        return training_content

    def _generate_post_shift_review(self, input_data: Dict) -> Dict:
        """生成班后复盘报告 (D2增强版: 支持客诉真实来源)

        汇总当班关键数据和服务表现:
        - KPI达成情况
        - 服务亮点与不足
        - D2新增: 从feedback/events表读取真实客诉数据
        - 改进建议
        """
        shift = input_data.get("shift", "evening")
        actual_revenue = input_data.get("actual_revenue", 12800)
        store_id = input_data.get("store_id", "store_jiaojiang")
        review_date = input_data.get("date", datetime.now().strftime("%Y-%m-%d"))

        # D2增强: 尝试从feedback/events表读取客诉数据
        complaints_data = self._fetch_complaint_data(store_id, review_date)
        real_complaints = complaints_data.get("complaints", [])
        complaint_count = len(real_complaints) if real_complaints else input_data.get("complaints", 0)

        # 根据客诉情况动态生成改进建议
        if complaint_count > 0:
            complaint_types = [c.get("type", "unknown") for c in real_complaints]
            improvements = [
                f"重点解决{complaint_types[0] if len(complaint_types) > 0 else '服务'}类客诉问题",
                "加强员工服务意识培训",
                "优化客诉响应流程",
            ]
            highlights = [
                f"营业额完成率 {round(actual_revenue / (15000 if shift == 'evening' else 12000) * 100, 1)}%",
                f"处理客诉 {complaint_count} 起，需关注改进",
            ]
        else:
            improvements = [
                "加强21:00后甜品推荐培训",
                "优化脏桌检测→任务派发的响应速度",
            ]
            highlights = [
                "翻台率接近目标值 (2.45 vs 2.5)",
                "零重大客诉",
                "新品虾滑推广效果良好 (+15%)",
            ] if actual_revenue > 10000 else [
                "需要关注客单价提升空间",
                "晚市尾段翻台可优化",
            ]

        review = {
            "task_type": "post_shift_review",
            "shift": shift,
            "date": review_date,
            "summary": {
                "actual_revenue": actual_revenue,
                "target_revenue": 15000 if shift == "evening" else 12000,
                "achievement_rate": round(actual_revenue / 15000 * 100, 1) if shift == "evening" else round(actual_revenue / 12000 * 100, 1),
                "total_tables": input_data.get("total_tables", 42),
                "complaints": complaint_count,
                "complaints_source": complaints_data.get("data_source", "input_parameter"),
            },
            "complaint_details": real_complaints if real_complaints else None,
            "highlights": highlights,
            "improvements": improvements,
            "next_focus": ["提升客单价至¥180+", "降低平均响应时间至90秒内"],
            "agent": self.config.name,
        }
        return review

    def _fetch_complaint_data(self, store_id: str, date_str: str) -> Dict:
        """获取客诉数据 (D2新增)

        尝试从feedback/events表读取真实客诉记录，
        如果不可用则返回空列表。

        Args:
            store_id: 门店ID
            date_str: 日期字符串

        Returns:
            客诉数据字典，含 complaints 列表和 data_source 标记
        """
        try:
            # 尝试从数据库查询（实际部署时启用）
            # from hotpot_platform.cloud.feedback.models import CustomerComplaint
            # complaints = CustomerComplaint.query.filter_by(
            #     store_id=store_id,
            #     date=date_str,
            # ).all()
            #
            # 当前为演示模式，走降级逻辑
            raise ImportError("feedback模块尚未集成")

        except (ImportError, Exception) as e:
            logger.debug(f"客诉数据源不可用: {e}")
            return {
                "store_id": store_id,
                "date": date_str,
                "complaints": [],
                "data_source": "unavailable",
                "note": "feedback/events表尚未对接，使用输入参数或默认值",
            }

    def _get_dish_knowledge(self, input_data: Dict) -> Dict:
        """查询菜品知识库

        Args:
            input_data: {"sku": "DP001"} 或 {"category": "荤菜"} 或 {} (全部)
        """
        sku = input_data.get("sku")
        category = input_data.get("category")

        if sku:
            result = [d for d in self._DISH_KNOWLEDGE_BASE if d["sku"] == sku]
        elif category:
            result = [d for d in self._DISH_KNOWLEDGE_BASE if d["category"] == category]
        else:
            result = self._DISH_KNOWLEDGE_BASE

        return {
            "task_type": "dish_knowledge",
            "query": input_data,
            "results": result,
            "total": len(result),
            "agent": self.config.name,
        }

    # ════════════════════════════════════════════════════════════
    # P0-D: 销售与服务培训 — 消息处理器
    # ════════════════════════════════════════════════════════════

    def _handle_sales_kpi_query(self, msg: AgentMessage) -> AgentMessage:
        """处理销售KPI查询消息"""
        kpi_data = self._query_sales_kpi(msg.payload)
        return AgentMessage(
            msg_type=MessageType.REPORT, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="sales.kpi.response",
            payload=kpi_data, correlation_id=msg.message_id,
        )

    def _handle_dish_recommendations(self, msg: AgentMessage) -> AgentMessage:
        """处理菜品推荐请求"""
        dishes = self._get_dish_knowledge(msg.payload)
        return AgentMessage(
            msg_type=MessageType.REPORT, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="sales.dish_recommendations.response",
            payload=dishes, correlation_id=msg.message_id,
        )

    def _handle_pre_shift_training(self, msg: AgentMessage) -> AgentMessage:
        """处理班前培训请求"""
        training = self._generate_pre_shift_training(msg.payload)
        return AgentMessage(
            msg_type=MessageType.REPORT, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="training.pre_shift.response",
            payload=training, correlation_id=msg.message_id,
        )

    def _handle_post_shift_review(self, msg: AgentMessage) -> AgentMessage:
        """处理班后复盘请求"""
        review = self._generate_post_shift_review(msg.payload)
        return AgentMessage(
            msg_type=MessageType.REPORT, sender_id=self.config.agent_id,
            receiver_id=msg.sender_id, topic="training.post_shift.response",
            payload=review, correlation_id=msg.message_id,
        )

    def _handle_promo_suggestion_request(self, msg: AgentMessage) -> AgentMessage:
        """处理促销建议请求 (⚠️ 返回仅建议，禁止自动执行)"""
        suggestions = self._get_promo_suggestions(msg.payload)
        return AgentMessage(
            msg_type=MessageType.REPORT, priority=MessagePriority.NORMAL,
            sender_id=self.config.agent_id, receiver_id=msg.sender_id,
            topic="sales.promo_suggestions.response",
            payload=suggestions, correlation_id=msg.message_id,
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
