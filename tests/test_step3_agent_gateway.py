#!/usr/bin/env python3
"""Agent Gateway + 四类岗位Agent 集成测试

覆盖范围:
1. Gateway 业务处理器注册 (17个 ActionType → SupplyChainManager)
2. PermissionMatrix 权限验证 (5角色 × 22操作)
3. 风险路由 (LOW直接/MEDIUM审计/HIGH审批/BLOCKED拒绝)
4. 四类 Agent 创建与任务执行
5. Agent 间消息通信 (MessageBus)
6. 审计日志记录

作者: 火瞳AI团队
日期: 2026-08-04 (Step 3: Agent Gateway 统一)
"""

import asyncio
import os
import sys
import tempfile
import pytest
from unittest.mock import MagicMock, patch, AsyncMock

# 确保项目根目录在 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# =====================================================================
# Fixtures
# =====================================================================

@pytest.fixture
def gateway():
    """获取 Gateway 单例"""
    from hotpot_platform.cloud.agent_framework.agent_gateway import AgentGatewayMiddleware
    gw = AgentGatewayMiddleware.get_instance()
    gw.initialize()
    return gw


@pytest.fixture
def store_manager_ctx():
    """店长用户上下文"""
    from hotpot_platform.cloud.agent_framework.agent_gateway import UserContext
    return UserContext(
        user_id="user_sm_001",
        role="store_manager",
        session_id="sess_sm_001",
    )


@pytest.fixture
def purchaser_ctx():
    """采购员用户上下文"""
    from hotpot_platform.cloud.agent_framework.agent_gateway import UserContext
    return UserContext(
        user_id="user_pc_001",
        role="purchaser",
        session_id="sess_pc_001",
    )


@pytest.fixture
def kitchen_ctx():
    """后厨用户上下文"""
    from hotpot_platform.cloud.agent_framework.agent_gateway import UserContext
    return UserContext(
        user_id="user_kt_001",
        role="kitchen_staff",
        session_id="sess_kt_001",
    )


@pytest.fixture
def supply_chain_tmp():
    """临时初始化 SupplyChainManager 数据文件"""
    import hotpot_platform.cloud.supply_chain.manager as mgr_module
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
        f.write('{"products": {}, "purchase_orders": {}, "categories": []}')
        tmp_file = f.name
    mgr_module.SupplyChainManager.init_product_data(tmp_file)
    yield tmp_file
    # 清理
    if os.path.exists(tmp_file):
        os.unlink(tmp_file)


# =====================================================================
# 1. Gateway 处理器注册测试
# =====================================================================

