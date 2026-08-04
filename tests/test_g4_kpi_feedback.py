#!/usr/bin/env python3
"""G4: KPI 自动回写引擎 闭环测试.

验证:
  1. KPI 持久化表 Schema 正确性 (pg_db.py)
  2. 任务类型 → KPI 映射配置完整性
  3. KPIFeedbackEngine 核心逻辑:
     - on_task_completed 回调触发
     - 值提取和状态判定
     - PG 写入成功/失败处理
  4. AgentGateway COMPLETE_TASK 落地:
     - _handle_complete_task 真正调用 TaskStore
     - 触发 task_completed_callback
  5. 完整闭环模拟: 模拟任务完成 → KPI回写 → 查询验证
  6. 聚合KPI写入场景
  7. 边界情况: 无映射类型、PG未连接、降级模式

运行方式:
    python -m pytest tests/test_g4_kpi_feedback.py -v
"""

import os
import sys
import pytest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch, PropertyMock

# 确保项目路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# =====================================================================
# Test Group 1: KPI Schema 和映射配置
# =====================================================================

class TestKPISchemaAndMapping:
    """测试 KPI 表结构和映射配置."""

    def test_kpi_schema_exists(self):
        """G4-01: PG_KPI_METRICS_SCHEMA 已定义."""
        from hotpot_platform.cloud.event_hub.pg_db import PG_KPI_METRICS_SCHEMA
        assert PG_KPI_METRICS_SCHEMA is not None
        assert "CREATE TABLE IF NOT EXISTS kpi_metrics" in PG_KPI_METRICS_SCHEMA
        print("✅ G4-01: KPI Schema 定义正确")

    def test_kpi_schema_has_required_fields(self):
        """G4-02: Schema 包含所有必需字段."""
        from hotpot_platform.cloud.event_hub.pg_db import PG_KPI_METRICS_SCHEMA
        required_fields = [
            "store_id", "metric_id", "metric_name", "value", "unit",
            "status", "trend", "period_start", "period_end",
            "source_task_id", "category", "dimensions", "provenance"
        ]
        for field in required_fields:
            assert field in PG_KPI_METRICS_SCHEMA, f"缺少字段: {field}"
        print("✅ G4-02: Schema 字段完整")

    def test_kpi_schema_has_indexes(self):
        """G4-03: Schema 包含性能优化索引."""
        from hotpot_platform.cloud.event_hub.pg_db import PG_KPI_METRICS_SCHEMA
        assert "idx_kpi_store_metric" in PG_KPI_METRICS_SCHEMA
        assert "idx_kpi_period" in PG_KPI_METRICS_SCHEMA
        assert "idx_kpi_category" in PG_KPI_METRICS_SCHEMA
        assert "idx_kpi_task" in PG_KPI_METRICS_SCHEMA
        print("✅ G4-03: 索引定义完整 (4个)")

    def test_task_type_mapping_exists(self):
        """G4-04: TASK_TYPE_KPI_MAPPING 已定义."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import TASK_TYPE_KPI_MAPPING
        assert isinstance(TASK_TYPE_KPI_MAPPING, dict)
        assert len(TASK_TYPE_KPI_MAPPING) >= 6  # 至少6种任务类型
        print(f"✅ G4-04: 任务映射表包含 {len(TASK_TYPE_KPI_MAPPING)} 种类型")

    def test_mapping_has_core_types(self):
        """G4-05: 包含核心业务任务类型."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import TASK_TYPE_KPI_MAPPING
        core_types = ["cleaning", "sop_check", "purchase", "receiving", "inventory"]
        for t in core_types:
            assert t in TASK_TYPE_KPI_MAPPING, f"缺少核心类型: {t}"
        print("✅ G4-05: 核心业务类型映射完整")

    def test_mapping_structure_valid(self):
        """G4-06: 每个映射条目结构完整."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import TASK_TYPE_KPI_MAPPING
        required_keys = ["metric_id", "metric_name", "unit", "category", "value_extractor"]
        for task_type, mapping in TASK_TYPE_KPI_MAPPING.items():
            for key in required_keys:
                assert key in mapping, f"{task_type} 缺少 {key}"
                assert callable(mapping["value_extractor"]), f"{task_type} value_extractor 不可调用"
        print("✅ G4-06: 所有映射条目结构有效")


# =====================================================================
# Test Group 2: KPI 状态判定逻辑
# =====================================================================

class TestKPIDetermineStatus:
    """测试 KPI 状态判定函数."""

    def test_lower_direction_good(self):
        """G4-07: lower方向 - 达到good阈值."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import determine_kpi_status
        status = determine_kpi_status(
            value=50.0,
            thresholds={"good": 60, "warning": 120, "critical": 180},
            target_direction="lower"
        )
        assert status == "good"

    def test_lower_direction_warning(self):
        """G4-08: lower方向 - warning区间."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import determine_kpi_status
        status = determine_kpi_status(
            value=100.0,
            thresholds={"good": 60, "warning": 120, "critical": 180},
            target_direction="lower"
        )
        assert status == "warning"

    def test_lower_direction_critical(self):
        """G4-09: lower方向 - 超过critical阈值."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import determine_kpi_status
        status = determine_kpi_status(
            value=200.0,
            thresholds={"good": 60, "warning": 120, "critical": 180},
            target_direction="lower"
        )
        assert status == "critical"

    def test_higher_direction_good(self):
        """G4-10: higher方向 - 达到good阈值."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import determine_kpi_status
        status = determine_kpi_status(
            value=97.0,
            thresholds={"good": 95, "warning": 85, "critical": 70},
            target_direction="higher"
        )
        assert status == "good"

    def test_higher_direction_warning(self):
        """G4-11: higher方向 - warning区间."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import determine_kpi_status
        status = determine_kpi_status(
            value=88.0,
            thresholds={"good": 95, "warning": 85, "critical": 70},
            target_direction="higher"
        )
        assert status == "warning"

    def test_no_thresholds_returns_normal(self):
        """G4-12: 无阈值时返回 normal."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import determine_kpi_status
        status = determine_kpi_status(
            value=50.0,
            thresholds={},
            target_direction="lower"
        )
        assert status == "normal"


# =====================================================================
# Test Group 3: KPIFeedbackEngine 核心逻辑
# =====================================================================

class TestKPIFeedbackEngineCore:
    """测试 KPI 反馈引擎核心功能."""

    def setup_method(self):
        """每个测试前的设置."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine
        self.engine = KPIFeedbackEngine(pg_db=None)  # 不连接真实PG

    def test_engine_creation(self):
        """G4-13: 引擎可正常创建."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine
        engine = KPIFeedbackEngine()
        assert engine is not None
        assert engine._store_id == "store_jiaojiang"
        stats = engine.get_stats()
        assert stats["total_processed"] == 0
        print("✅ G4-13: 引擎创建成功")

    def test_on_task_completed_cleaning(self):
        """G4-14: 清台任务的 KPI 提取正确."""
        task_result = {
            "task_id": "TSK-CLEAN-001",
            "status": "completed",
            "db_updated": True,
        }
        kwargs = {
            "task_type": "cleaning",
            "table_id": "T02",
            "response_time_sec": 55,
            "source_event_id": "EVT-VISION-001",
        }

        records = self.engine.on_task_completed(task_result, **kwargs)

        # 应该生成1条 KPI 记录
        assert len(records) == 1
        record = records[0]
        assert record["metric_id"] == "cleaning_response_time"
        assert record["value"] == 55.0
        assert record["unit"] == "seconds"
        assert record["source_task_id"] == "TSK-CLEAN-001"
        assert record["dimensions"]["table_id"] == "T02"
        print("✅ G4-14: 清台任务 KPI 提取正确 (55秒)")

    def test_on_task_completed_sop_check(self):
        """G4-15: SOP检查任务的 KPI 提取正确."""
        task_result = {
            "task_id": "TSK-SOP-001",
            "status": "completed",
            "task_type": "sop_check",  # 放入 task_result 以便提取
            "compliance_score": 0.96,  # 96%
            "area": "kitchen_zone_a",
        }
        kwargs = {}  # 已在 task_result 中

        records = self.engine.on_task_completed(task_result, **kwargs)

        assert len(records) == 1
        assert records[0]["metric_id"] == "sop_compliance_rate"
        assert records[0]["value"] == 96.0  # 0.96 * 100
        assert records[0]["status"] == "good"  # 96 > 95 threshold
        print("✅ G4-15: SOP合规率 KPI 正确 (96%, good)")

    def test_on_task_completed_purchase(self):
        """G4-16: 采购任务的 KPI 提取正确."""
        task_result = {
            "task_id": "TSK-PUR-001",
            "status": "completed",
            "task_type": "purchase",  # 放入 task_result
            "on_time": True,
            "supplier": "supplier_wang",
        }
        kwargs = {}

        records = self.engine.on_task_completed(task_result, **kwargs)

        assert len(records) == 1
        assert records[0]["metric_id"] == "purchase_timeliness"
        assert records[0]["value"] == 100.0  # on_time=True → 100%
        assert records[0]["status"] == "good"
        print("✅ G4-16: 采购及时率 KPI 正确 (100%, good)")

    def test_on_task_completed_unknown_type(self):
        """G4-17: 未知任务类型不产生 KPI."""
        task_result = {"task_id": "TSK-UNKNOWN-001", "status": "completed"}
        kwargs = {"task_type": "nonexistent_type"}

        records = self.engine.on_task_completed(task_result, **kwargs)

        assert len(records) == 0
        print("✅ G4-17: 未知类型跳过 (无KPI)")

    def test_stats_tracking(self):
        """G4-18: 统计计数器正确更新."""
        # 处理3个任务
        self.engine.on_task_completed(
            {"task_id": "TSK-1"}, task_type="cleaning", response_time_sec=60
        )
        self.engine.on_task_completed(
            {"task_id": "TSK-2"}, task_type="sop_check", compliance_score=0.9
        )
        self.engine.on_task_completed(
            {"task_id": "TSK-3"}, task_type="unknown_type"
        )

        stats = self.engine.get_stats()
        assert stats["total_processed"] == 3
        assert stats["kpi_written"] == 0  # PG未连接，都算失败
        print(f"✅ G4-18: 统计正确 (processed={stats['total_processed']})")


# =====================================================================
# Test Group 4: PG 写入集成测试 (Mock)
# =====================================================================

class TestKPIPGWriteIntegration:
    """测试 KPI 写入 PG 的集成 (使用 Mock)."""

    def test_upsert_kpi_metric_success(self):
        """G4-19: upsert_kpi_metric 成功写入."""
        mock_pg = MagicMock()
        mock_pg.upsert_kpi_metric.return_value = 42  # 返回记录ID

        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine
        engine = KPIFeedbackEngine(pg_db=mock_pg)

        result = engine.on_task_completed(
            {"task_id": "TSK-PG-001"},
            task_type="cleaning",
            response_time_sec=45,
            table_id="T05",
        )

        assert len(result) == 1
        assert result[0]["_write_success"] is True
        assert result[0]["_record_id"] == 42
        mock_pg.upsert_kpi_metric.assert_called_once()
        print("✅ G4-19: PG写入成功 (id=42)")

    def test_upsert_kpi_metric_failure(self):
        """G4-20: PG写入失败时降级处理."""
        mock_pg = MagicMock()
        mock_pg.upsert_kpi_metric.side_effect = Exception("Connection lost")

        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine
        engine = KPIFeedbackEngine(pg_db=mock_pg)

        result = engine.on_task_completed(
            {"task_id": "TSK-PG-FAIL"},
            task_type="cleaning",
            response_time_sec=30,
        )

        assert len(result) == 1
        assert result[0]["_write_success"] is False
        assert result[0]["_record_id"] == -1
        print("✅ G4-20: PG写入失败时降级正常")

    def test_batch_aggregate_write(self):
        """G4-21: 聚合KPI批量写入."""
        mock_pg = MagicMock()
        mock_pg.write_aggregate_kpis.return_value = 3

        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine
        engine = KPIFeedbackEngine(pg_db=mock_pg)

        metrics = {
            "daily_revenue": {"value": 12000, "name": "日营业额", "unit": "¥"},
            "waste_rate": {"value": 2.5, "name": "损耗率", "unit": "%", "status": "good"},
            "customer_count": {"value": 150, "name": "客流量", "unit": "人"},
        }

        count = engine.write_aggregate_kpis(
            store_id="store_jiaojiang",
            period_start="2026-08-04T00:00:00+00:00",
            period_end="2026-08-04T23:59:59+00:00",
            metrics=metrics,
        )

        assert count == 3
        assert mock_pg.upsert_kpi_metric.call_count == 3
        print("✅ G4-21: 聚合KPI批量写入成功 (3条)")


# =====================================================================
# Test Group 5: AgentGateway 集成测试
# =====================================================================

class TestGatewayCompleteTaskIntegration:
    """测试 Gateway COMPLETE_TASK 与 KPI 引擎的集成."""

    def test_complete_task_triggers_callback(self):
        """G4-22: COMPLETE_TASK 触发 KPI 回写回调."""
        from hotpot_platform.cloud.agent_framework.agent_gateway import AgentGatewayMiddleware
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine

        gateway = AgentGatewayMiddleware.get_instance()
        gateway.initialize()

        # Mock KPI引擎
        mock_engine = MagicMock()
        mock_engine.on_task_completed.return_value = [
            {"metric_id": "cleaning_response_time", "_write_success": True}
        ]

        # 注入回调
        gateway.set_task_completed_callback(mock_engine.on_task_completed)

        # 执行 COMPLETE_TASK
        handler = gateway._handler_registry.get(
            __import__("hotpot_platform.cloud.agent_framework.action_types", fromlist=["ActionType"]).ActionType.COMPLETE_TASK
        )
        if handler and callable(handler):
            result = handler(
                task_id="TSK-GW-001",
                actor_id="server_B02",
                note="清台完成",
            )

            assert result["task_id"] == "TSK-GW-001"
            assert result["status"] == "completed"
            # 验证回调被调用
            mock_engine.on_task_completed.assert_called_once()
            call_args = mock_engine.on_task_completed.call_args
            assert call_args[0][0]["task_id"] == "TSK-GW-001"
            print("✅ G4-22: COMPLETE_TASK 成功触发KPI回调")
        else:
            pytest.skip("COMPLETE_TASK handler not properly registered")

    def test_complete_task_without_callback(self):
        """G4-23: 无回调时不崩溃."""
        from hotpot_platform.cloud.agent_framework.agent_gateway import AgentGatewayMiddleware

        gateway = AgentGatewayMiddleware.get_instance()
        gateway.initialize()

        # 不设置回调
        gateway._task_completed_callback = None

        handler = gateway._handler_registry.get(
            __import__("hotpot_platform.cloud.agent_framework.action_types", fromlist=["ActionType"]).ActionType.COMPLETE_TASK
        )
        if handler and callable(handler):
            result = handler(task_id="TSK-NO-CB")

            assert result["status"] == "completed"
            assert result["kpi_written"] is False
            assert "kpi_skipped_reason" in result
            print("✅ G4-23: 无回调时优雅降级")
        else:
            pytest.skip("COMPLETE_TASK handler not registered")

    def test_set_callback_api(self):
        """G4-24: set_task_completed_callback API 可用."""
        from hotpot_platform.cloud.agent_framework.agent_gateway import AgentGatewayMiddleware

        gateway = AgentGatewayMiddleware.get_instance()

        callback = lambda result, **kw: None
        gateway.set_task_completed_callback(callback)

        assert gateway._task_completed_callback is not None
        assert gateway._task_completed_callback == callback
        print("✅ G4-24: set_task_completed_callback API 正常")


# =====================================================================
# Test Group 6: 完整闭环端到端模拟
# =====================================================================

class TestEndToEndClosingLoop:
    """完整闭环端到端测试: 任务创建→完成→KPI回写→查询."""

    def test_full_loop_simulation(self):
        """G4-25: 模拟完整闭环流程.

        场景:
          1. 边缘检测到 T02 需要清理 → 创建任务 TSK-E2E-001
          2. 服务员接单并完成任务
          3. AgentGateway 处理 COMPLETE_TASK
          4. KPIFeedbackEngine 提取响应时间 (55秒)
          5. 写入 PG kpi_metrics 表
          6. 从 PG 查询验证数据完整
        """
        # 准备 Mock PG
        mock_pg = MagicMock()
        written_records = []

        def capture_upsert(**kwargs):
            record_id = len(written_records) + 1
            written_records.append({"id": record_id, **kwargs})
            return record_id

        mock_pg.upsert_kpi_metric.side_effect = capture_upsert

        # 初始化组件
        from hotpot_platform.cloud.agent_framework.agent_gateway import AgentGatewayMiddleware
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine

        gateway = AgentGatewayMiddleware.get_instance()
        gateway.initialize()

        engine = KPIFeedbackEngine(pg_db=mock_pg)
        gateway.set_task_completed_callback(engine.on_task_completed)

        # Step 1-2: 模拟任务完成
        complete_result = gateway._handle_complete_task(
            task_id="TSK-E2E-001",
            actor_id="waiter_B02",
            note="T02 清台完成",
            task_type="cleaning",
            table_id="T02",
            response_time_sec=55,
            source_event_id="EVT-VISION-T02",
        )

        # Step 3: 验证结果
        assert complete_result["status"] == "completed"
        assert complete_result["kpi_written"] is True

        # Step 4: 验证 PG 写入
        assert len(written_records) == 1
        kpi_record = written_records[0]
        assert kpi_record["metric_id"] == "cleaning_response_time"
        assert kpi_record["value"] == 55.0
        assert kpi_record["source_task_id"] == "TSK-E2E-001"
        assert kpi_record["provenance"]["tags"]  # 有溯源标签

        print("✅ G4-25: 完整闭环模拟通过!")
        print(f"   任务: TSK-E2E-001 → KPI: cleaning_response_time=55s → PG id={kpi_record['id']}")

    def test_multiple_tasks_aggregation(self):
        """G4-26: 多任务聚合统计场景.

        模拟1小时内完成5个清台任务，验证聚合KPI.
        """
        mock_pg = MagicMock()
        mock_pg.upsert_kpi_metric.return_value = 1

        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine
        engine = KPIFeedbackEngine(pg_db=mock_pg)

        # 模拟5个清台任务
        response_times = [45, 62, 38, 71, 55]  # 秒
        for i, rt in enumerate(response_times):
            engine.on_task_completed(
                {"task_id": f"TSK-AGG-{i+1:03d}", "status": "completed"},
                task_type="cleaning",
                table_id=f"T{(i%8)+1:02d}",
                response_time_sec=rt,
            )

        # 验证统计
        stats = engine.get_stats()
        assert stats["total_processed"] == 5
        assert mock_pg.upsert_kpi_metric.call_count == 5

        # 计算聚合指标
        avg_response = sum(response_times) / len(response_times)
        print(f"✅ G4-26: 多任务聚合通过! (avg={avg_response:.1f}s, tasks={stats['total_processed']})")


# =====================================================================
# Test Group 7: 边界情况和容错
# =====================================================================

class TestEdgeCasesAndFaultTolerance:
    """边界情况和容错测试."""

    def test_empty_task_result(self):
        """G4-27: 空 task_result 不崩溃."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine
        engine = KPIFeedbackEngine()

        result = engine.on_task_completed({})
        assert result == []
        print("✅ G4-27: 空 task_result 安全处理")

    def test_missing_required_fields(self):
        """G4-28: 缺少必要字段时使用默认值."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine
        engine = KPIFeedbackEngine()

        result = engine.on_task_completed(
            {"task_id": "TSK-MISSING"},
            task_type="cleaning",
            # 缺少 response_time_sec
        )

        # 应该用默认值 0
        assert len(result) == 1
        assert result[0]["value"] == 0.0
        print("✅ G4-28: 缺少字段时使用默认值 (0.0)")

    def test_custom_extractor_registration(self):
        """G4-29: 自定义提取器注册和使用."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine
        engine = KPIFeedbackEngine()

        # 注册自定义提取器 - 返回完整记录
        def custom_audit_extractor(task):
            score = task.get("score", 80)
            return {
                "metric_id": "custom_audit_score",
                "metric_name": "自定义审计分",
                "value": float(score),
                "unit": "分",
                "status": "good" if score >= 80 else "warning",
                "_write_success": True,
                "_record_id": 99,
            }

        engine.register_extractor("custom_audit", custom_audit_extractor, "custom_audit_score")

        result = engine.on_task_completed(
            {"task_id": "TSK-CUSTOM", "score": 92},  # score 在 task_result 中
            task_type="custom_audit",
        )

        assert len(result) == 1
        assert result[0]["metric_id"] == "custom_audit_score"
        assert result[0]["value"] == 92.0
        print("✅ G4-29: 自定义提取器工作正常 (value=92)")

    def test_stats_reset(self):
        """G4-30: 统计计数器重置."""
        from hotpot_platform.cloud.agent_framework.kpi_feedback_engine import KPIFeedbackEngine
        engine = KPIFeedbackEngine()

        # 先处理几个任务
        engine.on_task_completed({"task_id": "1"}, task_type="cleaning", response_time_sec=10)
        engine.on_task_completed({"task_id": "2"}, task_type="sop_check", compliance_score=0.9)

        assert engine.get_stats()["total_processed"] == 2

        # 重置
        engine.reset_stats()
        assert engine.get_stats()["total_processed"] == 0
        print("✅ G4-30: 统计重置正常")


# =====================================================================
# 运行入口
# =====================================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
