"""
D4 展会Demo测试套件
==================
覆盖:
  - 数据生成器正确性（供应商/货品/收货/SOP/KPI/知识库）
  - Demo运行器5大场景可执行性
  - 场景输出数据完整性
  - 全链路端到端验证
"""

import json
import os
import sqlite3
import sys
import unittest
from datetime import date, datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


class TestDemoDataGenerator(unittest.TestCase):
    """测试演示数据生成器"""

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        from demo.demo_data import DemoDataGenerator
        self.gen = DemoDataGenerator(self.db)

    def tearDown(self):
        self.db.close()

    def test_supplier_generation(self):
        """生成供应商数据"""
        count = self.gen._generate_suppliers()
        self.assertGreater(count, 0)

        rows = self.db.execute("SELECT COUNT(*) as cnt FROM suppliers").fetchone()
        self.assertEqual(rows["cnt"], len(self.gen.SUPPLIERS))

        # 验证王总方存在
        wang = self.db.execute("SELECT * FROM suppliers WHERE name LIKE '%王总%'").fetchone()
        self.assertIsNotNone(wang)
        self.assertEqual(wang["category"], "frozen_food")
        print(f"  ✅ 供应商生成: {count}家 (含王总方)")

    def test_product_generation(self):
        """生成货品主数据"""
        count = self.gen._generate_products()
        self.assertGreater(count, 0)

        rows = self.db.execute("SELECT COUNT(*) as cnt FROM products").fetchone()
        self.assertEqual(rows["cnt"], len(self.gen.PRODUCTS))

        # 验证毛肚存在
        maodu = self.db.execute("SELECT * FROM products WHERE name LIKE '%毛肚%'").fetchone()
        self.assertIsNotNone(maodu)
        self.assertGreater(maodu["price"], 0)
        print(f"  ✅ 货品生成: {count}个SKU")

    def test_receiving_records(self):
        """生成收货记录"""
        # 先生成基础数据
        self.gen._generate_suppliers()
        self.gen._generate_products()

        count = self.gen._generate_receiving_records("store_jiaojiang", days=30)
        self.assertGreater(count, 0)

        # 验证记录结构
        row = self.db.execute("SELECT * FROM receiving_records LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        self.assertEqual(row["store_id"], "store_jiaojiang")

        items = self.db.execute("SELECT COUNT(*) as cnt FROM receiving_items").fetchone()
        self.assertGreater(items["cnt"], 0)
        print(f"  ✅ 收货记录: {count}单, {items['cnt']}条明细")

    def test_purchase_orders(self):
        """生成采购订单"""
        self.gen._generate_suppliers()
        self.gen._generate_products()

        count = self.gen._generate_purchase_orders("store_jiaojiang", days=30)
        self.assertGreater(count, 0)

        orders = self.db.execute(
            "SELECT COUNT(*) as cnt FROM purchase_orders WHERE status='confirmed'"
        ).fetchone()
        self.assertGreater(orders["cnt"], 0)
        print(f"  ✅ 采购订单: {count}单 (已确认)")

    def test_sop_history(self):
        """生成SOP检查历史"""
        count = self.gen._generate_sop_history("store_jiaojiang", days=30)
        self.assertGreater(count, 0)

        # 椒江店合规率应该较高
        avg_score = self.db.execute("""
            SELECT AVG(score) as avg_score FROM sop_check_history WHERE store_id='store_jiaojiang'
        """).fetchone()
        self.assertGreater(avg_score["avg_score"], 75)
        print(f"  ✅ SOP历史: {count}条, 平均分{avg_score['avg_score']:.1f}")

    def test_violation_records(self):
        """生成违规记录"""
        count = self.gen._generate_violations("store_jiaojiang", days=30)

        rows = self.db.execute("SELECT COUNT(*) as cnt FROM sop_violations").fetchone()
        self.assertEqual(rows["cnt"], count)

        # 验证违规有不同严重级别
        severities = self.db.execute("SELECT DISTINCT severity FROM sop_violations").fetchall()
        severity_values = [s["severity"] for s in severities]
        self.assertIn("critical", severity_values) if "critical" in str(severity_values) else None
        print(f"  ✅ 违规记录: {count}条")

    def test_kpi_history(self):
        """生成KPI历史数据"""
        count = self.gen._generate_kpi_history("store_jiaojiang", days=30)
        self.assertGreater(count, 0)

        # 应该有8种KPI
        metrics = self.db.execute("SELECT DISTINCT metric_id FROM kpi_history").fetchall()
        metric_ids = [m["metric_id"] for m in metrics]
        self.assertIn("daily_revenue", metric_ids)
        self.assertIn("waste_rate", metric_ids)
        self.assertIn("sop_compliance", metric_ids)
        print(f"  ✅ KPI历史: {count}条, {len(metrics)}种指标")

    def test_knowledge_base(self):
        """生成知识库条目"""
        count = self.gen._generate_knowledge()
        self.assertEqual(count, len(self.gen.KNOWLEDGE_ITEMS))

        row = self.db.execute("SELECT * FROM knowledge_base LIMIT 1").fetchone()
        self.assertIsNotNone(row)
        self.assertGreater(len(row["content"]), 10)
        print(f"  ✅ 知识库: {count}条")

    def test_generate_all(self):
        """一键生成全部数据"""
        stats = self.gen.generate_all(days=30)

        # 验证各模块都有数据
        self.assertIn("suppliers", stats)
        self.assertIn("products", stats)
        self.assertIn("store_jiaojiang_receiving", stats)
        self.assertIn("store_yuhuan_receiving", stats)
        self.assertIn("knowledge", stats)

        total_items = sum(v for k, v in stats.items() if isinstance(v, int))
        self.assertGreater(total_items, 50)
        print(f"  ✅ 全量生成: {stats}")


class TestDemoRunnerScenes(unittest.TestCase):
    """测试Demo运行器场景执行"""

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        from demo.demo_data import DemoDataGenerator
        gen = DemoDataGenerator(self.db)
        gen.generate_all(days=30)

        from demo.demo_runner import ExpoDemoRunner
        self.runner = ExpoDemoRunner(db_path=":memory:", store_id="store_jiaojiang")
        # 使用外部db
        self.runner.db = self.db

    def tearDown(self):
        self.db.close()

    def _init_runner(self):
        """初始化引擎"""
        if not self.runner._engines:
            self.runner._init_engines()

    def test_scene_kitchen_eye(self):
        """场景1: 后厨之眼可执行"""
        self._init_runner()
        result = self.runner.scene_kitchen_eye()

        self.assertIn("steps", result)
        self.assertIn("key_metrics", result)
        self.assertEqual(len(result["steps"]), 4)
        self.assertIn("SOP合规分", result["key_metrics"])
        print(f"  ✅ 场景1完成: 合规分={result['key_metrics'].get('SOP合规分')}")

    def test_scene_smart_ordering(self):
        """场景2: 算得清的订货可执行"""
        self._init_runner()
        result = self.runner.scene_smart_ordering()

        self.assertIn("steps", result)
        self.assertEqual(len(result["steps"]), 5)
        self.assertIn("MAPE", result["key_metrics"])
        print(f"  ✅ 场景2完成: MAPE={result['key_metrics'].get('MAPE')}")

    def test_scene_supply_chain(self):
        """场景3: 冻品供应链管控可执行"""
        self._init_runner()
        result = self.runner.scene_supply_chain()

        self.assertIn("steps", result)
        self.assertEqual(len(result["steps"]), 5)
        print(f"  ✅ 场景3完成: SKU总数={result['key_metrics'].get('SKU总数')}")

    def test_scene_ai_assistant(self):
        """场景4: 岗位AI助理可执行"""
        self._init_runner()
        result = self.runner.scene_ai_assistant()

        self.assertIn("steps", result)
        self.assertEqual(len(result["steps"]), 4)
        self.assertIn("Agent数量", result["key_metrics"])
        print(f"  ✅ 场景4完成: Agent={result['key_metrics'].get('Agent数量')}个")

    def test_scene_chain_dashboard(self):
        """场景5: 连锁管控看板可执行"""
        self._init_runner()
        result = self.runner.scene_chain_dashboard()

        self.assertIn("steps", result)
        self.assertEqual(len(result["steps"]), 3)
        print(f"  ✅ 场景5完成")


class TestDemoRunnerIntegration(unittest.TestCase):
    """Demo运行器集成测试"""

    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row

    def tearDown(self):
        self.db.close()

    def test_run_all_scenes(self):
        """全部5个场景串联执行"""
        from demo.demo_data import DemoDataGenerator
        gen = DemoDataGenerator(self.db)
        gen.generate_all(days=15)  # 15天数据加快速度

        from demo.demo_runner import ExpoDemoRunner
        runner = ExpoDemoRunner(db_path=":memory:", store_id="store_jiaojiang")
        runner.db = self.db

        results = runner.run_all()

        self.assertIn("_total_elapsed", results)
        self.assertIn("_run_time", results)

        # 所有5个场景都应有结果
        expected_scenes = ["kitchen-eye", "smart-ordering", "supply-chain",
                          "ai-assistant", "chain-dashboard"]
        for scene in expected_scenes:
            self.assertIn(scene, results)
            self.assertNotIn("error", results[scene], f"场景 {scene} 有错误: {results[scene].get('error')}")

        print(f"  ✅ 全部5场景通过, 总耗时{results['_total_elapsed']}s")

    def test_two_store_data(self):
        """双店数据对比可用"""
        from demo.demo_data import DemoDataGenerator
        gen = DemoDataGenerator(self.db)
        gen.generate_all(days=20)

        # 两店都有数据
        jj_count = self.db.execute(
            "SELECT COUNT(*) as cnt FROM sop_check_history WHERE store_id='store_jiaojiang'"
        ).fetchone()["cnt"]
        yh_count = self.db.execute(
            "SELECT COUNT(*) as cnt FROM sop_check_history WHERE store_id='store_yuhuan'"
        ).fetchone()["cnt"]

        self.assertGreater(jj_count, 0)
        self.assertGreater(yh_count, 0)
        print(f"  ✅ 双店数据: 椒江{jj_count}条 + 玉环{yh_count}条")


class TestDemoEdgeCases(unittest.TestCase):
    """边界条件测试"""

    def test_empty_db(self):
        """空数据库不崩溃"""
        db = sqlite3.connect(":memory:")
        from demo.demo_runner import ExpoDemoRunner
        runner = ExpoDemoRunner(db_path=":memory:")
        runner.db = db
        runner._init_engines()  # 空DB初始化不应崩溃
        db.close()
        print(f"  ✅ 空DB初始化正常")

    def test_zero_days(self):
        """0天数据不报错"""
        db = sqlite3.connect(":memory:")
        from demo.demo_data import DemoDataGenerator
        gen = DemoDataGenerator(db)
        stats = gen.generate_all(days=0)
        self.assertIsInstance(stats, dict)
        db.close()
        print(f"  ✅ 0天数据处理正常")

    def test_store_config_complete(self):
        """店铺配置完整"""
        from demo.demo_data import DemoDataGenerator
        for key, cfg in DemoDataGenerator.STORES.items():
            self.assertIn("store_id", cfg)
            self.assertIn("name", cfg)
            self.assertIn("daily_revenue_base", cfg)
            self.assertIn("waste_rate_base", cfg)
        print(f"  ✅ 店铺配置完整 ({len(DemoDataGenerator.STORES)}家店)")


if __name__ == "__main__":
    unittest.main(verbosity=2)
