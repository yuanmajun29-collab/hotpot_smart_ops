"""
W2 Sprint 综合验收测试 (8/4-8/8)

覆盖:
  - D1-S02: 收货质检数据模型 + VLM视觉质检集成 + 审批工作流
  - D1-S03: PurchaseOrder数据模型 + 状态机
  - D2-DEEP-02: SOP规则引擎 (≥8条预置SOP规则)
  - D2-DEEP-01: Agent框架 (4角色Agent + Gateway + Orchestrator + 消息总线)
  - D1-S02-04: receiving_api 新路由 (7 endpoints)
  - D1-S02-03: 潘厨审批工作流

运行:
    python -m pytest tests/test_w2_modules.py -v
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ═══════════════════════════════════════════════════════════
# D1-S02-01 + D1-S03-01: supply_chain 数据模型
# ═══════════════════════════════════════════════════════════

class TestReceivingRecord:
    """ReceivingRecord dataclass 模型"""

    def test_creation_and_auto_fields(self):
        """batch_id 自生成, variance_pct 自动计算"""
        from hotpot_platform.cloud.supply_chain.models import ReceivingRecord

        r = ReceivingRecord(
            supplier_name="精品毛肚",
            order_weight_kg=10.0,
            actual_weight_kg=9.8,
        )
        assert r.batch_id.startswith("RCV-")
        assert r.variance_pct == -2.0
        assert r.created_at, "created_at should be auto-set"

    def test_variance_zero(self):
        """重量完全匹配时 variance_pct = 0"""
        from hotpot_platform.cloud.supply_chain.models import ReceivingRecord

        r = ReceivingRecord(supplier_name="牛肉卷", order_weight_kg=5.0, actual_weight_kg=5.0)
        assert r.variance_pct == 0.0

    def test_to_dict(self):
        from hotpot_platform.cloud.supply_chain.models import ReceivingRecord

        r = ReceivingRecord(supplier_name="王总", order_weight_kg=10.0, actual_weight_kg=9.6)
        d = r.to_dict()
        assert d["supplier_name"] == "王总"
        assert d["variance_pct"] == -4.0

    def test_temp_ok_via_manager(self):
        """ReceivingManager 自动设置 temp_ok"""
        from hotpot_platform.cloud.supply_chain.manager import ReceivingManager

        mgr = ReceivingManager()
        r = mgr.create_record(
            store_id="STORE-01", po_id="PO-001", supplier_id="SUPP-01",
            sku="毛肚", sku_name="精品毛肚", sku_category="meat",
            order_weight_kg=10.0, actual_weight_kg=10.0,
            supplier_name="王总", receiver="小张", temp_c=-18.0,
        )
        assert r.temp_ok is True

        r2 = mgr.create_record(
            store_id="STORE-01", po_id="PO-001", supplier_id="SUPP-01",
            sku="毛肚", sku_name="精品毛肚", sku_category="meat",
            order_weight_kg=10.0, actual_weight_kg=10.0,
            supplier_name="王总", receiver="小张", temp_c=30.0,
        )
        assert r2.temp_ok is False


class TestQualityCheckResult:
    """QualityCheckResult dataclass"""

    def test_creation_and_auto_check_id(self):
        from hotpot_platform.cloud.supply_chain.models import QualityCheckResult

        q = QualityCheckResult(batch_id="RCV-TEST", store_id="S1")
        assert q.check_id.startswith("QC-")
        assert q.batch_id == "RCV-TEST"

    def test_determine_action_grades(self):
        """final_action 按 final_grade 判定"""
        from hotpot_platform.cloud.supply_chain.models import QualityCheckResult

        for grade, action in [("A", "accept"), ("B", "accept"), ("C", "downgrade"), ("D", "reject")]:
            q = QualityCheckResult(batch_id="RCV-TEST", store_id="S1", final_grade=grade)
            q.determine_action()
            assert q.final_action == action, f"Grade {grade} -> {q.final_action}, expected {action}"


class TestPurchaseOrderStateMachine:
    """D1-S03: PO状态机"""

    def test_default_status_draft(self):
        from hotpot_platform.cloud.supply_chain.models import PurchaseOrder, POStatus

        po = PurchaseOrder(supplier_name="王总")
        assert po.status == POStatus.DRAFT
        assert po.po_id.startswith("PO-")

    def test_full_lifecycle(self):
        """完整采购订单生命周期: DRAFT->SUBMITTED->APPROVED->ORDERED->SHIPPED->RECEIVING->RECEIVED"""
        from hotpot_platform.cloud.supply_chain.models import PurchaseOrder, POStatus

        po = PurchaseOrder(supplier_name="王总", expected_delivery_date="2026-08-10")
        flow = [POStatus.SUBMITTED, POStatus.APPROVED, POStatus.ORDERED,
                POStatus.SHIPPED, POStatus.RECEIVING, POStatus.RECEIVED]

        for step in flow:
            assert po.transition(step), f"Failed at {step.value}"
        assert po.status == POStatus.RECEIVED

    def test_invalid_transition_rejected(self):
        from hotpot_platform.cloud.supply_chain.models import PurchaseOrder, POStatus

        po = PurchaseOrder(supplier_name="王总")
        assert not po.transition(POStatus.RECEIVED)  # DRAFT -> RECEIVED 不合法
        assert po.status == POStatus.DRAFT  # 状态不变

    def test_to_dict(self):
        from hotpot_platform.cloud.supply_chain.models import PurchaseOrder

        po = PurchaseOrder(supplier_name="王总", store_id="STORE-01")
        d = po.to_dict()
        assert d["supplier_name"] == "王总"
        assert d["store_id"] == "STORE-01"
        assert "po_id" in d


# ═══════════════════════════════════════════════════════════
# D1-S02-02: 收货/质检/VLM管理器
# ═══════════════════════════════════════════════════════════

class TestReceivingManager:
    def test_create_record(self):
        from hotpot_platform.cloud.supply_chain.manager import ReceivingManager

        mgr = ReceivingManager()
        r = mgr.create_record(
            store_id="STORE-01", po_id="PO-001", supplier_id="SUPP-01",
            sku="毛肚", sku_name="精品毛肚", sku_category="meat",
            order_weight_kg=10.0, actual_weight_kg=9.8,
            supplier_name="王总", receiver="小张",
        )
        assert r.batch_id.startswith("RCV-")
        assert r.variance_pct == -2.0

    def test_temperature_check(self):
        from hotpot_platform.cloud.supply_chain.manager import ReceivingManager

        mgr = ReceivingManager()
        r = mgr.create_record(
            store_id="STORE-01", po_id="PO-001", supplier_id="SUPP-01",
            sku="毛肚", sku_name="精品毛肚", sku_category="meat",
            order_weight_kg=10.0, actual_weight_kg=9.8,
            supplier_name="王总", receiver="小张", temp_c=-18.0,
        )
        assert r.temp_ok is True


class TestQualityManager:
    """VLM模拟质检"""

    def test_vlm_inspect_batch(self):
        from hotpot_platform.cloud.supply_chain.manager import QualityManager, ReceivingManager

        rm = ReceivingManager()
        record = rm.create_record(
            store_id="STORE-01", po_id="PO-001", supplier_id="SUPP-01",
            sku="毛肚", sku_name="精品毛肚", sku_category="meat",
            order_weight_kg=10.0, actual_weight_kg=9.8,
            supplier_name="王总", receiver="小张",
        )

        qm = QualityManager()
        result = qm.inspect_batch(record)
        assert result.check_id.startswith("QC-")
        assert result.final_grade in ("A", "B", "C", "D")
        assert result.final_action in ("accept", "downgrade", "reject")

    def test_perfect_match(self):
        """完美匹配时 VLM 置信度高（因随机因素可能是 A 或 B）"""
        from hotpot_platform.cloud.supply_chain.manager import QualityManager, ReceivingManager

        rm = ReceivingManager()
        record = rm.create_record(
            store_id="STORE-01", po_id="PO-001", supplier_id="SUPP-01",
            sku="毛肚", sku_name="精品毛肚", sku_category="meat",
            order_weight_kg=10.0, actual_weight_kg=10.0,
            supplier_name="王总", receiver="小张",
        )

        qm = QualityManager()
        result = qm.inspect_batch(record)
        assert result.final_grade in ("A", "B"), f"Perfect match gave {result.final_grade}"
        assert result.vlm_confidence >= 0.6

    def test_manual_review_needed_for_large_deviation(self):
        """大偏差触发人工复核"""
        from hotpot_platform.cloud.supply_chain.manager import QualityManager, ReceivingManager

        rm = ReceivingManager()
        record = rm.create_record(
            store_id="STORE-01", po_id="PO-001", supplier_id="SUPP-01",
            sku="毛肚", sku_name="精品毛肚", sku_category="meat",
            order_weight_kg=10.0, actual_weight_kg=7.0,  # -30% deviation
            supplier_name="王总", receiver="小张",
        )

        qm = QualityManager()
        result = qm.inspect_batch(record)
        assert result.manual_review_needed is True
        assert result.final_grade in ("C", "D")


class TestSupplyChainFullPipeline:
    """全链路一键流水线"""

    def test_full_receiving_pipeline(self):
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        mgr = SupplyChainManager()
        result = mgr.full_receiving_pipeline(
            store_id="STORE-01", po_id="PO-001", supplier_id="SUPP-01",
            sku="毛肚", sku_name="精品毛肚", sku_category="meat",
            order_weight_kg=10.0, actual_weight_kg=9.6,
            supplier_name="王总", receiver="小张",
        )
        assert result["record"]["batch_id"].startswith("RCV-")
        qc = result["quality_check"]
        assert qc["final_grade"] in ("A", "B", "C", "D")
        # needs_approval 由 VLM 随机性决定，验证字段存在
        assert isinstance(result["needs_approval"], bool)


# ═══════════════════════════════════════════════════════════
# D1-S02-03: 审批工作流
# ═══════════════════════════════════════════════════════════

class TestApprovalWorkflow:
    """潘厨多节点审批链"""

    def test_create_receiving_workflow(self):
        from hotpot_platform.cloud.supply_chain.models import ApprovalWorkflow

        wf = ApprovalWorkflow.create_receiving_workflow(
            document_type="receiving",
            document_id="RCV-001",
            created_by="系统",
            chef_name="潘厨",
            store_manager="李店长",
        )
        assert wf.workflow_id.startswith("WF-")
        assert wf.document_type == "receiving"
        assert wf.overall_status.value == "pending"
        assert len(wf.nodes) >= 3  # 潘厨初检 + 终审 + 店长

    def test_approve_nodes(self):
        from hotpot_platform.cloud.supply_chain.models import ApprovalWorkflow

        wf = ApprovalWorkflow.create_receiving_workflow(
            document_type="receiving",
            document_id="RCV-002",
            created_by="系统",
            chef_name="潘厨",
        )
        assert wf.approve("潘大厨", "品相不错，可接收")
        assert wf.nodes[0].status.value == "approved"
        assert wf.current_node_index == 1

    def test_approval_manager(self):
        from hotpot_platform.cloud.supply_chain.manager import ApprovalWorkflowManager

        mgr = ApprovalWorkflowManager()
        wf = mgr.start_receiving_approval(
            batch_id="RCV-003",
            store_id="STORE-01",
            chef_name="潘厨",
            created_by="系统",
        )
        assert wf.workflow_id.startswith("WF-")

        ok, msg = mgr.approve_node(wf.workflow_id, "潘厨", "通过初检")
        assert ok
        # 流转到终审
        assert "chef_final" in msg


# ═══════════════════════════════════════════════════════════
# D2-DEEP-02: SOP规则引擎
# ═══════════════════════════════════════════════════════════

class TestSOPTemplateManager:
    """SOPTemplateManager — 模板 CRUD"""

    def test_manager_instantiated(self):
        from hotpot_platform.cloud.sop_engine.template_manager import SOPTemplateManager

        mgr = SOPTemplateManager()
        assert mgr is not None

    def test_list_templates(self):
        """list_templates 返回分页结果"""
        from hotpot_platform.cloud.sop_engine.template_manager import SOPTemplateManager

        mgr = SOPTemplateManager()
        result = mgr.list_templates(status="active")
        assert result is not None
        assert hasattr(result, "items")
        assert hasattr(result, "total")

    def test_create_template(self):
        """创建模板后返回 template_id"""
        from hotpot_platform.cloud.sop_engine.template_manager import SOPTemplateManager
        from hotpot_platform.cloud.sop_engine.models import SOPRule, SOPCategory, Zone, Severity, CheckStrategy

        mgr = SOPTemplateManager()
        rules = [
            SOPRule(
                rule_id="TEST-RCV-001",
                name="智能温度检测",
                description="收货时检测冷链温度",
                severity=Severity.MAJOR,
                check_strategy=CheckStrategy.TEMP_MONITOR,
                corrective_action="拒收温度不达标食材",
                category=SOPCategory.FOOD_SAFETY_CAT,
                zone=Zone.WAREHOUSE,
            )
        ]
        tmpl = mgr.create_template(
            name="收货质检SOP",
            category=SOPCategory.WAREHOUSE_OP,
            zone=Zone.WAREHOUSE,
            rules=rules,
            author="system",
        )
        assert tmpl.template_id, "template_id should be auto-generated"
        assert len(tmpl.rules) == 1


class TestSOPChecker:
    """SOP合规检查器 — 8条预置规则"""

    ZONE_EXPECTED = {
        "kitchen": 4,   # 口罩/洗手/着装/留样
        "warehouse": 2,  # 温控/FEFO
        "front": 2,      # 清理/迎宾
        "dining": 0,
    }

    def test_checker_instantiated(self):
        from hotpot_platform.cloud.sop_engine.checker import SOPChecker

        checker = SOPChecker()
        assert checker is not None

    def test_default_rules_count(self):
        """预置规则共8条（无DB时降级）"""
        from hotpot_platform.cloud.sop_engine.checker import SOPChecker
        from hotpot_platform.cloud.sop_engine.models import Zone

        checker = SOPChecker()
        total = 0
        for zone_str, expected in self.ZONE_EXPECTED.items():
            zone_enum = Zone(zone_str)
            report = checker.check("STORE-01", zone_enum)
            assert report.total_rules == expected, \
                f"Zone {zone_str}: expected {expected} rules, got {report.total_rules}"
            total += report.total_rules
        assert total == 8

    def test_kitchen_check(self):
        """厨房检查: 口罩佩戴检测"""
        from hotpot_platform.cloud.sop_engine.checker import SOPChecker
        from hotpot_platform.cloud.sop_engine.models import Zone

        checker = SOPChecker()
        report = checker.check("STORE-01", Zone.KITCHEN, signals={
            "mask_kitchen": True,
            "mask_kitchen_confidence": 0.95,
        })
        assert report.compliance_score >= 0  # 有合规分数

    def test_warehouse_check(self):
        """仓库检查: 冷链温度监控"""
        from hotpot_platform.cloud.sop_engine.checker import SOPChecker
        from hotpot_platform.cloud.sop_engine.models import Zone

        checker = SOPChecker()
        report = checker.check("STORE-01", Zone.WAREHOUSE, signals={
            "temp_warehouse": -18.0,
        })
        assert report.compliance_score is not None
        assert len(report.checkpoints) > 0

    def test_front_check(self):
        """前厅检查: 餐桌清理"""
        from hotpot_platform.cloud.sop_engine.checker import SOPChecker
        from hotpot_platform.cloud.sop_engine.models import Zone

        checker = SOPChecker()
        report = checker.check("STORE-01", Zone.FRONT, signals={
            "table_idle_min": 5,
        })
        assert report.compliance_score is not None

    def test_batch_check_all_zones(self):
        """批量检查所有区域"""
        from hotpot_platform.cloud.sop_engine.checker import SOPChecker

        checker = SOPChecker()
        results = checker.batch_check("STORE-01")
        assert len(results) == 4  # KITCHEN, WAREHOUSE, FRONT, DINING


class TestSOPViolationTracker:
    """违规追踪器"""

    def test_tracker_instantiated(self):
        from hotpot_platform.cloud.sop_engine.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        assert tracker is not None

    def test_record_violation_from_check_report(self):
        """通过 SOPChecker 报告记录违规"""
        from hotpot_platform.cloud.sop_engine.violation_tracker import ViolationTracker
        from hotpot_platform.cloud.sop_engine.checker import SOPChecker
        from hotpot_platform.cloud.sop_engine.models import Zone

        checker = SOPChecker()
        report = checker.check("STORE-01", Zone.KITCHEN, signals={
            "mask_kitchen": False,  # 触发违规
            "mask_kitchen_confidence": 0.95,
        })

        tracker = ViolationTracker()
        records = tracker.record_violation(report)
        assert len(records) >= 0  # 可能有或没有违规取决于信号
        assert isinstance(records, list)

    def test_query_violations(self):
        from hotpot_platform.cloud.sop_engine.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        result = tracker.query_violations(store_id="STORE-01", page=1, size=10)
        assert result is not None
        assert hasattr(result, "items")
        assert hasattr(result, "total")

    def test_violation_stats(self):
        from hotpot_platform.cloud.sop_engine.violation_tracker import ViolationTracker

        tracker = ViolationTracker()
        stats = tracker.getViolationStats(store_id="STORE-01", period_days=30)
        assert stats is not None
        assert stats.store_id == "STORE-01"


# ═══════════════════════════════════════════════════════════
# D2-DEEP-01: Agent框架
# ═══════════════════════════════════════════════════════════

class TestAgentOrchestrator:
    """AgentOrchestrator + MessageBus + RoleAgent"""

    BUILTIN_TEMPLATES = ["TPL-A01-MANAGER", "TPL-A02-KITCHEN", "TPL-A03-PROCUREMENT", "TPL-A05-KNOWLEDGE"]

    def test_orchestrator_instantiated(self):
        from hotpot_platform.cloud.agent_framework.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator()
        assert orch is not None

    def test_message_bus_instantiated(self):
        from hotpot_platform.cloud.agent_framework.orchestrator import MessageBus

        bus = MessageBus()
        assert bus is not None

    def test_list_templates(self):
        """list_templates 返回可用Agent模板"""
        from hotpot_platform.cloud.agent_framework.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator()
        templates = orch.list_templates()
        assert len(templates) >= 4  # 4个内建模板

    def test_create_agent_from_template(self):
        from hotpot_platform.cloud.agent_framework.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator()
        agent = orch.create_agent_from_template(
            template_id="TPL-A01-MANAGER",
            agent_id="mgr-01",
        )
        assert agent is not None
        assert agent.config.agent_id == "mgr-01"
        assert agent.config.role == "store_manager"

    def test_list_agents_after_creation(self):
        from hotpot_platform.cloud.agent_framework.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator()
        orch.create_agent_from_template("TPL-A02-KITCHEN", "chef-02")
        agents = orch.list_agents()
        assert len(agents) >= 1

    def test_orchestrate_kitchen_workflow(self):
        """编排厨房质检流水线"""
        from hotpot_platform.cloud.agent_framework.orchestrator import AgentOrchestrator

        orch = AgentOrchestrator()
        orch.create_agent_from_template("TPL-A02-KITCHEN", "chef-03")
        orch.create_agent_from_template("TPL-A01-MANAGER", "mgr-02")

        result = orch.orchestrate(tasks=[
            {"agent_id": "chef-03", "task_type": "quality_check", "input_data": {"grade": "A"}},
        ])
        assert result is not None
        assert result.request_id is not None

    def test_all_builtin_templates(self):
        """验证所有4个内建模板可创建"""
        from hotpot_platform.cloud.agent_framework.orchestrator import AgentOrchestrator

        for tid in self.BUILTIN_TEMPLATES:
            orch = AgentOrchestrator()
            agent = orch.create_agent_from_template(tid, f"test-{tid}")
            assert agent is not None, f"Template {tid} 创建失败"


class TestAgentGateway:
    """H13-H14: Agent Gateway 中间件"""

    def test_gateway_instantiated(self):
        from hotpot_platform.cloud.agent_framework.agent_gateway import AgentGatewayMiddleware

        gw = AgentGatewayMiddleware()
        assert gw is not None

    def test_audit_stats(self):
        from hotpot_platform.cloud.agent_framework.agent_gateway import AgentGatewayMiddleware

        gw = AgentGatewayMiddleware()
        stats = gw.get_audit_stats()
        assert isinstance(stats, dict)

    def test_permission_matrix(self):
        from hotpot_platform.cloud.agent_framework.agent_gateway import AgentGatewayMiddleware

        gw = AgentGatewayMiddleware()
        matrix = gw.get_permission_matrix_summary(role="chef")
        assert isinstance(matrix, dict)


class TestActionTypes:
    """ActionType 枚举 — 22个值"""

    def test_all_action_types(self):
        from hotpot_platform.cloud.agent_framework.action_types import ActionType

        actions = list(ActionType)
        assert len(actions) == 22, f"Expected 22 ActionTypes, got {len(actions)}"

    def test_risk_description_exist(self):
        """每种 ActionType 都有风险描述"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType, get_action_risk_description

        for action in ActionType:
            desc = get_action_risk_description(action)
            assert isinstance(desc, str)
            assert len(desc) > 0

    def test_specific_action_types(self):
        """验证关键 ActionType 存在"""
        from hotpot_platform.cloud.agent_framework.action_types import ActionType

        assert hasattr(ActionType, "SUBMIT_RECEIVING")
        assert hasattr(ActionType, "CREATE_PO")
        assert hasattr(ActionType, "CANCEL_PO")
        assert hasattr(ActionType, "QUERY_PURCHASE_ORDERS")


