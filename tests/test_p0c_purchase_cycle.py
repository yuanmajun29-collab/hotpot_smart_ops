#!/usr/bin/env python3
"""
火瞳 · P0-C 采购闭环溯源验证 - 端到端测试
======================================

测试覆盖:
1. ✅ 完整闭环流程 (建议→审批→PO→收货)
2. ✅ correlation_id 全链路一致性
3. ✅ ADR-001 合规性 (无token不能创建PO)
4. ✅ 权限矩阵验证 (角色权限检查)
5. ✅ 异常流程 (审批拒绝/D级品)
6. ✅ 审计事件完整性
7. ✅ 时间线生成正确性

运行方式:
    pytest tests/test_p0c_purchase_cycle.py -v

作者: 火瞳AI团队
日期: 2026-08-03 (P0-C Phase 4)
"""

import pytest
import sys
from datetime import datetime, timedelta

sys.path.insert(0, '.')

from hotpot_platform.cloud.event_hub.routers.purchase_cycle import (
    PurchaseCycle,
    SuggestionData,
    ApprovalTaskData,
    PurchaseOrderData,
    ReceivingRecordData,
    AuditEventData,
    CyclePhase,
    CycleStatus,
    create_purchase_cycle,
)
from hotpot_platform.cloud.agent_framework.action_types import (
    ActionType,
    RiskLevel,
    PermissionMatrix,
    PermissionDeniedError,
)


# =====================================================================
# 测试夹具
# =====================================================================

@pytest.fixture
def user_context():
    """模拟用户上下文"""
    from hotpot_platform.cloud.agent_framework.agent_gateway import UserContext

    return UserContext(
        user_id="test_user_001",
        role="purchaser",
        session_id="session_test",
        ip_address="127.0.0.1",
    )


@pytest.fixture
def cycle(user_context):
    """创建采购闭环实例"""
    return create_purchase_cycle(
        store_id="store_test",
        user_id="test_user_001",
        role="purchaser",
    )


@pytest.fixture
def sample_items():
    """示例采购项"""
    return [
        {"sku_code": "FP-HNRC-001", "name": "汉拿山肥牛卷", "qty": 10, "unit_price": 68.0},
        {"sku_code": "FP-HNRC-002", "name": "精品羊肉卷", "qty": 5, "unit_price": 78.0},
    ]


# =====================================================================
# 测试组1: 数据模型验证
# =====================================================================

class TestDataModels:
    """测试数据模型完整性和默认值"""

    def test_suggestion_data_defaults(self):
        """SuggestionData 应有正确的默认值"""
        suggestion = SuggestionData()
        assert suggestion.suggestion_id.startswith("SUG-")
        assert len(suggestion.correlation_id) == 36  # UUID格式
        assert suggestion.status == "pending"
        assert suggestion.items == []
        assert suggestion.total_amount == 0.0
        assert 0 <= suggestion.confidence_score <= 1

    def test_approval_task_data_defaults(self):
        """ApprovalTaskData 应有正确的默认值"""
        task = ApprovalTaskData()
        assert task.task_id.startswith("APV-")
        assert task.status == "pending"
        assert task.decision is None
        assert task.approval_token is None
        assert task.risk_level == RiskLevel.HIGH

    def test_purchase_order_data_defaults(self):
        """PurchaseOrderData 应有正确的默认值"""
        po = PurchaseOrderData()
        assert po.order_id.startswith("PO-")
        assert po.status == "draft"
        assert po.currency == "CNY"
        assert po.approval_token is None

    def test_receiving_record_data_defaults(self):
        """ReceivingRecordData 应有正确的默认值"""
        receiving = ReceivingRecordData()
        assert receiving.receiving_id.startswith("RCV-")
        assert receiving.status == "pending"
        assert receiving.quality_grade is None
        assert receiving.temperature == 0.0

    def test_audit_event_data_defaults(self):
        """AuditEventData 应有正确的默认值"""
        event = AuditEventData()
        assert event.event_id  # 非空UUID
        assert event.result == "success"
        assert event.approval_required is False


