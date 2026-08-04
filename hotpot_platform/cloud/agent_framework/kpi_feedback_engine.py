"""
火瞳 · KPI 自动回写引擎 (G4 闭环核心)
========================================

本模块实现了"感知→决策→执行→验证→**回写**"全闭环的最后一步。

当任务完成时，本引擎自动:
  1. 从任务结果中提取 KPI 原始数据 (如响应时间、完成耗时)
  2. 根据任务类型映射到对应的 KPI 指标定义
  3. 计算 KPI 值 (含趋势和状态判定)
  4. 持久化写入 Hub PG (kpi_metrics 表)
  5. 可选: 触发 Dashboard 刷新

设计原则:
  - 解耦: 引擎独立于 AgentGateway，通过回调注入
  - 可扩展: 支持自定义 TaskType → KPI 映射
  - 容错: 单条 KPI 写入失败不影响整体流程
  - 可追溯: 每条 KPI 记录都关联 source_task_id

使用方式:

    # 方式1: 注入到 AgentGateway (推荐)
    engine = KPIFeedbackEngine(pg_db)
    gateway = AgentGatewayMiddleware.get_instance()
    gateway.set_task_completed_callback(engine.on_task_completed)

    # 方式2: 手动触发
    engine.write_kpi_from_task(task_result)

作者: 火瞳AI团队
日期: 2026-08-04 (G4 KPI自动回写)
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

# 配置日志
logger = logging.getLogger(__name__)


# =====================================================================
# 1. 任务类型 → KPI 指标映射配置
# =====================================================================

#: 任务类型到 KPI 指标的映射表
TASK_TYPE_KPI_MAPPING: Dict[str, Dict[str, Any]] = {
    # 清台任务 → 清台响应时间
    "cleaning": {
        "metric_id": "cleaning_response_time",
        "metric_name": "清台响应时间",
        "unit": "seconds",
        "category": "operation",
        "target_direction": "lower",  # 越低越好
        "thresholds": {"good": 60, "warning": 120, "critical": 180},
        "value_extractor": lambda task: task.get("response_time_sec", 0),
        "dimension_extractor": lambda task: {"table_id": task.get("table_id", "")},
    },
    # SOP检查任务 → SOP合规率
    "sop_check": {
        "metric_id": "sop_compliance_rate",
        "metric_name": "SOP合规率",
        "unit": "%",
        "category": "quality",
        "target_direction": "higher",
        "thresholds": {"good": 95, "warning": 85, "critical": 70},
        "value_extractor": lambda task: task.get("compliance_score", 0) * 100,
        "dimension_extractor": lambda task: {"area": task.get("area", "")},
    },
    # 采购任务 → 采购及时率
    "purchase": {
        "metric_id": "purchase_timeliness",
        "metric_name": "采购及时率",
        "unit": "%",
        "category": "cost",
        "target_direction": "higher",
        "thresholds": {"good": 98, "warning": 90, "critical": 80},
        "value_extractor": lambda task: (
            100.0 if task.get("on_time", False) else 0.0
        ),
        "dimension_extractor": lambda task: {"supplier": task.get("supplier", "")},
    },
    # 收货质检任务 → 收货合格率
    "receiving": {
        "metric_id": "receiving_pass_rate",
        "metric_name": "收货合格率",
        "unit": "%",
        "category": "quality",
        "target_direction": "higher",
        "thresholds": {"good": 99, "warning": 95, "critical": 90},
        "value_extractor": lambda task: task.get("pass_rate", 100.0),
        "dimension_extractor": lambda task: {"sku": task.get("sku", "")},
    },
    # 库存盘点任务 → 库存准确率
    "inventory": {
        "metric_id": "inventory_accuracy",
        "metric_name": "库存准确率",
        "unit": "%",
        "category": "inventory",
        "target_direction": "higher",
        "thresholds": {"good": 98, "warning": 95, "critical": 90},
        "value_extractor": lambda task: task.get("accuracy", 100.0),
        "dimension_extractor": lambda task: {"area": task.get("area", "")},
    },
    # 废料检测任务 → 损耗率
    "waste_detection": {
        "metric_id": "waste_rate",
        "metric_name": "损耗率",
        "unit": "%",
        "category": "cost",
        "target_direction": "lower",
        "thresholds": {"good": 3.0, "warning": 5.0, "critical": 8.0},
        "value_extractor": lambda task: task.get("waste_rate", 0),
        "dimension_extractor": lambda task: {"sku": task.get("sku", "")},
    },
}


def determine_kpi_status(value: float, thresholds: Dict[str, float], target_direction: str) -> str:
    """根据阈值和目标方向判定 KPI 状态.

    Args:
        value: 当前值
        thresholds: 阈值字典 {good, warning, critical}
        target_direction: 'higher' 或 'lower'

    Returns:
        'good' / 'warning' / 'critical' / 'normal'
    """
    good = thresholds.get("good")
    warning = thresholds.get("warning")
    critical = thresholds.get("critical")

    if target_direction == "higher":
        # 越高越好: value >= good → good, >= warning → warning, < critical → critical
        if good is not None and value >= good:
            return "good"
        elif warning is not None and value >= warning:
            return "warning"
        elif critical is not None and value < critical:
            return "critical"
    else:  # lower
        # 越低越好: value <= good → good, <= warning → warning, > critical → critical
        if good is not None and value <= good:
            return "good"
        elif warning is not None and value <= warning:
            return "warning"
        elif critical is not None and value > critical:
            return "critical"

    return "normal"


# =====================================================================
# 2. KPI 反馈引擎主类
# =====================================================================

class KPIFeedbackEngine:
    """KPI 自动回写引擎.

    职责:
      1. 接收任务完成事件
      2. 提取 KPI 原始数据
      3. 计算并持久化 KPI 到 Hub PG
      4. 提供聚合统计接口

    典型生命周期:
      engine = KPIFeedbackEngine(pg_db_instance)
      gateway.set_task_completed_callback(engine.on_task_completed)
    """

    def __init__(self, pg_db=None, store_id: str = "store_jiaojiang"):
        """初始化引擎.

        Args:
            pg_db: PostgresHubDatabase 实例 (可选，延迟初始化)
            store_id: 默认门店ID
        """
        self._pg_db = pg_db
        self._store_id = store_id
        self._custom_extractors: Dict[str, Callable] = {}  # 自定义提取器
        self._stats = {
            "total_processed": 0,
            "kpi_written": 0,
            "kpi_failed": 0,
        }

    @property
    def pg_db(self):
        """延迟获取 PG DB 实例."""
        if self._pg_db is None:
            try:
                from hotpot_platform.cloud.event_hub.pg_db import PostgresHubDatabase
                import os
                db_url = os.environ.get("HOTPOT_DATABASE_URL")
                if db_url:
                    self._pg_db = PostgresHubDatabase(db_url)
            except Exception as exc:
                logger.warning(f"无法初始化 PG DB: {exc}")
        return self._pg_db

    def register_extractor(
        self, task_type: str, extractor: Callable, metric_id: str = "",
    ) -> None:
        """注册自定义任务类型的 KPI 提取器.

        Args:
            task_type: 任务类型 (如 'custom_audit')
            extractor: 提取函数 (task_dict) → (metric_value, metric_name, unit, ...)
            metric_id: 对应的指标ID
        """
        self._custom_extractors[task_type] = (extractor, metric_id)
        logger.info(f"已注册自定义 KPI 提取器: {task_type} → {metric_id}")

    def on_task_completed(self, task_result: Dict, **kwargs) -> List[Dict]:
        """任务完成回调入口 (AgentGateway 调用).

        这是 G4 闭环的核心入口点，由 AgentGateway._handle_complete_task()
        在任务完成后自动调用。

        Args:
            task_result: 任务完成结果 (包含 task_id, status 等)
            **kwargs: 额外参数 (来自 Gateway 的 params)

        Returns:
            写入的 KPI 记录列表
        """
        task_id = task_result.get("task_id")
        if not task_id:
            logger.warning("⚠️ G4: 收到无 task_id 的任务完成事件")
            return []

        self._stats["total_processed"] += 1
        logger.info(f"🔄 G4: 开始处理任务 {task_id} 的 KPI 回写")

        # 尝试从 kwargs 获取完整任务信息
        task_info = self._enrich_task_info(task_result, kwargs)

        # 提取并写入 KPI
        kpi_records = self._extract_and_write_kpis(task_info)

        # 更新统计
        success_count = sum(1 for r in kpi_records if r.get("_write_success"))
        fail_count = len(kpi_records) - success_count
        self._stats["kpi_written"] += success_count
        self._stats["kpi_failed"] += fail_count

        logger.info(
            f"✅ G4: 任务 {task_id} KPI回写完成 "
            f"(成功={success_count}, 失败={fail_count})"
        )

        return kpi_records

    def _enrich_task_info(
        self, task_result: Dict, kwargs: Dict,
    ) -> Dict:
        """丰富任务信息 (合并多个来源)."""
        info = dict(task_result)

        # 从 kwargs 补充字段
        for key in ["task_type", "table_id", "response_time_sec",
                     "completion_time_sec", "source_event_id",
                     "assignee", "store_id"]:
            if key in kwargs and key not in info:
                info[key] = kwargs[key]

        if "store_id" not in info:
            info["store_id"] = self._store_id

        return info

    def _extract_and_write_kpis(self, task_info: Dict) -> List[Dict]:
        """提取 KPI 并写入 PG.

        Returns:
            KPI记录列表 (每条包含 _write_success 标记)
        """
        task_type = task_info.get("task_type", "")
        task_id = task_info.get("task_id", "")

        # 查找映射配置
        mapping = TASK_TYPE_KPI_MAPPING.get(task_type)
        if not mapping:
            # 尝试自定义提取器
            if task_type in self._custom_extractors:
                return self._call_custom_extractor(task_type, task_info)
            else:
                logger.debug(
                    f"G4: 任务类型 '{task_type}' 无 KPI 映射，跳过 (task={task_id})"
                )
                return []

        # 提取值
        try:
            value_extractor = mapping["value_extractor"]
            value = float(value_extractor(task_info))
        except Exception as exc:
            logger.warning(f"G4: KPI值提取失败 ({task_type}/{task_id}): {exc}")
            return []

        # 提取维度
        try:
            dim_extractor = mapping["dimension_extractor"]
            dimensions = dim_extractor(task_info) or {}
        except Exception:
            dimensions = {}

        # 判定状态
        status = determine_kpi_status(
            value, mapping.get("thresholds", {}), mapping.get("target_direction", "lower")
        )

        # 构建记录
        now = datetime.now(timezone.utc)
        kpi_record = {
            "store_id": task_info.get("store_id", self._store_id),
            "metric_id": mapping["metric_id"],
            "metric_name": mapping["metric_name"],
            "value": value,
            "unit": mapping.get("unit", ""),
            "target": mapping.get("thresholds", {}).get("good"),
            "status": status,
            "trend": "unknown",  # 需要历史数据才能计算趋势
            "change_pct": 0.0,
            "period_start": now.isoformat(),
            "period_end": now.isoformat(),
            "source_task_id": task_id,
            "source_event_id": task_info.get("source_event_id"),
            "category": mapping.get("category", "operation"),
            "dimensions": dimensions,
            "provenance": {
                "version": "1.0",
                "source": "kpi_feedback_engine",
                "source_device": "cloud_platform",
                "confidence": 0.95,
                "tags": ["auto-kpi", f"task-type-{task_type}", "g4-closing-loop"],
                "generated_at": now.isoformat(),
            },
        }

        # 写入 PG
        write_success = False
        record_id = -1
        try:
            db = self.pg_db
            if db:
                record_id = db.upsert_kpi_metric(**kpi_record)
                write_success = True
        except Exception as exc:
            logger.error(f"G4: KPI写入PG失败 ({mapping['metric_id']}/{task_id}): {exc}")

        kpi_record["_write_success"] = write_success
        kpi_record["_record_id"] = record_id

        return [kpi_record]

    def _call_custom_extractor(
        self, task_type: str, task_info: Dict,
    ) -> List[Dict]:
        """调用自定义提取器."""
        extractor, metric_id = self._custom_extractors[task_type]
        try:
            result = extractor(task_info)
            if isinstance(result, dict):
                result["_write_success"] = True
                return [result]
            elif isinstance(result, list):
                return result
        except Exception as exc:
            logger.warning(f"G4: 自定义提取器失败 ({task_type}): {exc}")
        return []

    def write_aggregate_kpis(
        self,
        store_id: str,
        period_start: str,
        period_end: str,
        metrics: Dict[str, Any],
        provenance: Optional[Dict] = None,
    ) -> int:
        """写入聚合 KPI 快照 (用于批量/定时场景).

        例如每小时/每天的聚合统计。

        Args:
            store_id: 门店ID
            period_start: 周期开始
            period_end: 周期结束
            metrics: 指标字典 {metric_id: {value, name, unit, ...}}
            provenance: 溯源信息

        Returns:
            成功写入的记录数
        """
        db = self.pg_db
        if not db:
            logger.warning("G4: PG DB 未连接，无法写入聚合KPI")
            return 0

        success_count = 0
        for metric_id, metric_data in metrics.items():
            try:
                record_id = db.upsert_kpi_metric(
                    store_id=store_id,
                    metric_id=metric_id,
                    metric_name=metric_data.get("name", metric_id),
                    value=float(metric_data.get("value", 0)),
                    unit=metric_data.get("unit", ""),
                    target=metric_data.get("target"),
                    status=metric_data.get("status", "normal"),
                    trend=metric_data.get("trend", "unknown"),
                    change_pct=float(metric_data.get("change_pct", 0)),
                    period_start=period_start,
                    period_end=period_end,
                    category=metric_data.get("category", "operation"),
                    dimensions=metric_data.get("dimensions", {}),
                    provenance=provenance or {
                        "version": "1.0",
                        "source": "aggregate_engine",
                        "tags": ["aggregate", "g4-closing-loop"],
                    },
                )
                success_count += 1
                logger.debug(f"G4: 聚合KPI写入成功: {metric_id} (id={record_id})")
            except Exception as exc:
                logger.warning(f"G4: 聚合KPI写入失败 ({metric_id}): {exc}")

        return success_count

    def get_stats(self) -> Dict[str, int]:
        """获取引擎运行统计."""
        return dict(self._stats)

    def reset_stats(self) -> None:
        """重置统计计数器."""
        self._stats = {"total_processed": 0, "kpi_written": 0, "kpi_failed": 0}