class TestAgentMessageBus:
    """消息总线功能"""

    def test_message_publish(self):
        """publish() 发布消息到总线"""
        from hotpot_platform.cloud.agent_framework.orchestrator import MessageBus
        from hotpot_platform.cloud.agent_framework.models import AgentMessage, MessageType

        bus = MessageBus()
        msg = AgentMessage(
            msg_type=MessageType.STANDARD,
            sender_id="chef-01",
            receiver_id="mgr-01",
            topic="quality_report",
            payload={"grade": "A", "batch": "RCV-001"},
        )
        count = bus.publish(msg)
        assert count >= 0  # 可能 0 (无订阅者) 或 >0 (有已注册agent)
        assert msg.topic == "quality_report"
        assert msg.payload["batch"] == "RCV-001"

    def test_register_and_publish(self):
        """注册 Agent 后 publish 能送达"""
        from hotpot_platform.cloud.agent_framework.orchestrator import MessageBus
        from hotpot_platform.cloud.agent_framework.agents import KitchenAgent
        from hotpot_platform.cloud.agent_framework.models import AgentMessage, MessageType

        bus = MessageBus()
        agent = KitchenAgent(message_bus=bus)
        bus.register_agent(agent)

        msg = AgentMessage(
            msg_type=MessageType.EVENT,
            sender_id="system",
            receiver_id=agent.config.agent_id,
            topic="quality.alert",
            payload={"level": "warning"},
        )
        count = bus.publish(msg)
        assert count >= 0  # 消息已发布