# =====================================================================
# 测试组2: PurchaseCycle 状态机核心流程
# =====================================================================

class TestPurchaseCycleCore:
    """测试采购闭环核心状态机"""

    @pytest.mark.asyncio
    async def test_phase1_generate_suggestion(self, cycle, sample_items):
        """环节1: AI应能成功生成采购建议"""
        result = await cycle.generate_suggestion(
            items=sample_items,
            priority="normal",
            reason="库存低于安全水位",
            confidence_score=0.9,
        )

        assert result["code"] == 201
        assert "suggestion" in result
        assert "correlation_id" in result
        assert cycle.suggestion is not None
        assert cycle.suggestion.total_amount == 1070.0  # 10*68 + 5*78
        assert cycle.current_phase == CyclePhase.SUGGESTION
        assert cycle.status == CycleStatus.IN_PROGRESS
        assert len(cycle._audit_events) == 1  # 应生成1个审计事件

    @pytest.mark.asyncio
    async def test_phase2_create_approval_task(self, cycle, sample_items):
        """环节2: 应能成功创建审批任务"""
        # 先完成环节1
        await cycle.generate_suggestion(items=sample_items)

        # 创建审批任务
        result = await cycle.create_approval_task(
            action_type=ActionType.APPROVE_PURCHASE,
            summary="测试审批",
        )

        assert result["code"] == 201
        assert "task_id" in result
        assert result["status"] == "pending_approval"
        assert cycle.approval_task is not None
        assert cycle.approval_task.correlation_id == cycle.suggestion.correlation_id  # ✅ correlation_id一致！
        assert cycle.current_phase == CyclePhase.APPROVAL
        assert cycle.status == CycleStatus.PENDING_APPROVAL
        assert len(cycle._audit_events) == 2  # 建议+审批

    @pytest.mark.asyncio
    async def test_phase2_make_approval_decision_approve(self, cycle, sample_items):
        """环节2: 审批通过应生成approval_token"""
        await cycle.generate_suggestion(items=sample_items)
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)

        # 审批通过
        result = await cycle.make_approval_decision(
            decision="approve",
            decision_notes="同意采购",
            approver_user_id="approver_001",
        )

        assert result["decision"] == "approve"
        assert "approval_token" in result
        assert result["approval_token"] is not None  # ✅ 必须有token
        assert cycle.approval_task.decision == "approve"
        assert cycle.approval_task.approval_token is not None
        assert cycle.status == CycleStatus.APPROVED

    @pytest.mark.asyncio
    async def test_phase2_make_approval_decision_reject(self, cycle, sample_items):
        """环节2: 审批拒绝不应生成approval_token"""
        await cycle.generate_suggestion(items=sample_items)
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)

        # 审批拒绝
        result = await cycle.make_approval_decision(
            decision="reject",
            decision_notes="不需要",
            approver_user_id="approver_001",
        )

        assert result["decision"] == "reject"
        assert result.get("approval_token") is None  # ❌ 拒绝时无token
        assert cycle.status == CycleStatus.REJECTED

    @pytest.mark.asyncio
    async def test_phase3_execute_purchase_order_with_token(self, cycle, sample_items):
        """环节3: 有approval_token时应能成功创建PO"""
        # 完成前序环节
        await cycle.generate_suggestion(items=sample_items)
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)
        approval_result = await cycle.make_approval_decision(decision="approve", approver_user_id="approver_001")

        # 使用token创建PO
        result = await cycle.execute_purchase_order(
            supplier_id="SUPPLIER-001",
            supplier_name="测试供应商",
            items=sample_items,
            expected_delivery_date=(datetime.now() + timedelta(days=3)).isoformat(),
            approval_token=approval_result["approval_token"],
        )

        assert result["code"] == 201
        assert "order_id" in result
        assert result["status"] == "approved"
        assert cycle.purchase_order is not None
        assert cycle.purchase_order.correlation_id == cycle.suggestion.correlation_id  # ✅ 一致
        assert cycle.purchase_order.supplier_name == "测试供应商"
        assert cycle.current_phase == CyclePhase.PURCHASE_ORDER
        assert cycle.status == CycleStatus.EXECUTED

    @pytest.mark.asyncio
    async def test_phase3_execute_po_without_token_should_fail(self, cycle, sample_items):
        """环节3: 无approval_token时应抛出异常 (ADR-001合规)"""
        await cycle.generate_suggestion(items=sample_items)

        with pytest.raises(ValueError, match="必须先完成审批环节"):
            await cycle.execute_purchase_order(
                supplier_id="SUPPLIER-001",
                supplier_name="测试供应商",
                items=sample_items,
                expected_delivery_date=datetime.now().isoformat(),
                approval_token="invalid-token",
            )

    @pytest.mark.asyncio
    async def test_phase3_execute_po_with_invalid_token_should_fail(self, cycle, sample_items):
        """环节3: 无效token应抛出异常"""
        await cycle.generate_suggestion(items=sample_items)
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)
        # 不做审批决策，直接尝试用假token创建PO

        with pytest.raises(ValueError, match="必须先完成审批环节"):
            await cycle.execute_purchase_order(
                supplier_id="SUPPLIER-001",
                supplier_name="测试供应商",
                items=sample_items,
                expected_delivery_date=datetime.now().isoformat(),
                approval_token="fake-token-12345",
            )

    @pytest.mark.asyncio
    async def test_phase4_confirm_receiving_normal(self, cycle, sample_items):
        """环节4: 正常收货(A级)应直接完成闭环"""
        # 完成前序环节
        await cycle.generate_suggestion(items=sample_items)
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)
        approval_result = await cycle.make_approval_decision(decision="approve", approver_user_id="approver_001")
        await cycle.execute_purchase_order(
            supplier_id="SUPPLIER-001",
            supplier_name="测试供应商",
            items=sample_items,
            expected_delivery_date=datetime.now().isoformat(),
            approval_token=approval_result["approval_token"],
        )

        # 收货确认 (A级，正常温度)
        result = await cycle.confirm_receiving(
            items=[
                {"product_id": "FP-HNRC-001", "name": "汉拿山肥牛卷", "qty_received": 10, "qty_expected": 10},
            ],
            temperature=-18.5,  # ✅ 正常
            weight_actual=10.0,
            quality_grade="A",  # ✅ A级
            inspector_id="inspector_panchu",
            inspector_name="潘厨",
        )

        assert result["code"] == 201
        assert result["receiving_id"].startswith("RCV-")
        assert result["quality_check"]["temperature"]["ok"] is True
        assert result["quality_check"]["grade"] == "A"
        assert result["status"] == "approved"  # A级无需二次审批
        assert result["_meta"]["cycle_completed"] is True  # ✅ 闭环完成！
        assert cycle.status == CycleStatus.COMPLETED

    @pytest.mark.asyncio
    async def test_phase4_confirm_receiving_d_grade_requires_approval(self, cycle, sample_items):
        """环节4: D级品应需要店长二次审批"""
        # 完成前序环节
        await cycle.generate_suggestion(items=sample_items)
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)
        approval_result = await cycle.make_approval_decision(decision="approve", approver_user_id="approver_001")
        await cycle.execute_purchase_order(
            supplier_id="SUPPLIER-001",
            supplier_name="测试供应商",
            items=sample_items,
            expected_delivery_date=datetime.now().isoformat(),
            approval_token=approval_result["approval_token"],
        )

        # D级收货
        result = await cycle.confirm_receiving(
            items=[{"product_id": "FP-HNRC-001", "name": "汉拿山肥牛卷", "qty_received": 10, "qty_expected": 10}],
            temperature=-8.5,  # ⚠️ 温度异常
            weight_actual=9.0,  # ⚠️ 重量不足
            quality_grade="D",  # ⚠️ D级
            inspector_id="inspector_panchu",
            inspector_name="潘厨",
        )

        assert result["status"] == "pending_approval"  # ⚠️ 需要二次审批
        assert result["_meta"]["cycle_completed"] is False  # 尚未完成
        assert result["next_step"].find("审批") != -1

        # 店长二次审批
        approve_result = await cycle.approve_receiving(
            approver_user_id="store_manager_001",
            approver_notes="同意退换货处理",
        )

        assert approve_result["cycle_completed"] is True  # ✅ 现在完成了
        assert cycle.status == CycleStatus.COMPLETED


