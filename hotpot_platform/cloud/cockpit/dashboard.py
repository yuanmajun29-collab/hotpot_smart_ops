#!/usr/bin/env python3
"""店长数字座舱 — 核心引擎 (A01-A05).

模块:
- DashboardAggregator: 数据聚合器(汇聚多源数据生成完整座舱)
- KPIEngine: KPI指标计算
- AlertSummary: 告警汇总与分级
- DecisionSupport: 决策建议生成
- StoreComparison: 门店对比分析

对应PRD A01-A05.
"""

from __future__ import annotations

import logging
import random
from datetime import date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

from .models import (
    AlertItem,
    AlertLevel,
    ComparisonResult,
    DashboardData,
    DecisionSuggestion,
    KPIItem,
    KitchenDashboardData,
    MetricTrend,
    Priority,
    ProcurementDashboardData,
    StoreMetric,
    TodoItem,
    TodoStatus,
    WasteAlertItem,
)

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────
# KPI 定义注册表
# ──────────────────────────────────────────────────────────────

KPI_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "daily_revenue": {
        "name": "日营业额",
        "unit": "¥",
        "target_direction": "higher",   # 越高越好
        "category": "revenue",
        "weight": 0.2,
    },
    "waste_rate": {
        "name": "损耗率",
        "unit": "%",
        "target_direction": "lower",    # 越低越好
        "category": "cost",
        "weight": 0.15,
        "thresholds": {"good": 3.0, "warning": 5.0, "critical": 8.0},
    },
    "table_turnover": {
        "name": "翻台率",
        "unit": "次",
        "target_direction": "higher",
        "category": "operation",
        "weight": 0.1,
    },
    "customer_count": {
        "name": "客流量",
        "unit": "人",
        "target_direction": "higher",
        "category": "revenue",
        "weight": 0.1,
    },
    "avg_ticket": {
        "name": "客单价",
        "unit": "¥",
        "target_direction": "higher",
        "category": "revenue",
        "weight": 0.1,
    },
    "sop_compliance": {
        "name": "SOP合规率",
        "unit": "%",
        "target_direction": "higher",
        "category": "quality",
        "weight": 0.15,
        "thresholds": {"good": 95, "warning": 85, "critical": 70},
    },
    "inventory_accuracy": {
        "name": "库存准确率",
        "unit": "%",
        "target_direction": "higher",
        "category": "inventory",
        "weight": 0.1,
        "thresholds": {"good": 98, "warning": 95, "critical": 90},
    },
    "labor_efficiency": {
        "name": "人效",
        "unit": "¥/人",
        "target_direction": "higher",
        "category": "staffing",
        "weight": 0.1,
    },
}