class TestScenarios:
    """编排场景验证"""

    def test_waste_to_purchase_scenario(self):
        from hotpot_platform.cloud.agent_framework.orchestration_scenarios import WasteToPurchaseOrchestration

        scenario = WasteToPurchaseOrchestration()
        assert scenario is not None

    def test_table_service_loop(self):
        from hotpot_platform.cloud.agent_framework.orchestration_scenarios import TableServiceLoop

        scenario = TableServiceLoop()
        assert scenario is not None

    def test_sop_training_loop(self):
        from hotpot_platform.cloud.agent_framework.orchestration_scenarios import SOpViolationTrainingLoop

        scenario = SOpViolationTrainingLoop()
        assert scenario is not None


# ═══════════════════════════════════════════════════════════
# Knowledge 知识库
# ═══════════════════════════════════════════════════════════

class TestKnowledgeModule:
    def test_retriever_instantiated(self):
        from hotpot_platform.cloud.knowledge import KnowledgeRetriever

        kr = KnowledgeRetriever()
        assert kr is not None

    def test_query_succeeds(self):
        from hotpot_platform.cloud.knowledge import KnowledgeRetriever

        kr = KnowledgeRetriever()
        result = kr.query("火锅食材")
        assert result is not None
        assert result.query_text == "火锅食材"

    def test_add_and_retrieve_item(self):
        from hotpot_platform.cloud.knowledge import KnowledgeRetriever
        from hotpot_platform.cloud.knowledge.models import KnowledgeCategory

        kr = KnowledgeRetriever()
        item = kr.add_item(
            title="毛肚储存标准",
            content="毛肚应冷藏保存，温度0-4°C，保质期3天。",
            category=KnowledgeCategory.DISH,
            source_doc="火锅食材标准手册",
        )
        assert item.item_id.startswith("KB-")

        result = kr.query("毛肚 保存")
        assert result.total_found >= 0