# =====================================================================
# 测试组3: correlation_id 全链路一致性
# =====================================================================

class TestCorrelationIdConsistency:
    """测试correlation_id在全链路中的一致性"""

    @pytest.mark.asyncio
    async def test_correlation_id_consistency_across_all_phases(self, cycle, sample_items):
        """correlation_id应在所有环节中保持一致"""
        # 环节1
        result1 = await cycle.generate_suggestion(items=sample_items)
        corr_id = result1["correlation_id"]

        # 环节2
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)
        assert cycle.approval_task.correlation_id == corr_id

        # 审批
        await cycle.make_approval_decision(decision="approve", approver_user_id="app_001")

        # 环节3
        await cycle.execute_purchase_order(
            supplier_id="SUP-001", supplier_name="S", items=sample_items,
            expected_delivery_date=datetime.now().isoformat(),
            approval_token=cycle.approval_task.approval_token,
        )
        assert cycle.purchase_order.correlation_id == corr_id

        # 环节4
        await cycle.confirm_receiving(
            items=[], temperature=-18.0, weight_actual=10.0, quality_grade="A",
        )
        assert cycle.receiving_record.correlation_id == corr_id

        # 全链路查询
        trace = await cycle.get_full_trace()
        assert trace["trace"]["correlation_id"] == corr_id

    @pytest.mark.asyncio
    async def test_correlation_id_in_audit_events(self, cycle, sample_items):
        """每个审计事件都应包含相同的correlation_id"""
        await cycle.generate_suggestion(items=sample_items)
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)
        await cycle.make_approval_decision(decision="approve", approver_user_id="app_001")

        corr_id = cycle.suggestion.correlation_id

        for event in cycle._audit_events:
            assert event.correlation_id == corr_id, f"审计事件correlation_id不一致: {event.event_id}"