class KPIEngine:
    """KPI指标计算引擎.

    从各数据源采集原始数据 → 计算KPI → 判定状态/趋势.
    """

    def __init__(self) -> None:
        self._data_sources: Dict[str, Callable] = {}
        self._cache: Dict[str, KPIItem] = {}
        self._cache_time: Optional[datetime] = None
        self._cache_ttl_seconds = 300  # 5分钟缓存

    def register_source(self, metric_id: str, source_fn: Callable) -> None:
        """注册数据源函数."""
        self._data_sources[metric_id] = source_fn

    def calculate_all(self, store_id: str) -> List[KPIItem]:
        """计算所有KPI."""
        kpis: List[KPIItem] = []
        for metric_id, definition in KPI_DEFINITIONS.items():
            kpi = self.calculate_one(store_id, metric_id)
            if kpi:
                kpis.append(kpi)
        return kpis

    def calculate_one(self, store_id: str, metric_id: str) -> Optional[KPIItem]:
        """计算单个KPI."""
        # 检查缓存
        cache_key = f"{store_id}:{metric_id}"
        if (self._cache.get(cache_key) and self._cache_time and
                (datetime.now() - self._cache_time).total_seconds() < self._cache_ttl_seconds):
            return self._cache[cache_key]

        definition = KPI_DEFINITIONS.get(metric_id)
        if not definition:
            return None

        # 从数据源获取值
        raw_value = None
        source_fn = self._data_sources.get(metric_id)
        if source_fn:
            try:
                raw_value = source_fn(store_id)
            except Exception as exc:
                logger.warning("KPI source error for %s: %s", metric_id, exc)

        # 如果无数据源，使用模拟值(演示用)
        if raw_value is None:
            raw_value = self._simulate_value(metric_id)

        # 计算趋势和状态
        previous = self._get_previous_value(store_id, metric_id)
        trend, change_pct = self._calculate_trend(raw_value, previous, definition["target_direction"])
        status = self._determine_status(raw_value, definition)

        kpi = KPIItem(
            metric_id=metric_id,
            name=definition["name"],
            value=round(raw_value, 2),
            unit=definition["unit"],
            target=definition.get("thresholds", {}).get("good"),
            previous_value=previous,
            trend=trend,
            change_pct=round(change_pct, 1),
            status=status,
        )

        # 缓存
        self._cache[cache_key] = kpi
        self._cache_time = datetime.now()

        return kpi

    @staticmethod
    def _simulate_value(metric_id: str) -> float:
        """模拟KPI值(用于Demo/测试)."""
        simulators = {
            "daily_revenue": lambda: random.uniform(8000, 15000),
            "waste_rate": lambda: random.uniform(2.0, 7.0),
            "table_turnover": lambda: random.uniform(2.5, 4.5),
            "customer_count": lambda: random.randint(80, 200),
            "avg_ticket": lambda: random.uniform(60, 120),
            "sop_compliance": lambda: random.uniform(78, 99),
            "inventory_accuracy": lambda: random.uniform(92, 99.5),
            "labor_efficiency": lambda: random.uniform(800, 1500),
        }
        fn = simulators.get(metric_id, lambda: 0.0)
        return fn()

    @staticmethod
    def _get_previous_value(store_id: str, metric_id: str) -> Optional[float]:
        """获取上期值(简化版)."""
        return None  # 实际应从DB/缓存读取

    @staticmethod
    def _calculate_trend(current: float, previous: Optional[float], direction: str) -> tuple:
        """计算趋势."""
        if previous is None or previous == 0:
            return MetricTrend.UNKNOWN, 0.0

        change_pct = (current - previous) / abs(previous) * 100

        if direction == "higher":
            trend = MetricTrend.UP if change_pct > 1 else (MetricTrend.DOWN if change_pct < -1 else MetricTrend.STABLE)
        else:
            trend = MetricTrend.DOWN if change_pct > 1 else (MetricTrend.UP if change_pct < -1 else MetricTrend.STABLE)

        return trend, round(change_pct, 1)

    @staticmethod
    def _determine_status(value: float, definition: Dict[str, Any]) -> str:
        """根据阈值判定状态."""
        thresholds = definition.get("thresholds", {})
        direction = definition.get("target_direction", "higher")

        good = thresholds.get("good")
        warning = thresholds.get("warning")
        critical = thresholds.get("critical")

        if good is not None:
            if direction == "higher":
                if value >= good:
                    return "good"
                elif warning and value >= warning:
                    return "normal"
                elif critical and value >= critical:
                    return "warning"
                return "critical"
            else:
                if value <= good:
                    return "good"
                elif warning and value <= warning:
                    return "normal"
                elif critical and value <= critical:
                    return "warning"
                return "critical"

        return "normal"


