#!/usr/bin/env python3
"""店长数字座舱包 — 统一入口 (A01-A05).

模块:
- models: Pydantic数据模型(DashboardData, KPIItem, TodoItem, AlertItem等)
- dashboard: DashboardAggregator(聚合器) + KPIEngine + AlertSummary + DecisionSupport + StoreComparison

对应PRD A01-A05.
"""

from .dashboard import (
    AlertSummary,
    DashboardAggregator,
    DecisionSupport,
    KPIEngine,
    KPI_DEFINITIONS,
    StoreComparison,
)
from .models import (
    AlertItem,
    AlertLevel,
    ComparisonResult,
    DashboardData,
    DecisionSuggestion,
    DeliveryTrackingItem,
    KPIItem,
    KitchenDashboardData,
    MetricTrend,
    PrepReminder,
    Priority,
    ProcurementDashboardData,
    PurchaseRecommendation,
    SOPDeviationItem,
    StoreMetric,
    SupplierComparison,
    TodoItem,
    TodoStatus,
    WasteAlertItem,
)

__all__ = [
    # 核心引擎
    "DashboardAggregator",
    "KPIEngine",
    "AlertSummary",
    "DecisionSupport",
    "StoreComparison",
    # 模型
    "DashboardData",
    "KPIItem",
    "TodoItem",
    "AlertItem",
    "DecisionSuggestion",
    "ComparisonResult",
    # 子模块数据
    "KitchenDashboardData",
    "ProcurementDashboardData",
    # 子模型
    "PrepReminder",
    "SOPDeviationItem",
    "WasteAlertItem",
    "PurchaseRecommendation",
    "SupplierComparison",
    "DeliveryTrackingItem",
    "StoreMetric",
    # 枚举
    "Priority",
    "TodoStatus",
    "AlertLevel",
    "MetricTrend",
    # 常量
    "KPI_DEFINITIONS",
]