# =====================================================================
# 测试组4: ADR-001 合规性验证
# =====================================================================

class TestADR001Compliance:
    """验证ADR-001: 'AI不自动创建正式PO' 的合规性"""

    @pytest.mark.asyncio
    async def test_no_auto_po_creation(self, cycle, sample_items):
        """即使调用generate_suggestion，也不应自动创建PO"""
        await cycle.generate_suggestion(items=sample_items)

        assert cycle.purchase_order is None  # ❌ 没有PO被创建
        assert cycle.status != CycleStatus.EXECUTED

    @pytest.mark.asyncio
    async def test_po_creation_requires_human_approval(self, cycle, sample_items):
        """PO创建必须有approval_token（人工审批证明）"""
        await cycle.generate_suggestion(items=sample_items)
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)
        # 故意不做make_approval_decision

        with pytest.raises(Exception):  # 应该失败
            await cycle.execute_purchase_order(
                supplier_id="SUP-001", supplier_name="S", items=sample_items,
                expected_delivery_date=datetime.now().isoformat(),
                approval_token=None,  # ❌ 无token
            )

    @pytest.mark.asyncio
    async def test_adr_compliant_flag_in_response(self, cycle, sample_items):
        """响应中应包含adr_compliant标志"""
        result = await cycle.generate_suggestion(items=sample_items)
        assert result["_meta"]["adr_compliant"] is True

        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)
        # 第二次获取结果（从cycle对象重新构建）