class AlertSummary:
    """告警汇总与分级.

    汇总来自各模块的告警(SOP/库存/IoT/废料等), 分级展示.
    """

    def __init__(self) -> None:
        self._alert_sources: List[Callable] = []

    def register_source(self, source_fn: Callable) -> None:
        """注册告警源."""
        self._alert_sources.append(source_fn)

    def summarize(
        self,
        store_id: str,
        level_filter: Optional[AlertLevel] = None,
        acknowledged_only: bool = False,
    ) -> List[AlertItem]:
        """汇总告警."""
        all_alerts: List[AlertItem] = []

        for source_fn in self._alert_sources:
            try:
                alerts = source_fn(store_id)
                if isinstance(alerts, list):
                    all_alerts.extend(alerts)
            except Exception as exc:
                logger.warning("Alert source error: %s", exc)

        # 过滤
        if level_filter:
            all_alerts = [a for a in all_alerts if a.level == level_filter]
        if acknowledged_only:
            all_alerts = [a for a in all_alerts if a.acknowledged]

        # 按级别和时间排序
        priority_order = {AlertLevel.CRITICAL: 0, AlertLevel.WARNING: 1, AlertLevel.INFO: 2}
        all_alerts.sort(key=lambda a: (priority_order.get(a.level, 9), a.detected_at), reverse=True)

        return all_alerts

    @staticmethod
    def generate_mock_alerts(store_id: str) -> List[AlertItem]:
        """生成模拟告警(Demo用)."""
        now = datetime.now()
        return [
            AlertItem(
                alert_id=f"ALERT-{store_id}-001",
                level=AlertLevel.WARNING,
                title="冷链温度偏高",
                message="冷冻间A温度-17.5°C，接近上限(-16°C)",
                source="iot_monitor",
                detected_at=now - timedelta(minutes=15),
                action_suggested="检查制冷设备运行状态",
            ),
            AlertItem(
                alert_id=f"ALERT-{store_id}-002",
                level=AlertLevel.INFO,
                title="毛肚库存偏低",
                message="毛肚当前库存2.3kg，低于安全库存(5kg)",
                source="inventory_alertor",
                detected_at=now - timedelta(hours=1),
                action_suggested="建议明日采购补充",
            ),
            AlertItem(
                alert_id=f"ALERT-{store_id}-003",
                level=AlertLevel.CRITICAL,
                title="SOP违规: 未佩戴口罩",
                message="厨房区域检测到1人次未规范佩戴口罩",
                source="sop_checker",
                detected_at=now - timedelta(minutes=5),
                action_suggested="立即提醒员工规范佩戴",
            ),
        ]


