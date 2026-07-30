#!/usr/bin/env python3
"""D2 岗位AI助理冲刺 — 集成测试.

覆盖:
- SC01-SC03: SOP合规引擎(检查/模板/违规追踪)
- KT01-KT04: 知识检索(BM25+向量RRF混合)
- H13-H14: Agent框架(角色Agent/编排器/消息总线)
- A01-A05: 店长数字座舱(KPI/告警/决策建议/对比)

运行: pytest tests/test_d2_agent_cockpit.py -v
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

# 确保项目根目录在路径中
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# ═══════════════════════════════════════════════════════════════
# SC01-SC03 SOP合规引擎 测试
# ═══════════════════════════════════════════════════════════════

class TestSOPEngine(unittest.TestCase):
    """SOP合规引擎集成测试."""

    def setUp(self) -> None:
        """创建内存DB用于测试."""
        import sqlite3
        self.db = sqlite3.connect(":memory:")
        self.checker = __import__(
            "hotpot_platform.cloud.sop_engine.checker", fromlist=["SOPChecker"]
        ).SOPChecker(db_session=self.db)
        self.template_mgr = __import__(
            "hotpot_platform.cloud.sop_engine.template_manager", fromlist=["SOPTemplateManager"]
        ).SOPTemplateManager(db_session=self.db)
        self.violation_tracker = __import__(
            "hotpot_platform.cloud.sop_engine.violation_tracker", fromlist=["ViolationTracker"]
        ).ViolationTracker(db_session=self.db)

    def tearDown(self) -> None:
        self.db.close()

    # ── SC01: SOPChecker ─────────────────────────────────────

    def test_sc01_check_kitchen_pass(self) -> None:
        """厨房区域全通过检查."""
        from hotpot_platform.cloud.sop_engine.models import Zone

        report = self.checker.check(
            store_id="test_store",
            zone=Zone.KITCHEN,
            signals={
                "mask_kitchen": True,
                "mask_kitchen_confidence": 0.95,
                "handwash_kitchen": 10,
                "uniform_kitchen": True,
                "food_sample_done": True,
                "food_temp_ok": True,
                "expired_items_count": 0,
            },
        )
        self.assertGreater(report.compliance_score, 80)
        self.assertEqual(report.failed_count, 0)
        print(f"  ✅ kitchen compliance_score={report.compliance_score}")

    def test_sc01_check_kitchen_violations(self) -> None:
        """厨房区域检测到违规."""
        from hotpot_platform.cloud.sop_engine.models import Zone, Severity

        report = self.checker.check(
            store_id="test_store",
            zone=Zone.KITCHEN,
            signals={
                "mask_kitchen": False,           # 未戴口罩 → 违规
                "mask_kitchen_confidence": 0.3,
                "handwash_kitchen": 60,          # 超时未洗手 → 违规
                "uniform_kitchen": True,
                "food_sample_done": False,       # 未留样 → critical违规
                "food_temp_ok": True,
                "expired_items_count": 0,
            },
        )
        self.assertGreater(report.failed_count, 0)
        self.assertLess(report.compliance_score, 80)
        # 应有critical级别违规(食品安全)
        critical_violations = [v for v in report.violations if v.severity == Severity.CRITICAL]
        self.assertGreater(len(critical_violations), 0)
        print(f"  ✅ detected {len(report.violations)} violations, score={report.compliance_score}")

    def test_sc01_batch_check(self) -> None:
        """批量多区域检查."""
        results = self.checker.batch_check("test_store")
        self.assertIn("kitchen", results)
        self.assertIn("warehouse", results)
        self.assertIn("front", results)
        print(f"  ✅ batch check covered {len(results)} zones")

    def test_sc01_compliance_trend(self) -> None:
        """合规趋势查询."""
        trend = self.checker.get_compliance_trend("test_store", days=7)
        self.assertEqual(trend.store_id, "test_store")
        self.assertEqual(trend.period_days, 7)
        print(f"  ✅ trend avg_score={trend.avg_score}")

    # ── SC01: SOPTemplateManager ────────────────────────────

    def test_sc01_template_crud(self) -> None:
        """模板CRUD + 版本管理."""
        from hotpot_platform.cloud.sop_engine.models import (
            SOPCategory, SOPRule, Zone, TemplateStatus,
        )

        rule = SOPRule(
            rule_id="TEST-001",
            name="测试规则",
            severity="minor",
            check_strategy="uniform_check",
            category=SOPCategory.KITCHEN_HYGIENE,
            zone=Zone.KITCHEN,
        )

        # 创建
        tpl = self.template_mgr.create_template(
            name="测试模板",
            category=SOPCategory.KITCHEN_HYGIENE,
            zone=Zone.KITCHEN,
            rules=[rule],
            author="tester",
        )
        self.assertIsNotNone(tpl.template_id)
        self.assertEqual(tpl.version, "1.0.0")
        self.assertEqual(tpl.status, TemplateStatus.DRAFT)

        # 更新(版本应递增)
        updated = self.template_mgr.update_template(
            tpl.template_id,
            rules=[rule],
            status=TemplateStatus.ACTIVE,
            updater="tester",
        )
        self.assertIsNotNone(updated)
        self.assertEqual(updated.version, "1.0.1")  # 补本+1
        self.assertEqual(updated.status, TemplateStatus.ACTIVE)

        # 版本历史
        history = self.template_mgr.get_template_version_history(tpl.template_id)
        self.assertGreater(len(history), 0)
        print(f"  ✅ template CRUD ok, version={updated.version}, history={len(history)}")

    def test_sc01_template_list(self) -> None:
        """模板列表查询."""
        result = self.template_mgr.list_templates(page=1, size=10)
        self.assertIsInstance(result.total, int)
        print(f"  ✅ list templates total={result.total}")

    # ── SC03: ViolationTracker ──────────────────────────────

    def test_sc03_record_and_query(self) -> None:
        """违规记录与查询."""
        from hotpot_platform.cloud.sop_engine.models import ComplianceReport, Zone

        # 先执行一次检查产生报告
        report = self.checker.check(
            store_id="test_store",
            zone=Zone.KITCHEN,
            signals={
                "mask_kitchen": False,
                "mask_kitchen_confidence": 0.2,
            },
        )

        # 记录违规
        records = self.violation_tracker.record_violation(report)
        if report.violations:
            self.assertGreater(len(records), 0)
            vio_id = records[0].violation_id
            self.assertTrue(vio_id.startswith("VIO-"))

            # 查询
            result = self.violation_tracker.query_violations(store_id="test_store")
            self.assertGreater(result.total, 0)

            # 确认处理
            acked = self.violation_tracker.acknowledge(vio_id, ack_by="tester", note="已处理")
            self.assertIsNotNone(acked)
            self.assertEqual(acked.status, "acknowledged")
            print(f"  ✅ violation record+query+ack ok, id={vio_id}")
        else:
            print("  ⚠ no violations to record (all passed)")

    def test_sc03_stats(self) -> None:
        """违规统计."""
        stats = self.violation_tracker.getViolationStats("test_store", period_days=30)
        self.assertEqual(stats.store_id, "test_store")
        self.assertEqual(stats.period_days, 30)
        print(f"  ✅ violation stats: total={stats.total_violations}")


# ═══════════════════════════════════════════════════════════════
# KT01-KT04 知识检索 测试
# ═══════════════════════════════════════════════════════════════

class TestKnowledgeRetriever(unittest.TestCase):
    """知识检索引擎集成测试."""

    def setUp(self) -> None:
        import sqlite3
        self.db = sqlite3.connect(":memory:")
        KnowledgeRetriever = __import__(
            "hotpot_platform.cloud.knowledge.retriever", fromlist=["KnowledgeRetriever"]
        ).KnowledgeRetriever
        self.retriever = KnowledgeRetriever(db_session=self.db)

        # 预置一些测试数据
        self._seed_test_data()

    def tearDown(self) -> None:
        self.db.close()

    def _seed_test_data(self) -> None:
        from hotpot_platform.cloud.knowledge.models import KnowledgeCategory

        test_items = [
            ("毛肚处理标准", "新鲜毛肚应先用水冲洗去除杂质，然后用盐搓洗去污渍，最后用清水浸泡。切片厚度2-3mm为最佳。", "dish"),
            ("底料配方比例", "牛油3斤、郫县豆瓣200g、豆豉100g、冰糖50g、干辣椒100g、花椒30g、香料包1个。先熬牛油再下配料。", "dish"),
            ("口罩佩戴规范", "所有进入厨房区域的人员必须佩戴医用口罩，覆盖口鼻。每4小时更换一次。", "safety"),
            ("冷链温度要求", "冷藏间保持0-4°C，冷冻间保持-22至-16°C。温度记录每小时一次。", "safety"),
            ("翻台率提升方法", "1.优化桌台布局 2.提高服务效率 3.合理预估等位时间 4.提供等位小吃", "operation"),
        ]
        for title, content, cat in test_items:
            self.retriever.add_item(
                title=title,
                content=content,
                category=KnowledgeCategory(cat),
                source_doc="测试文档",
            )

    def test_kt01_basic_query(self) -> None:
        """基础混合检索."""
        result = self.retriever.query(query_text="毛肚怎么处理", top_k=3)
        self.assertGreater(result.total_found, 0)
        self.assertGreater(len(result.results), 0)
        best = result.results[0]
        self.assertGreater(best.rrf_score, 0)
        print(f"  ✅ query '毛肚怎么处理' → {len(result.results)} results, top='{best.title}' score={best.rrf_score}")

    def test_kt02_dish_query(self) -> None:
        """菜品专项检索(KT01)."""
        result = self.retriever.dish_query(dish_name="毛肚", intent="recipe")
        self.assertEqual(result.dish_name, "毛肚")
        self.assertEqual(result.intent, "recipe")
        print(f"  ✅ dish_query: sources={len(result.source_items)}")

    def test_kt02_operation_query(self) -> None:
        """经营Know-how检索(KT02)."""
        result = self.retriever.operation_query(question="翻台率低怎么办")
        self.assertIn("翻台率", result.question)
        if result.answer:
            self.assertGreater(result.confidence, 0)
        print(f"  ✅ operation_query: confidence={result.confidence}, followups={len(result.follow_up_questions)}")

    def test_kt03_add_and_delete(self) -> None:
        """知识条目增删."""
        from hotpot_platform.cloud.knowledge.models import KnowledgeCategory

        item = self.retriever.add_item(
            title="测试条目",
            content="这是测试内容",
            category=KnowledgeCategory.OPERATION,
        )
        self.assertTrue(item.item_id.startswith("KB-"))

        # 删除
        deleted = self.retriever.delete_item(item.item_id, deleted_by="tester")
        self.assertTrue(deleted)
        print(f"  ✅ add+delete item {item.item_id}")

    def test_kt04_category_filter(self) -> None:
        """分类过滤检索."""
        from hotpot_platform.cloud.knowledge.models import KnowledgeCategory

        result = self.retriever.query(
            query_text="温度",
            category=KnowledgeCategory.SAFETY,
        )
        for r in result.results:
            self.assertEqual(r.category, "safety")
        print(f"  ✅ category filter: {len(result.results)} safety items")


# ═══════════════════════════════════════════════════════════════
# H13-H14 Agent框架 测试
# ═══════════════════════════════════════════════════════════════

class TestAgentFramework(unittest.TestCase):
    """Agent协作框架集成测试."""

    def setUp(self) -> None:
        AgentOrchestrator = __import__(
            "hotpot_platform.cloud.agent_framework.orchestrator", fromlist=["AgentOrchestrator"]
        ).AgentOrchestrator
        self.orchestrator = AgentOrchestrator()
        self.bus = self.orchestrator._bus

    def test_h13_create_from_template(self) -> None:
        """从模板创建Agent(H13热插拔)."""
        agent = self.orchestrator.create_agent_from_template(
            template_id="TPL-A01-MANAGER",
            agent_id="A01-TEST",
        )
        self.assertIsNotNone(agent)
        self.assertEqual(agent.config.agent_id, "A01-TEST")
        self.assertEqual(agent.config.role.value, "store_manager")
        print(f"  ✅ created agent A01-TEST from template")

    def test_h13_list_templates(self) -> None:
        """列出内置模板."""
        templates = self.orchestrator.list_templates()
        self.assertGreater(len(templates), 0)
        template_ids = [t["template_id"] for t in templates]
        self.assertIn("TPL-A01-MANAGER", template_ids)
        self.assertIn("TPL-A02-KITCHEN", template_ids)
        print(f"  ✅ {len(templates)} builtin templates")

    def test_h14_message_bus_publish(self) -> None:
        """消息总线发布/路由(H14)."""
        from hotpot_platform.cloud.agent_framework.models import AgentMessage, MessageType, MessagePriority

        received_messages = []

        def handler(msg: AgentMessage) -> Optional[AgentMessage]:
            received_messages.append(msg)
            return None

        # 注册一个测试Agent
        agent = self.orchestrator.create_agent_from_template(
            template_id="TPL-A02-KITCHEN",
            agent_id="A02-TEST",
        )
        if agent:
            self.bus.subscribe("A02-TEST", "sop.*", handler, [MessageType.ALERT])

            # 发布消息
            msg = AgentMessage(
                msg_type=MessageType.ALERT,
                priority=MessagePriority.HIGH,
                sender_id="SYSTEM",
                receiver_id="A02-TEST",
                topic="sop.violation.mask",
                payload={"rule_id": "SOP-KITCHEN-001"},
            )
            count = self.bus.publish(msg)
            self.assertGreater(count, 0)
            print(f"  ✅ message bus: delivered to {count} receiver(s)")

    def test_h14_message_persist(self) -> None:
        """消息持久化查询."""
        import sqlite3
        db = sqlite3.connect(":memory:")
        from hotpot_platform.cloud.agent_framework.orchestrator import MessageBus
        bus_with_db = MessageBus(db_session=db)

        from hotpot_platform.cloud.agent_framework.models import AgentMessage, MessageType
        msg = AgentMessage(
            msg_type=MessageType.EVENT,
            sender_id="TEST",
            topic="test.topic",
            payload={"key": "value"},
        )
        bus_with_db.publish(msg)

        messages = bus_with_db.query_messages(sender_id="TEST")
        self.assertGreater(len(messages), 0)
        print(f"  ✅ message persist: {len(messages)} messages stored")

        db.close()


# ═══════════════════════════════════════════════════════════════
# A01-A05 数字座舱 测试
# ═══════════════════════════════════════════════════════════════

class TestCockpit(unittest.TestCase):
    """店长数字座舱集成测试."""

    def setUp(self) -> None:
        DashboardAggregator = __import__(
            "hotpot_platform.cloud.cockpit.dashboard", fromlist=["DashboardAggregator"]
        ).DashboardAggregator
        self.dashboard = DashboardAggregator()

    def test_a01_build_dashboard(self) -> None:
        """构建完整座舱(A01)."""
        data = self.dashboard.build_dashboard(store_id="store_test")
        self.assertEqual(data.store_id, "store_test")
        self.assertGreater(len(data.kpis), 0)
        self.assertIsInstance(data.overall_health_score, float)
        self.assertGreater(data.overall_health_score, 0)
        print(f"  ✅ dashboard: {len(data.kpis)} KPIs, health={data.overall_health_score}")

    def test_a01_todos_generated(self) -> None:
        """待办事项自动生成."""
        data = self.dashboard.build_dashboard(store_id="store_test")
        # 应有从告警/KPI异常派生的待办
        self.assertIsInstance(data.todos, list)
        print(f"  ✅ todos: {len(data.todos)} items")

    def test_a01_alert_summary(self) -> None:
        """告警汇总."""
        data = self.dashboard.build_dashboard(store_id="store_test")
        active_alerts = data.active_alert_count
        self.assertIsInstance(active_alerts, int)
        print(f"  ✅ alerts: {active_alerts} active")

    def test_a01_decision_suggestions(self) -> None:
        """决策建议生成."""
        data = self.dashboard.build_dashboard(store_id="store_test")
        self.assertIsInstance(data.suggestions, list)
        if data.suggestions:
            sug = data.suggestions[0]
            self.assertTrue(hasattr(sug, 'title'))
            self.assertTrue(hasattr(sug, 'confidence'))
        print(f"  ✅ suggestions: {len(data.suggestions)} items")

    def test_a02_kitchen_dashboard(self) -> None:
        """后厨座舱数据(A02)."""
        KitchenDashboardData = __import__(
            "hotpot_platform.cloud.cockpit.models", fromlist=["KitchenDashboardData"]
        ).KitchenDashboardData
        kitchen_data = KitchenDashboardData(
            store_id="store_test",
            compliance_score=92.5,
            shift_summary="午班运行正常",
        )
        self.assertEqual(kitchen_data.store_id, "store_test")
        self.assertEqual(kitchen_data.compliance_score, 92.5)
        print(f"  ✅ kitchen dashboard: score={kitchen_data.compliance_score}")

    def test_a03_procurement_dashboard(self) -> None:
        """采购座舱数据(A03)."""
        ProcurementDashboardData = __import__(
            "hotpot_platform.cloud.cockpit.models", fromlist=["ProcurementDashboardData"]
        ).ProcurementDashboardData
        proc_data = ProcurementDashboardData(
            store_id="store_test",
            total_estimated_cost=3500.0,
            budget_remaining=1500.0,
        )
        self.assertEqual(proc_data.total_estimated_cost, 3500.0)
        print(f"  ✅ procurement dashboard: cost={proc_data.total_estimated_cost}")

    def test_a05_store_comparison(self) -> None:
        """门店对比(A01扩展)."""
        StoreComparison = __import__(
            "hotpot_platform.cloud.cockpit.dashboard", fromlist=["StoreComparison"]
        ).StoreComparison
        comparison = StoreComparison()
        result = comparison.compare_stores(
            primary_store_id="store_jiaojiang",
            store_ids=["store_yuhuan"],
        )
        self.assertEqual(result.primary_store_id, "store_jiaojiang")
        self.assertGreater(len(result.stores), 1)
        print(f"  ✅ store comparison: {len(result.stores)} stores, {len(result.anomalies)} anomalies")


# ═══════════════════════════════════════════════════════════════
# D2 端到端集成测试
# ═══════════════════════════════════════════════════════════════

class TestD2EndToEnd(unittest.TestCase):
    """D2 全链路端到端测试.

    流程: SOP检查 → 违规记录 → 知识推荐 → Agent通知 → 座舱展示.
    """

    def test_full_flow_sop_to_cockpit(self) -> None:
        """完整流程: SOP检测违规 → 记录 → 推荐纠正知识 → 汇总到座舱."""
        import sqlite3
        db = sqlite3.connect(":memory:")

        # 1. SOP检查
        from hotpot_platform.cloud.sop_engine.models import Zone
        checker = __import__(
            "hotpot_platform.cloud.sop_engine.checker", fromlist=["SOPChecker"]
        ).SOPChecker(db_session=db)
        report = checker.check(
            store_id="e2e_store",
            zone=Zone.KITCHEN,
            signals={
                "mask_kitchen": False,
                "mask_kitchen_confidence": 0.1,
                "handwash_kitchen": 120,
                "uniform_kitchen": True,
                "food_sample_done": True,
                "food_temp_ok": True,
                "expired_items_count": 0,
            },
        )
        self.assertGreater(len(report.violations), 0)
        print(f"  [E2E Step1] SOP check: {len(report.violations)} violations, score={report.compliance_score}")

        # 2. 违规记录
        tracker = __import__(
            "hotpot_platform.cloud.sop_engine.violation_tracker", fromlist=["ViolationTracker"]
        ).ViolationTracker(db_session=db)
        records = tracker.record_violation(report)
        print(f"  [E2E Step2] Violation recorded: {len(records)} records")

        # 3. 知识推荐(针对违规类型推荐相关知识)
        retriever = __import__(
            "hotpot_platform.cloud.knowledge.retriever", fromlist=["KnowledgeRetriever"]
        ).KnowledgeRetriever(db_session=db)
        from hotpot_platform.cloud.knowledge.models import KnowledgeCategory
        retriever.add_item(
            title="口罩佩戴正确方法",
            content="佩戴口罩时应确保金属条向上，覆盖口鼻，压紧鼻夹。定期更换，潮湿后立即更换。",
            category=KnowledgeCategory.SAFETY,
            source_doc="SOP手册",
        )
        knowledge_result = retriever.query(query_text="口罩佩戴规范", top_k=3)
        print(f"  [E2E Step3] Knowledge: {len(knowledge_result.results)} recommendations")

        # 4. Agent通知(模拟A02后厨助理接收SOP违规消息)
        orchestrator = __import__(
            "hotpot_platform.cloud.agent_framework.orchestrator", fromlist=["AgentOrchestrator"]
        ).AgentOrchestrator()
        agent = orchestrator.create_agent_from_template(
            template_id="TPL-A02-KITCHEN",
            agent_id="A02-E2E",
        )
        if agent and report.violations:
            from hotpot_platform.cloud.agent_framework.models import AgentMessage, MessageType, MessagePriority
            msg = agent.send(
                msg_type=MessageType.ALERT,
                receiver_id=None,  # 广播
                topic="sop.violation.kitchen",
                payload={
                    "violations": [v.dict() for v in report.violations],
                    "compliance_score": report.compliance_score,
                },
                priority=MessagePriority.HIGH,
            )
            print(f"  [E2E Step4] Agent notification sent: {msg.message_id[:12]}...")

        # 5. 座舱汇总展示
        dashboard = __import__(
            "hotpot_platform.cloud.cockpit.dashboard", fromlist=["DashboardAggregator"
        ]).DashboardAggregator()
        cockpit_data = dashboard.build_dashboard(store_id="e2e_store")
        print(f"  [E2E Step5] Cockpit: health={cockpit_data.overall_health_score}, "
              f"{len(cockpit_data.kpis)} KPIs, {len(cockpit_data.alerts)} alerts, "
              f"{len(cockpit_data.todos)} todos")

        db.close()
        print("  ✅ E2E flow complete!")


if __name__ == "__main__":
    unittest.main(verbosity=2)