# =====================================================================
# 测试组5: 权限矩阵集成
# =====================================================================

class TestPermissionMatrixIntegration:
    """测试与PermissionMatrix的集成"""

    def test_store_manager_cannot_create_po_directly(self):
        """店长不应有直接创建PO的权限"""
        rule = PermissionMatrix.check("store_manager", ActionType.CREATE_PO)
        assert rule.risk_level == RiskLevel.BLOCKED

    def test_purchaser_can_create_po_with_approval(self):
        """采购员可以创建PO但需要审批"""
        rule = PermissionMatrix.check("purchaser", ActionType.CREATE_PO)
        assert rule.risk_level == RiskLevel.HIGH
        assert rule.requires_approval is True

    def test_kitchen_staff_blocked_from_po_operations(self):
        """后厨人员不应有任何PO相关权限"""
        for action in [ActionType.CREATE_PO, ActionType.APPROVE_PURCHASE]:
            rule = PermissionMatrix.check("kitchen_staff", action)
            assert rule.risk_level == RiskLevel.BLOCKED


# =====================================================================
# 测试组6: 全链路追踪查询
# =====================================================================

class TestFullTraceQuery:
    """测试全链路追踪查询功能"""

    @pytest.mark.asyncio
    async def test_trace_returns_all_phases(self, cycle, sample_items):
        """全链路查询应返回所有已完成环节的数据"""
        # 执行完整流程
        await cycle.generate_suggestion(items=sample_items)
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)
        await cycle.make_approval_decision(decision="approve", approver_user_id="app_001")
        await cycle.execute_purchase_order(
            supplier_id="SUP-001", supplier_name="S", items=sample_items,
            expected_delivery_date=datetime.now().isoformat(),
            approval_token=cycle.approval_task.approval_token,
        )
        await cycle.confirm_receiving(
            items=[], temperature=-18.0, weight_actual=10.0, quality_grade="A",
        )

        # 查询追踪
        trace_result = await cycle.get_full_trace()
        trace = trace_result["trace"]

        assert trace["correlation_id"] == cycle.suggestion.correlation_id
        assert trace["status"] == CycleStatus.COMPLETED.value
        assert trace["phases"][CyclePhase.SUGGESTION.value] is not None
        assert trace["phases"][CyclePhase.APPROVAL.value] is not None
        assert trace["phases"][CyclePhase.PURCHASE_ORDER.value] is not None
        assert trace["phases"][CyclePhase.RECEIVING.value] is not None
        assert len(trace["timeline"]) >= 4  # 至少4个时间线节点
        assert trace["statistics"]["adr_compliant"] is True
        assert trace["statistics"]["completed_phases"] == 4

    @pytest.mark.asyncio
    async def test_trace_timeline_sorted_by_time(self, cycle, sample_items):
        """时间线应按时间排序"""
        await cycle.generate_suggestion(items=sample_items)
        await cycle.create_approval_task(action_type=ActionType.APPROVE_PURCHASE)
        await cycle.make_approval_decision(decision="approve", approver_user_id="app_001")

        trace_result = await cycle.get_full_trace()
        timeline = trace_result["trace"]["timeline"]

        if len(timeline) >= 2:
            for i in range(len(timeline) - 1):
                assert timeline[i]["timestamp"] <= timeline[i+1]["timestamp"], "时间线未排序"


# =====================================================================
# 运行入口
# =====================================================================

if __name__ == "__main__":
    # 直接运行时执行pytest
    import subprocess
    result = subprocess.run(
        ["python3", "-m", "pytest", __file__, "-v", "--tb=short"],
        cwd=".",
    )
    sys.exit(result.returncode)