class DecisionSupport:
    """决策建议生成器.

    基于多源数据分析生成可操作的决策建议.
    """

    def generate_suggestions(
        self,
        store_id: str,
        kpis: List[KPIItem],
        alerts: List[AlertItem],
    ) -> List[DecisionSuggestion]:
        """基于KPI和告警生成决策建议."""
        suggestions: List[DecisionSuggestion] = []

        # 1. 基于KPI异常的建议
        for kpi in kpis:
            if kpi.status in ("warning", "critical"):
                suggestion = self._kpi_to_suggestion(kpi)
                if suggestion:
                    suggestions.append(suggestion)

        # 2. 基于告警的建议
        for alert in alerts:
            if not alert.acknowledged and alert.level in (AlertLevel.CRITICAL, AlertLevel.WARNING):
                suggestion = self._alert_to_suggestion(alert)
                if suggestion:
                    suggestions.append(suggestion)

        # 3. 综合优化建议
        optimization = self._generate_optimization(kpis)
        if optimization:
            suggestions.extend(optimization)

        # 排序: 按优先级+置信度
        priority_order = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}
        suggestions.sort(
            key=lambda s: (priority_order.get(s.priority, 9), -s.confidence)
        )

        return suggestions[:10]  # 最多10条

    @staticmethod
    def _kpi_to_suggestion(kpi: KPIItem) -> Optional[DecisionSuggestion]:
        """将KPI异常转为建议."""
        generators = {
            "waste_rate": lambda: DecisionSuggestion(
                suggestion_id=f"SUG-waste-{kpi.metric_id}",
                title="损耗率优化建议",
                description=f"当前损耗率{kpi.value:.1f}%，{'高于' if kpi.value > 5 else '处于'}目标水平。建议检查高损耗菜品TOP5。",
                category="cost",
                impact_type="save",
                impact_amount=(kpi.value - 3.0) * 500,  # 粗略估算日节省
                confidence=0.8 if kpi.value > 5 else 0.6,
                data_sources=["waste_detection", "inventory"],
                action_steps=[
                    "查看废料检测报告，定位高频损耗菜品",
                    "检查备货量是否超过实际需求",
                    "评估出品率和切配标准执行情况",
                ],
                priority=Priority.HIGH if kpi.value > 5 else Priority.MEDIUM,
            ),
            "sop_compliance": lambda: DecisionSuggestion(
                suggestion_id=f"SUG-sop-{kpi.metric_id}",
                title="SOP合规提升建议",
                description=f"SOP合规率{kpi.value:.1f}%，需提升至95%以上。",
                category="quality",
                impact_type="improve",
                impact_amount=95 - kpi.value,
                confidence=0.75,
                data_sources=["sop_engine"],
                action_steps=[
                    "查看今日SOP违规详情",
                    "安排重点规则培训",
                    "考虑调整检查频次",
                ],
                priority=Priority.HIGH if kpi.value < 85 else Priority.MEDIUM,
            ),
        }
        fn = generators.get(kpi.metric_id)
        return fn() if fn else None

    @staticmethod
    def _alert_to_suggestion(alert: AlertItem) -> Optional[DecisionSuggestion]:
        """将告警转为建议."""
        if not alert.action_suggested:
            return None
        return DecisionSuggestion(
            suggestion_id=f"SUG-alert-{alert.alert_id}",
            title=f"处理: {alert.title}",
            description=alert.message,
            category="operations",
            impact_type="improve",
            confidence=0.9,
            data_sources=[alert.source],
            action_steps=[alert.action_suggested],
            priority=Priority.CRITICAL if alert.level == AlertLevel.CRITICAL else Priority.HIGH,
        )

    @staticmethod
    def _generate_optimization(kpis: List[KPIItem]) -> List[DecisionSuggestion]:
        """生成综合优化建议."""
        suggestions = []

        # 查找关联指标异常组合
        waste_kpi = next((k for k in kpis if k.metric_id == "waste_rate"), None)
        revenue_kpi = next((k for k in kpis if k.metric_id == "daily_revenue"), None)

        if waste_kpi and revenue_kpi:
            if waste_kpi.status == "warning" and revenue_kpi.status == "normal":
                suggestions.append(DecisionSuggestion(
                    suggestion_id="SUG-combined-001",
                    title="降损增效综合方案",
                    description="损耗率偏高但营收正常，存在优化空间。",
                    category="cost",
                    impact_type="save",
                    impact_amount=waste_kpi.value * 400,
                    confidence=0.7,
                    data_sources=["waste_detection", "pos"],
                    action_steps=[
                        "启动损耗专项分析周报",
                        "对比各时段损耗分布",
                        "制定分时段备料优化方案",
                    ],
                    priority=Priority.MEDIUM,
                ))

        return suggestions


class StoreComparison:
    """门店对比分析."""

    def compare_stores(
        self,
        primary_store_id: str,
        store_ids: List[str],
        comparison_date: Optional[date] = None,
        metrics: Optional[List[str]] = None,
    ) -> ComparisonResult:
        """多店横向对比."""
        comparison_date = comparison_date or date.today()
        metrics = metrics or list(KPI_DEFINITIONS.keys())

        stores_data: List[StoreMetric] = []
        for sid in [primary_store_id] + store_ids:
            metric_values = {}
            for mid in metrics:
                # 实际应从DB查询，这里用模拟
                metric_values[mid] = KPIEngine._simulate_value(mid)
            stores_data.append(StoreMetric(
                store_id=sid,
                store_name=self._store_name(sid),
                metrics=metric_values,
                period_start=comparison_date - timedelta(days=1),
                period_end=comparison_date,
            ))

        # 计算排名
        rankings: Dict[str, List[str]] = {}
        for mid in metrics:
            sorted_stores = sorted(stores_data, key=lambda s: s.metrics.get(mid, 0), reverse=True)
            rankings[mid] = [s.store_id for s in sorted_stores]

        # 检测异常(偏离均值>2个标准差)
        anomalies = []
        for mid in metrics:
            values = [s.metrics.get(mid, 0) for s in stores_data]
            if values:
                avg = sum(values) / len(values)
                variance = sum((v - avg) ** 2 for v in values) / len(values)
                std_dev = variance ** 0.5 if variance > 0 else 1
                for s in stores_data:
                    val = s.metrics.get(mid, 0)
                    if abs(val - avg) > 2 * std_dev:
                        anomalies.append({
                            "store_id": s.store_id,
                            "metric_id": mid,
                            "value": val,
                            "avg": round(avg, 2),
                            "deviation": round((val - avg) / std_dev if std_dev > 0 else 0, 2),
                        })

        return ComparisonResult(
            primary_store_id=primary_store_id,
            comparison_date=comparison_date,
            stores=stores_data,
            rankings=rankings,
            anomalies=anomalies,
        )

    @staticmethod
    def _store_name(store_id: str) -> str:
        """获取门店名称."""
        names = {
            "store_jiaojiang": "椒江店",
            "store_yuhuan": "玉环店",
        }
        return names.get(store_id, store_id)