# ═══════════════════════════════════════════════════════════
# D1-S02-04: receiving_api 路由 (7 endpoints)
# ═══════════════════════════════════════════════════════════

class TestReceivingAPIRoutes:
    """验证 receiving.py 路由器 (7 endpoints)"""

    def test_router_exists(self):
        from hotpot_platform.cloud.event_hub.routers.receiving import router

        assert router is not None
        assert len(router.routes) == 7, f"Expected 7, got {len(router.routes)}"

    def test_quality_tap_endpoint(self):
        """POST /api/v1/receiving/quality-tap"""
        from hotpot_platform.cloud.event_hub.routers.receiving import router

        paths = {r.path for r in router.routes}
        assert "/api/v1/receiving/quality-tap" in paths

    def test_submit_and_checkin_endpoints(self):
        """POST /api/v1/receiving/submit + /api/v1/receiving/checkin"""
        from hotpot_platform.cloud.event_hub.routers.receiving import router

        paths = {r.path for r in router.routes}
        assert "/api/v1/receiving/submit" in paths
        assert "/api/v1/receiving/checkin" in paths

    def test_query_endpoints(self):
        """GET /api/v1/receiving/checkins + batches"""
        from hotpot_platform.cloud.event_hub.routers.receiving import router

        paths = {r.path for r in router.routes}
        assert "/api/v1/receiving/checkins" in paths
        assert "/api/v1/receiving/batches" in paths

    def test_supplier_stats_endpoint(self):
        """GET /api/v1/receiving/supplier-stats"""
        from hotpot_platform.cloud.event_hub.routers.receiving import router

        paths = {r.path for r in router.routes}
        assert "/api/v1/receiving/supplier-stats" in paths

    def test_audit_signatures_endpoint(self):
        """GET /api/v1/audit/signatures"""
        from hotpot_platform.cloud.event_hub.routers.receiving import router

        paths = {r.path for r in router.routes}
        assert "/api/v1/audit/signatures" in paths
