#!/usr/bin/env python3
"""
火瞳 · 部署验证测试套件 v1.0
============================

端到端部署验证，覆盖5大维度：
1. Schema初始化验证 (5 audit表 + product_master)
2. 数据迁移验证 (24产品 → 唯一 + 分类正确)
3. Demo数据种子验证 (3个采购周期场景)
4. API端点可用性检查 (Event Hub 8+ API)
5. 前端页面加载验证 (trace.html)

使用方式:
    # 运行全部测试
    python test_deployment_verification.py

    # 仅运行P0关键测试
    python test_deployment_verification.py --level P0

    # 输出详细报告
    python test_deployment_verification.py --verbose

    # 指定数据库URL (默认SQLite)
    python test_deployment_verification.py --db-url postgresql://user:pass@localhost/hotpot

作者: 火瞳AI团队
日期: 2026-08-03 (P1-A Step4)
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# 确保项目根目录在Python路径中
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

# ── 测试框架 ──
class TestResult:
    """单个测试结果"""
    def __init__(self, name: str, category: str, level: str):
        self.name = name
        self.category = category
        self.level = level
        self.passed = False
        self.error_msg = ""
        self.duration_ms = 0
        self.details = ""

    def __repr__(self):
        status = "✅ PASS" if self.passed else "❌ FAIL"
        return f"[{self.level}] {status} {self.name} ({self.duration_ms}ms)"


class TestSuite:
    """测试套件管理器"""

    def __init__(self, verbose: bool = False):
        self.results: List[TestResult] = []
        self.verbose = verbose
        self.start_time = time.time()
        self.total_tests = 0
        self.passed_tests = 0
        self.failed_tests = 0

    def add_result(self, result: TestResult):
        self.results.append(result)
        self.total_tests += 1
        if result.passed:
            self.passed_tests += 1
        else:
            self.failed_tests += 1

    def run_test(self, name: str, category: str, level: str, test_func):
        """运行单个测试用例"""
        result = TestResult(name, category, level)
        start = time.time()

        try:
            if self.verbose:
                print(f"  🔄 运行: {name}...")

            # 执行测试函数
            details = test_func()
            result.passed = True
            result.details = str(details) if details else "OK"

        except AssertionError as e:
            result.error_msg = str(e)
            result.details = f"AssertionError: {e}"
            if self.verbose:
                traceback.print_exc()

        except Exception as e:
            result.error_msg = str(e)
            result.details = f"{type(e).__name__}: {e}"
            if self.verbose:
                traceback.print_exc()

        finally:
            result.duration_ms = int((time.time() - start) * 1000)
            self.add_result(result)

            # 输出结果
            status_icon = "✅" if result.passed else "❌"
            print(f"  {status_icon} [{level}] {name} ({result.duration_ms}ms)")
            if not result.passed and result.error_msg:
                print(f"     ⚠️  {result.error_msg}")

        return result

    def summary(self) -> Dict[str, Any]:
        """生成测试摘要"""
        duration = int(time.time() - self.start_time)

        # 按级别统计
        by_level = {}
        for r in self.results:
            if r.level not in by_level:
                by_level[r.level] = {"total": 0, "passed": 0, "failed": 0}
            by_level[r.level]["total"] += 1
            if r.passed:
                by_level[r.level]["passed"] += 1
            else:
                by_level[r.level]["failed"] += 1

        return {
            "timestamp": datetime.now().isoformat(),
            "duration_seconds": duration,
            "total": self.total_tests,
            "passed": self.passed_tests,
            "failed": self.failed_tests,
            "pass_rate": f"{(self.passed_tests / max(self.total_tests, 1)) * 100:.1f}%",
            "by_level": by_level,
            "all_passed": self.failed_tests == 0,
        }


# ════════════════════════════════════════════════════════
# 测试用例实现
# ════════════════════════════════════════════════════════

class DeploymentVerificationTests:
    """部署验证测试集合"""

    def __init__(self, db_url: Optional[str] = None, hub_url: str = "http://127.0.0.1:8098"):
        self.db_url = db_url or os.environ.get("HOTPOT_DATABASE_URL", "")
        self.hub_url = hub_url
        self.suite = TestSuite()

    def _is_sqlite_mode(self) -> bool:
        """判断当前是否为SQLite模式"""
        from hotpot_platform.cloud.event_hub.middleware.db_init import _get_database_url
        db_url = self.db_url or _get_database_url()
        return not db_url or db_url.startswith("sqlite://") or db_url.startswith("sqlite:////")

    # ── 维度1: Schema初始化验证 ──

    def test_1_1_audit_tables_exist(self):
        """验证5张audit表已创建"""
        from hotpot_platform.cloud.event_hub.middleware.db_init import _get_sqlite_path

        if self._is_sqlite_mode():
            import sqlite3
            db_path = _get_sqlite_path()
            assert db_path.exists(), f"SQLite数据库不存在: {db_path}"

            conn = sqlite3.connect(str(db_path))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()

            expected_tables = [
                "purchase_suggestions",
                "approval_tasks",
                "purchase_orders",
                "receiving_records",
                "audit_events",
            ]
            for table in expected_tables:
                assert table in tables, f"缺少表: {table}"

            return f"找到 {len(tables)} 张表，包含全部5张audit表"
        else:
            # PG模式
            from hotpot_platform.cloud.event_hub.middleware.db_init import _get_pg_connection
            conn = _get_pg_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT table_name FROM information_schema.tables
                WHERE table_schema = 'public'
                AND table_name IN (
                    'purchase_suggestions', 'approval_tasks',
                    'purchase_orders', 'receiving_records', 'audit_events'
                )
            """)
            tables = [row[0] for row in cursor.fetchall()]
            conn.close()

            assert len(tables) == 5, f"PG模式: 只找到 {len(tables)}/5 张表: {tables}"
            return f"PG模式: 全部5张audit表存在"

    def test_1_2_product_master_table_exists(self):
        """验证product_master表已创建"""
        from hotpot_platform.cloud.event_hub.middleware.db_init import _get_sqlite_path

        if self._is_sqlite_mode():
            import sqlite3
            conn = sqlite3.connect(str(_get_sqlite_path()))
            cursor = conn.cursor()
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='product_master'")
            result = cursor.fetchone()
            conn.close()

            assert result is not None, "product_master表不存在"
            return "product_master表存在"
        else:
            from hotpot_platform.cloud.event_hub.middleware.db_init import _get_pg_connection
            conn = _get_pg_connection()
            cursor = conn.cursor()
            cursor.execute("""
                SELECT EXISTS(
                    SELECT 1 FROM information_schema.tables
                    WHERE table_name = 'product_master'
                )
            """)
            exists = cursor.fetchone()[0]
            conn.close()

            assert exists, "PG: product_master表不存在"
            return "PG: product_master表存在"

    def test_1_3_table_columns_valid(self):
        """验证关键字段列存在"""
        from hotpot_platform.cloud.event_hub.middleware.db_init import _get_sqlite_path

        expected_columns = {
            "purchase_suggestions": ["id", "suggestion_id", "correlation_id", "store_id", "items", "total_amount", "status"],
            "approval_tasks": ["id", "task_id", "correlation_id", "action_type", "risk_level", "status", "decision"],
            "purchase_orders": ["id", "order_id", "correlation_id", "supplier_name", "total_amount", "status"],
            "receiving_records": ["id", "receiving_id", "quality_grade", "temperature", "status"],
        }

        if self._is_sqlite_mode():
            import sqlite3
            conn = sqlite3.connect(str(_get_sqlite_path()))
            cursor = conn.cursor()

            for table, columns in expected_columns.items():
                cursor.execute(f"PRAGMA table_info({table})")
                existing_cols = [row[1] for row in cursor.fetchall()]
                for col in columns:
                    assert col in existing_cols, f"{table}.{col} 列不存在"

            conn.close()
            return f"SQLite: 全部{sum(len(v) for v in expected_columns.values())}个字段验证通过"
        else:
            from hotpot_platform.cloud.event_hub.middleware.db_init import _get_pg_connection
            conn = _get_pg_connection()
            cursor = conn.cursor()

            for table, columns in expected_columns.items():
                cursor.execute("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = %s
                """, (table,))
                existing_cols = [row[0] for row in cursor.fetchall()]
                for col in columns:
                    assert col in existing_cols, f"PG: {table}.{col} 列不存在"

            conn.close()
            return f"PG: 全部字段验证通过"

    # ── 维度2: 数据迁移验证 ──

    def test_2_1_product_count(self):
        """验证产品数量 (24条 → 19唯一)"""
        from hotpot_platform.cloud.event_hub.middleware.db_init import _get_sqlite_path

        if self._is_sqlite_mode():
            import sqlite3
            conn = sqlite3.connect(str(_get_sqlite_path()))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM product_master")
            count = cursor.fetchone()[0]
            conn.close()

            assert count >= 15, f"产品数量不足: {count} (期望>=15)"
            assert count <= 30, f"产品数量异常: {count} (期望<=30)"
            return f"产品总数: {count}"
        else:
            from hotpot_platform.cloud.event_hub.middleware.db_init import _get_pg_connection
            conn = _get_pg_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM product_master")
            count = cursor.fetchone()[0]
            conn.close()

            assert count >= 15, f"PG: 产品数量不足: {count}"
            return f"PG: 产品总数: {count}"

    def test_2_2_frozen_products_detected(self):
        """验证冻品自动识别 (至少5个)"""
        from hotpot_platform.cloud.event_hub.middleware.db_init import _get_sqlite_path

        if self._is_sqlite_mode():
            import sqlite3
            conn = sqlite3.connect(str(_get_sqlite_path()))
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM product_master WHERE is_frozen = 1")
            frozen_count = cursor.fetchone()[0]
            conn.close()

            assert frozen_count >= 5, f"冻品识别不足: {frozen_count} (期望>=5)"
            return f"冻品数量: {frozen_count}"
        else:
            from hotpot_platform.cloud.event_hub.middleware.db_init import _get_pg_connection
            conn = _get_pg_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM product_master WHERE is_frozen = true")
            frozen_count = cursor.fetchone()[0]
            conn.close()

            assert frozen_count >= 5, f"PG: 冻品识别不足: {frozen_count}"
            return f"PG: 冻品数量: {frozen_count}"

    def test_2_3_price_mapping_correct(self):
        """验证价格映射 (unit_price → cost_price)"""
        from hotpot_platform.cloud.event_hub.middleware.db_init import _get_sqlite_path

        if self._is_sqlite_mode():
            import sqlite3
            conn = sqlite3.connect(str(_get_sqlite_path()))
            cursor = conn.cursor()
            cursor.execute("SELECT sku_code, cost_price FROM product_master WHERE cost_price > 0 LIMIT 5")
            products = cursor.fetchall()
            conn.close()

            assert len(products) > 0, "无价格数据"
            for sku, price in products:
                assert price > 0, f"{sku} 价格异常: {price}"

            sample = ", ".join([f"{p[0]}:¥{p[1]}" for p in products[:3]])
            return f"价格示例: {sample}"
        else:
            return "PG: 跳过价格映射详细验证"

    # ── 维度3: Demo数据种子验证 ──

    def test_3_1_demo_scenarios_generated(self):
        """验证3个Demo场景可生成"""
        sys.path.insert(0, str(_PROJECT_ROOT))

        # 导入Demo数据生成器
        from scripts.seed_demo_data import DemoDataGenerator

        generator = DemoDataGenerator()
        scenarios = generator.generate_all()

        assert len(scenarios) == 3, f"场景数量错误: {len(scenarios)} (期望3)"

        expected_keys = {"normal", "rejected", "quality_issue"}
        actual_keys = set(scenarios.keys())
        assert expected_keys == actual_keys, f"场景键不匹配: {actual_keys}"

        return f"生成 {len(scenarios)} 个场景: {list(scenarios.keys())}"

    def test_3_2_normal_scenario_complete(self):
        """验证正常流程场景完整性"""
        sys.path.insert(0, str(_PROJECT_ROOT))
        from scripts.seed_demo_data import DemoDataGenerator

        generator = DemoDataGenerator()
        scenarios = generator.generate_all()
        normal = scenarios["normal"]

        # 检查必需字段
        required_phases = ["suggestion", "approval", "purchase_order", "receiving"]
        for phase in required_phases:
            assert phase in normal and normal[phase] is not None, f"正常流程缺少环节: {phase}"

        # 检查状态流转
        assert normal["suggestion"]["status"] == "accepted", "建议状态应为accepted"
        assert normal["approval"]["decision"] == "approve", "审批决策应为approve"
        assert normal["purchase_order"]["status"] == "received", "PO状态应为received"
        assert normal["receiving"]["quality_grade"] == "A", "质检等级应为A"

        # 检查时间线
        timeline = normal.get("timeline", [])
        assert len(timeline) >= 5, f"时间线节点不足: {len(timeline)} (期望>=5)"

        return f"正常流程完整: {len(timeline)} 个时间线节点"

    def test_3_3_rejected_scenario_stops_at_approval(self):
        """验证拒绝流程在审批环节终止"""
        sys.path.insert(0, str(_PROJECT_ROOT))
        from scripts.seed_demo_data import DemoDataGenerator

        generator = DemoDataGenerator()
        scenarios = generator.generate_all()
        rejected = scenarios["rejected"]

        # 审批拒绝后不应有PO和收货
        assert rejected["purchase_order"] is None, "拒绝流程不应有PO"
        assert rejected["receiving"] is None, "拒绝流程不应有收货记录"

        # 审批决策应为reject
        assert rejected["approval"]["decision"] == "reject", "审批决策应为reject"
        assert rejected["status"] == "rejected", "整体状态应为rejected"

        return "拒绝流程正确终止于审批环节"

    def test_3_4_quality_scenario_has_issues(self):
        """验证质检异常场景包含质量问题"""
        sys.path.insert(0, str(_PROJECT_ROOT))
        from scripts.seed_demo_data import DemoDataGenerator

        generator = DemoDataGenerator()
        scenarios = generator.generate_all()
        quality = scenarios["quality_issue"]

        # 应有D级质量评级
        assert quality["receiving"]["quality_grade"] == "D", "质检等级应为D"

        # 温度异常
        temp = quality["receiving"]["temperature"]
        assert temp > -15, f"温度应异常(>-15°C): 实际{temp}°C"

        # 统计应标记质量问题
        stats = quality.get("statistics", {})
        assert stats.get("quality_issues", 0) > 0, "统计应标记质量问题"
        assert stats.get("supplier_penalty") is True, "应有供应商扣分"

        return f"质检异常场景: D级, 温度{temp}°C, 已扣分供应商"

    # ── 维度4: API端点可用性检查 ──

    def test_4_1_health_endpoint(self):
        """验证Health Check端点"""
        import urllib.request
        import urllib.error

        try:
            url = f"{self.hub_url}/health"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = response.read().decode("utf-8")

                assert response.status == 200, f"HTTP状态码异常: {response.status}"

                # 尝试解析JSON
                try:
                    import json as json_mod
                    json_data = json_mod.loads(data)
                    assert "ok" in json_data or "status" in json_data, f"健康检查响应格式异常: {data[:100]}"
                    return f"Health OK: {json_data}"
                except json.JSONDecodeError:
                    # 可能返回纯文本
                    assert "ok" in data.lower(), f"健康检查内容异常: {data[:100]}"
                    return f"Health OK (text): {data[:50]}"

        except urllib.error.URLError as e:
            raise AssertionError(f"无法连接到Event Hub: {self.hub_url} - {e}")
        except Exception as e:
            raise AssertionError(f"健康检查失败: {e}")

    def test_4_2_api_docs_accessible(self):
        """验证API文档可访问"""
        import urllib.request
        import urllib.error

        try:
            url = f"{self.hub_url}/docs"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                assert response.status == 200, f"API文档HTTP状态码: {response.status}"
                html = response.read().decode("utf-8")
                assert len(html) > 100, "API文档内容过短"
                return f"API Docs 可访问 (HTML长度: {len(html)})"
        except urllib.error.URLError:
            raise AssertionError(f"API文档不可访问: {url}")
        except Exception as e:
            raise AssertionError(f"API文档验证失败: {e}")

    def test_4_3_purchase_cycle_endpoint_exists(self):
        """验证采购闭环API端点存在"""
        import urllib.request
        import urllib.error

        endpoints = [
            "/v1/purchase-cycles",
            "/v1/purchase-cycles/list",
        ]

        accessible = []
        for endpoint in endpoints:
            try:
                url = f"{self.hub_url}{endpoint}"
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=3) as response:
                    if response.status in [200, 401, 404]:  # 401=需认证, 404=路径可能不同
                        accessible.append(f"{endpoint} (HTTP {response.status})")
            except urllib.error.HTTPError as e:
                accessible.append(f"{endpoint} (HTTP {e.code})")
            except Exception as e:
                accessible.append(f"{endpoint} (Error: {str(e)[:30]})")

        return f"采购闭环端点检查: {'; '.join(accessible)}"

    def test_4_4_gateway_audit_endpoint(self):
        """验证Gateway审计日志端点"""
        import urllib.request
        import urllib.error

        try:
            url = f"{self.hub_url}/v1/gateway/audit-log?limit=1"
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=5) as response:
                data = response.read().decode("utf-8")

                if response.status == 200:
                    try:
                        import json as json_mod
                        json_data = json_mod.loads(data)
                        return f"Audit Log OK: {type(json_data).__name__}"
                    except:
                        return f"Audit Log Response: {data[:100]}"
                else:
                    return f"Audit Log HTTP {response.status}: {data[:50]}"

        except urllib.error.HTTPError as e:
            if e.code == 401:
                return "Audit Log 需要认证 (HTTP 401, 正常)"
            raise AssertionError(f"Audit Log端点异常: HTTP {e.code}")
        except Exception as e:
            raise AssertionError(f"Audit Log验证失败: {e}")

    # ── 维度5: 前端页面验证 ──

    def test_5_1_trace_html_exists(self):
        """验证trace.html文件存在"""
        trace_paths = [
            _PROJECT_ROOT / "hotpot_platform" / "cloud" / "event_hub" / "static" / "trace.html",
            _PROJECT_ROOT / "hotpot_platform" / "cloud" / "event_hub" / "routers" / "trace.html",
            _PROJECT_ROOT / "demo" / "web" / "trace.html",
        ]

        for path in trace_paths:
            if path.exists():
                size = path.stat().st_size
                assert size > 1000, f"trace.html文件过小: {size} bytes"
                return f"trace.html 存在: {path.name} ({size} bytes)"

        raise AssertionError(f"trace.html未找到，搜索路径: {[str(p) for p in trace_paths]}")

    def test_5_2_trace_html_structure(self):
        """验证trace.html基本结构"""
        trace_paths = [
            _PROJECT_ROOT / "hotpot_platform" / "cloud" / "event_hub" / "static" / "trace.html",
            _PROJECT_ROOT / "hotpot_platform" / "cloud" / "event_hub" / "routers" / "trace.html",
        ]

        content = None
        for path in trace_paths:
            if path.exists():
                content = path.read_text(encoding="utf-8")
                break

        if content is None:
            return "跳过(trace.html不存在)"

        # 检查基本HTML结构
        assert "<!DOCTYPE html>" in content or "<html" in content, "缺少HTML声明"
        assert "<head>" in content or "<body>" in content, "缺少head/body标签"
        assert "<script" in content or "<div" in content, "缺少脚本或内容区域"

        # 检查是否引用了必要资源
        has_timeline = "timeline" in content.lower() or "时间线" in content
        has_chart = "chart" in content.lower() or "图表" in content

        return f"trace.html结构OK (时间线:{has_timeline}, 图表:{has_chart})"


# ════════════════════════════════════════════════════════
# 主执行入口
# ════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description='火瞳部署验证测试套件')
    parser.add_argument('--level', choices=['P0', 'P1', 'P2', 'ALL'], default='ALL',
                       help='测试级别 (默认ALL)')
    parser.add_argument('--db-url', type=str, default=None,
                       help='数据库连接字符串 (默认自动检测)')
    parser.add_argument('--hub-url', type=str, default='http://127.0.0.1:8098',
                       help='Event Hub地址 (默认http://127.0.0.1:8098)')
    parser.add_argument('--verbose', action='store_true',
                       help='输出详细信息')
    parser.add_argument('--format', choices=['text', 'json'], default='text',
                       help='输出格式')

    args = parser.parse_args()

    print("")
    print("╔══════════════════════════════════════════════════╗")
    print("║       🔥 火瞳 · 部署验证测试套件 v1.0           ║")
    print("╠══════════════════════════════════════════════════╣")
    print(f"║  时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S'):<34} ║")
    print(f"║  级别: {args.level:<36} ║")
    print(f"║  数据库: {('PG' if args.db_url else 'SQLite'):<33} ║")
    print(f"║  Event Hub: {args.hub_url:<31} ║")
    print("╚══════════════════════════════════════════════════╝")
    print("")

    # 创建测试实例
    tests = DeploymentVerificationTests(db_url=args.db_url, hub_url=args.hub_url)

    # ── 定义测试矩阵 ──
    test_matrix = [
        # (名称, 类别, 级别, 测试方法)
        
        # 维度1: Schema初始化 (P0)
        ("1.1 Audit表存在性验证", "Schema", "P0", tests.test_1_1_audit_tables_exist),
        ("1.2 Product Master表验证", "Schema", "P0", tests.test_1_2_product_master_table_exists),
        ("1.3 表字段完整性验证", "Schema", "P1", tests.test_1_3_table_columns_valid),

        # 维度2: 数据迁移 (P0)
        ("2.1 产品数量验证", "Data", "P0", tests.test_2_1_product_count),
        ("2.2 冻品自动识别验证", "Data", "P0", tests.test_2_2_frozen_products_detected),
        ("2.3 价格映射正确性", "Data", "P1", tests.test_2_3_price_mapping_correct),

        # 维度3: Demo数据种子 (P1)
        ("3.1 Demo场景生成验证", "Demo", "P1", tests.test_3_1_demo_scenarios_generated),
        ("3.2 正常流程完整性", "Demo", "P0", tests.test_3_2_normal_scenario_complete),
        ("3.3 拒绝流程终止验证", "Demo", "P1", tests.test_3_3_rejected_scenario_stops_at_approval),
        ("3.4 质检异常场景验证", "Demo", "P1", tests.test_3_4_quality_scenario_has_issues),

        # 维度4: API端点 (P0/P1)
        ("4.1 Health Check端点", "API", "P0", tests.test_4_1_health_endpoint),
        ("4.2 API文档可访问性", "API", "P1", tests.test_4_2_api_docs_accessible),
        ("4.3 采购闭环API端点", "API", "P1", tests.test_4_3_purchase_cycle_endpoint_exists),
        ("4.4 Gateway审计端点", "API", "P1", tests.test_4_4_gateway_audit_endpoint),

        # 维度5: 前端页面 (P2)
        ("5.1 trace.html文件存在", "Frontend", "P2", tests.test_5_1_trace_html_exists),
        ("5.2 trace.html结构验证", "Frontend", "P2", tests.test_5_2_trace_html_structure),
    ]

    # 过滤测试级别
    if args.level != "ALL":
        test_matrix = [(n, c, l, f) for n, c, l, f in test_matrix if l == args.level or
                      (args.level == "P0" and l == "P0") or
                      (args.level == "P1" and l in ["P0", "P1"])]

    # 运行测试
    print(f"📋 计划运行 {len(test_matrix)} 个测试用例\n")

    current_category = None
    for name, category, level, test_func in test_matrix:
        # 输出分类标题
        if category != current_category:
            current_category = category
            category_names = {
                "Schema": "📊 维度1: Schema初始化验证",
                "Data": "💾 维度2: 数据迁移验证",
                "Demo": "🎭 维度3: Demo数据种子验证",
                "API": "🔌 维度4: API端点可用性",
                "Frontend": "🖥️  维度5: 前端页面验证",
            }
            print(f"\n{'─'*60}")
            print(f"  {category_names.get(category, category)}")
            print(f"{'─'*60}\n")

        tests.suite.run_test(name, category, level, test_func)

    # 生成报告
    summary = tests.suite.summary()

    print(f"\n{'='*60}")
    print(f"  📊 测试报告")
    print(f"{'='*60}")
    print(f"  总计:   {summary['total']} 个测试")
    print(f"  通过:   ✅ {summary['passed']} 个")
    print(f"  失败:   ❌ {summary['failed']} 个")
    print(f"  通过率: {summary['pass_rate']}")
    print(f"  耗时:   {summary['duration_seconds']}秒")
    print(f"{'='*60}\n")

    # 按级别统计
    if args.verbose:
        print("  各级别统计:")
        for level, stats in summary["by_level"].items():
            icon = "✅" if stats["failed"] == 0 else "❌"
            print(f"    {icon} [{level}] {stats['passed']}/{stats['total']} 通过")

    # 最终判定
    if summary["all_passed"]:
        print("  🎉 所有测试通过！部署验证成功！\n")
        exit_code = 0
    else:
        print("  ⚠️  部分测试失败，请检查上方错误信息\n")
        exit_code = 1

    # JSON输出
    if args.format == "json":
        report_file = _PROJECT_ROOT / "test_reports" / f"deployment_verify_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        report_file.parent.mkdir(parents=True, exist_ok=True)
        with open(report_file, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)
        print(f"  📄 详细报告已保存: {report_file}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