class DashboardAggregator:
    """座舱数据聚合器(A01核心).

    汇聚所有子模块数据 → 生成完整DashboardData.
    """

    def __init__(
        self,
        kpi_engine: KPIEngine = None,
        alert_summary: AlertSummary = None,
        decision_support: DecisionSupport = None,
        store_comparison: StoreComparison = None,
    ) -> None:
        self._kpi = kpi_engine or KPIEngine()
        self._alerts = alert_summary or AlertSummary()
        self._decisions = decision_support or DecisionSupport()
        self._comparison = store_comparison or StoreComparison()

        # 注册默认告警源
        self._alerts.register_source(AlertSummary.generate_mock_alerts)

    def build_dashboard(
        self,
        store_id: str,
        include_comparison: bool = False,
        comparison_store_ids: Optional[List[str]] = None,
    ) -> DashboardData:
        """构建完整座舱数据."""
        # 1. 计算KPI
        kpis = self._kpi.calculate_all(store_id)

        # 2. 汇总告警
        alerts = self._alerts.summarize(store_id)

        # 3. 生成待办(从告警+KPI异常派生)
        todos = self._generate_todos(alerts, kpis)

        # 4. 生成决策建议
        suggestions = self._decisions.generate_suggestions(store_id, kpis, alerts)

        # 5. 门店对比(可选)
        comparison = None
        if include_comparison and comparison_store_ids:
            comparison = self._comparison.compare_stores(
                store_id, comparison_store_ids
            )

        dashboard = DashboardData(
            store_id=store_id,
            period_date=date.today(),
            todos=todos,
            kpis=kpis,
            alerts=alerts,
            suggestions=suggestions,
            comparison=comparison,
        )

        return dashboard

    @staticmethod
    def _generate_todos(alerts: List[AlertItem], kpis: List[KPIItem]) -> List[TodoItem]:
        """从告警和KPI异常生成待办事项."""
        todos: List[TodoItem] = []
        todo_idx = 1

        # 告警转待办
        for alert in alerts:
            if not alert.acknowledged and alert.level in (AlertLevel.CRITICAL, AlertLevel.WARNING):
                priority = Priority.CRITICAL if alert.level == AlertLevel.CRITICAL else Priority.HIGH
                todos.append(TodoItem(
                    todo_id=f"TODO-{todo_idx:03d}",
                    title=alert.title,
                    description=alert.message,
                    priority=priority,
                    category="alert",
                    source_agent=alert.source,
                    source_event_id=alert.alert_id,
                    action_text=alert.action_suggested,
                ))
                todo_idx += 1

        # KPI异常转待办
        for kpi in kpis:
            if kpi.status in ("warning", "critical"):
                todos.append(TodoItem(
                    todo_id=f"TODO-{todo_idx:03d}",
                    title=f"{kpi.name}需要关注",
                    description=f"当前值{kpi.value}{kpi.unit}，状态:{kpi.status}",
                    priority=Priority.HIGH if kpi.status == "critical" else Priority.MEDIUM,
                    category="kpi",
                    action_text=f"查看{kpi.name}详细分析",
                ))
                todo_idx += 1

        # 按优先级排序
        order = {Priority.CRITICAL: 0, Priority.HIGH: 1, Priority.MEDIUM: 2, Priority.LOW: 3}
        todos.sort(key=lambda t: order.get(t.priority, 9))

        return todos[:20]  # 最多20条待办