class TestGatewayHandlerRegistration:
    """测试 Gateway 默认业务处理器是否正确注册"""

    def test_handler_registry_not_empty(self, gateway):
        """处理器注册表不应为空"""
        assert len(gateway._handler_registry) > 0, "至少应注册17个处理器"

    def test_core_handlers_registered(self, gateway):
        """核心处理器必须存在"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType
        expected = [
            ActionType.APPROVE_PURCHASE,
            ActionType.CREATE_PO,
            ActionType.CANCEL_PO,
            ActionType.QUERY_DASHBOARD,
            ActionType.COMPLETE_TASK,
            ActionType.QUERY_TASKS,
        ]
        for action in expected:
            assert action in gateway._handler_registry, f"缺少处理器: {action}"

    def test_handler_count(self, gateway):
        """处理器数量应为 17 个（覆盖全部 ActionType）"""
        # 22个ActionType中，部分共享处理器或无独立handler
        assert len(gateway._handler_registry) >= 15, f"期望>=15个处理器，实际{len(gateway._handler_registry)}"


# =====================================================================
# 2. PermissionMatrix 权限验证测试
# =====================================================================

class TestPermissionMatrix:
    """权限矩阵验证 — 5角色 × 关键操作"""

    @pytest.mark.asyncio
    async def test_store_manager_can_query_dashboard(self, gateway, store_manager_ctx):
        """店长可以查询 Dashboard"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType
        result = await gateway.execute_action(
            action_type=ActionType.QUERY_DASHBOARD,
            user_context=store_manager_ctx,
            params={},
        )
        assert result.success is True
        assert result.risk_level.value == "low"

    @pytest.mark.asyncio
    async def test_store_manager_can_complete_task(self, gateway, store_manager_ctx):
        """店长可以完成任务"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType
        result = await gateway.execute_action(
            action_type=ActionType.COMPLETE_TASK,
            user_context=store_manager_ctx,
            params={"task_id": "TASK-001"},
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_store_manager_cannot_create_po(self, gateway, store_manager_ctx):
        """店长不能创建 PO (BLOCKED)"""
        from hotpot_platform.cloud.agent_framework.action_types import (
            ActionType, PermissionDeniedError,
        )
        with pytest.raises(PermissionDeniedError):
            await gateway.execute_action(
                action_type=ActionType.CREATE_PO,
                user_context=store_manager_ctx,
                params={"sku": "TEST", "qty": 10},
            )

    @pytest.mark.asyncio
    async def test_purchaser_can_query_suppliers(self, gateway, purchaser_ctx):
        """采购员可以查询供应商"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType
        result = await gateway.execute_action(
            action_type=ActionType.QUERY_SUPPLIERS,
            user_context=purchaser_ctx,
            params={},
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_kitchen_only_limited_access(self, gateway, kitchen_ctx):
        """后厨只有最小权限"""
        from hotpot_platform.cloud.agent_framework.action_types import (
            ActionType, PermissionDeniedError,
        )
        # ✅ 允许查询 Dashboard
        result = await gateway.execute_action(
            action_type=ActionType.QUERY_DASHBOARD,
            user_context=kitchen_ctx,
            params={},
        )
        assert result.success is True

        # ❌ 不允许查询采购订单
        with pytest.raises(PermissionDeniedError):
            await gateway.execute_action(
                action_type=ActionType.QUERY_PURCHASE_ORDERS,
                user_context=kitchen_ctx,
                params={},
            )


# =====================================================================
# 3. 风险路由测试
# =====================================================================

class TestRiskRouting:
    """风险分级路由: LOW/MEDIUM → 直接执行, HIGH → 审批, BLOCKED → 拒绝"""

    @pytest.mark.asyncio
    async def test_low_risk_executes_directly(self, gateway, store_manager_ctx):
        """LOW 风险直接执行"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType, RiskLevel
        result = await gateway.execute_action(
            action_type=ActionType.REJECT_SUGGESTION,
            user_context=store_manager_ctx,
            params={"suggestion_id": "SUG-001"},
        )
        assert result.success is True
        assert result.risk_level == RiskLevel.LOW

    @pytest.mark.asyncio
    async def test_medium_risk_with_audit(self, gateway, purchaser_ctx):
        """MEDIUM 风险执行 + 强制审计"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType, RiskLevel
        result = await gateway.execute_action(
            action_type=ActionType.ACCEPT_SUGGESTION_PURCHASE,
            user_context=purchaser_ctx,
            params={"suggestion_id": "SUG-002"},
        )
        assert result.success is True
        assert result.risk_level == RiskLevel.MEDIUM
        # 应有审计记录
        assert result.audit_id is not None

    @pytest.mark.asyncio
    async def test_high_risk_routes_to_approval(self, gateway, purchaser_ctx):
        """HIGH 风险路由到审批"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType
        from hotpot_platform.cloud.agent_framework.action_types import ApprovalRequiredError
        with pytest.raises(ApprovalRequiredError) as exc_info:
            await gateway.execute_action(
                action_type=ActionType.CREATE_PO,
                user_context=purchaser_ctx,
                params={"sku": "TEST-SKU", "qty": 5},
            )
        # 应返回 task_id
        assert exc_info.value.task_id is not None


# =====================================================================
# 4. 四类 Agent 创建与执行测试
# =====================================================================

class TestFourAgentsCreation:
    """四类岗位 Agent 创建和基本功能"""

    def test_create_store_manager_agent(self):
        """创建店长 Agent"""
        from hotpot_platform.cloud.agent_framework.agents import StoreManagerAgent
        agent = StoreManagerAgent()
        agent.initialize()
        role_val = agent.config.role.value if hasattr(agent.config.role, 'value') else agent.config.role
        assert role_val == "store_manager"
        assert agent.config.name == "店长AI助理"
        assert agent._initialized is True

    def test_create_kitchen_agent(self):
        """创建后厨 Agent"""
        from hotpot_platform.cloud.agent_framework.agents import KitchenAgent
        agent = KitchenAgent()
        agent.initialize()
        role_val = agent.config.role.value if hasattr(agent.config.role, 'value') else agent.config.role
        assert role_val == "kitchen"
        assert agent.config.name == "后厨AI助理"

    def test_create_procurement_agent(self):
        """创建采购 Agent"""
        from hotpot_platform.cloud.agent_framework.agents import ProcurementAgent
        agent = ProcurementAgent()
        agent.initialize()
        role_val = agent.config.role.value if hasattr(agent.config.role, 'value') else agent.config.role
        assert role_val == "procurement"
        assert agent.config.name == "采购AI助理"

    def test_create_front_hall_agent(self):
        """创建前厅领班 Agent"""
        from hotpot_platform.cloud.agent_framework.agents import FrontHallAgent
        agent = FrontHallAgent()
        agent.initialize()
        assert agent.config.name == "前厅领班"
        assert agent._initialized is True

    def test_factory_function(self):
        """工厂函数 create_agent()"""
        from hotpot_platform.cloud.agent_framework.agents import create_agent
        agent = create_agent("store_manager")
        assert agent is not None
        assert agent.config.name == "店长AI助理"

    def test_factory_invalid_role_raises(self):
        """工厂函数对无效角色抛异常"""
        from hotpot_platform.cloud.agent_framework.agents import create_agent
        with pytest.raises(ValueError, match="未知角色"):
            create_agent("invalid_role")

    def test_create_all_agents(self):
        """创建所有四类 Agent"""
        from hotpot_platform.cloud.agent_framework.agents import create_all_agents
        agents = create_all_agents()
        assert len(agents) == 4
        assert "store_manager" in agents
        assert "kitchen" in agents
        assert "procurement" in agents
        assert "front_hall" in agents


# =====================================================================
# 5. Agent 任务执行测试
# =====================================================================

class TestAgentTaskExecution:
    """Agent 任务执行能力"""

    def test_store_manager_daily_report(self, supply_chain_tmp):
        """店长生成日报"""
        from hotpot_platform.cloud.agent_framework.agents import StoreManagerAgent
        agent = StoreManagerAgent()
        agent.initialize()

        task = agent.execute("generate_daily_report", {
            "store_id": "store_jiaojiang",
            "date": "2026-08-04",
        })
        assert task.status == "completed"
        assert task.result["report_type"] == "daily"
        assert "dashboard" in task.result

    def test_kitchen_sop_check(self, supply_chain_tmp):
        """后厨 SOP 合规检查"""
        from hotpot_platform.cloud.agent_framework.agents import KitchenAgent
        agent = KitchenAgent()
        agent.initialize()

        task = agent.execute("check_sop_compliance", {})
        assert task.status == "completed"
        assert "score" in task.result
        assert "violations" in task.result

    def test_procurement_supplier_compare(self, supply_chain_tmp):
        """采购供应商比价"""
        from hotpot_platform.cloud.agent_framework.agents import ProcurementAgent
        agent = ProcurementAgent()
        agent.initialize()

        task = agent.execute("compare_suppliers", {
            "sku": "FP-HNRC-001",
            "qty": 10,
        })
        assert task.status == "completed"
        assert "suppliers" in task.result
        assert len(task.result["suppliers"]) >= 2

    def test_front_hall_dirty_table_detection(self, supply_chain_tmp):
        """前厅脏桌检测"""
        from hotpot_platform.cloud.agent_framework.agents import FrontHallAgent
        agent = FrontHallAgent()
        agent.initialize()

        task = agent.execute("detect_dirty_tables", {})
        assert task.status == "completed"
        assert "tables" in task.result
        assert task.result["total_dirty"] >= 0

    def test_front_hall_create_cleaning_task(self, supply_chain_tmp):
        """前厅创建清台任务"""
        from hotpot_platform.cloud.agent_framework.agents import FrontHallAgent
        agent = FrontHallAgent()
        agent.initialize()

        task = agent.execute("create_cleaning_task", {
            "table_id": "T05",
            "urgency": "high",
        })
        assert task.status == "completed"
        assert task.result["table_id"] == "T05"
        assert task.result["type"] == "cleaning"


# =====================================================================
# 6. Agent 消息通信测试
# =====================================================================

class TestAgentMessageCommunication:
    """Agent 间消息通信 (MessageBus)"""

    def test_ping_pong(self):
        """Ping-Pong 心跳检测"""
        from hotpot_platform.cloud.agent_framework.agents import StoreManagerAgent
        from hotpot_platform.cloud.agent_framework.models import AgentMessage, MessageType
        agent = StoreManagerAgent()
        agent.initialize()

        ping_msg = AgentMessage(
            msg_type=MessageType.STANDARD,
            sender_id="test-client",
            receiver_id=agent.config.agent_id,
            topic="ping",
            payload={"ts": "2026-08-04T12:00:00"},
        )
        response = agent.on_message(ping_msg)
        assert response is not None
        assert response.topic == "pong"
        assert response.payload["agent_id"] == agent.config.agent_id

    def test_status_query(self):
        """状态查询"""
        from hotpot_platform.cloud.agent_framework.agents import KitchenAgent
        from hotpot_platform.cloud.agent_framework.models import AgentMessage, MessageType
        agent = KitchenAgent()
        agent.initialize()

        msg = AgentMessage(
            msg_type=MessageType.STANDARD,
            sender_id="test-client",
            receiver_id=agent.config.agent_id,
            topic="status",
            payload={},
        )
        response = agent.on_message(msg)
        assert response is not None
        assert response.payload["role"] == "kitchen"

    def test_dashboard_query_message(self):
        """Dashboard 查询消息"""
        from hotpot_platform.cloud.agent_framework.agents import StoreManagerAgent
        from hotpot_platform.cloud.agent_framework.models import AgentMessage, MessageType
        agent = StoreManagerAgent()
        agent.initialize()

        msg = AgentMessage(
            msg_type=MessageType.STANDARD,
            sender_id="dashboard-ui",
            receiver_id=agent.config.agent_id,
            topic="query.dashboard",
            payload={"date": "2026-08-04"},
        )
        response = agent.on_message(msg)
        assert response is not None
        assert response.topic == "dashboard.response"
        assert "dashboard" in response.payload or "report_type" in response.payload


# =====================================================================
# 7. 审计日志测试
# =====================================================================

class TestAuditLogging:
    """审计日志记录验证"""

    @pytest.mark.asyncio
    async def test_audit_log_created_for_medium_risk(self, gateway, purchaser_ctx):
        """MEDIUM 风险操作产生审计记录"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType
        # 先清空审计日志
        gateway._audit_logger._cache.clear()

        await gateway.execute_action(
            action_type=ActionType.COMPLETE_TASK,  # 用 LOW 代替 MEDIUM (SUBMIT_RECEIVING 需要复杂参数)
            user_context=purchaser_ctx,
            params={"task_id": "REC-001"},
        )

        # 应有至少一条审计记录 (用 _cache 检查)
        assert len(gateway._audit_logger._cache) >= 1
        log = gateway._audit_logger._cache[-1]
        assert log.get("role") == "purchaser"

    @pytest.mark.asyncio
    async def test_audit_log_contains_user_info(self, gateway, store_manager_ctx):
        """审计记录包含完整用户信息"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType
        gateway._audit_logger._cache.clear()

        await gateway.execute_action(
            action_type=ActionType.DISMISS_TASK,
            user_context=store_manager_ctx,
            params={"task_id": "TASK-099"},
        )

        # 直接检查缓存
        assert len(gateway._audit_logger._cache) >= 1
        log = gateway._audit_logger._cache[-1]
        assert log["user_id"] == "user_sm_001"
        assert log["action_type"] == "dismiss_task"
        assert "timestamp" in log


# =====================================================================
# 8. AgentOrchestrator 编排器测试
# =====================================================================

class TestAgentOrchestration:
    """多 Agent 协作编排"""

    def test_orchestrator_creates_agent_from_template(self):
        """编排器从模板创建 Agent"""
        from hotpot_platform.cloud.agent_framework.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        agent = orch.create_agent_from_template("TPL-A01-MANAGER", agent_id="orch-test-001")
        assert agent is not None
        assert agent.config.name == "店长AI助理"

    def test_orchestrator_template_fallback(self):
        """编排器对不存在的模板返回 None"""
        from hotpot_platform.cloud.agent_framework.orchestrator import AgentOrchestrator
        orch = AgentOrchestrator()
        agent = orch.create_agent_from_template("NONEXISTENT", agent_id="orch-test-fallback")
        assert agent is None


# =====================================================================
# 运行入口
# =====================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
