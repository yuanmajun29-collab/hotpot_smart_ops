#!/usr/bin/env python3
"""店长数字座舱 — Pydantic数据模型 (A01-A05).

对应PRD:
- A01: 店长AI助理(今日待办/异常汇总/决策建议)
- A02: 后厨AI助理(备货提醒/SOP纠偏/废料预警)
- A03: 采购AI助理(采购清单/供应商比价/到货跟踪)
- A04: 供应商协同端
- A05: 知识库助理
"""

from __future__ import annotations

from datetime import date, datetime, time
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────
# 枚举类型
# ──────────────────────────────────────────────────────────────


class Priority(str, Enum):
    """待办优先级."""

    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class TodoStatus(str, Enum):
    """待办状态."""

    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    SKIPPED = "skipped"


class AlertLevel(str, Enum):
    """告警级别."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


class MetricTrend(str, Enum):
    """指标趋势."""

    UP = "up"           # 上升(好的方向, 如营收↑)
    DOWN = "down"       # 下降(坏的方向, 如损耗↓是好的)
    STABLE = "stable"
    UNKNOWN = "unknown"


# ──────────────────────────────────────────────────────────────
# 核心数据模型
# ──────────────────────────────────────────────────────────────


class TodoItem(BaseModel):
    """待办事项(A01核心)."""

    todo_id: str
    title: str
    description: str = ""
    priority: Priority = Priority.MEDIUM
    status: TodoStatus = TodoStatus.PENDING
    category: str = ""                 # sop / waste / inventory / procurement / quality
    source_agent: str = ""             # 来源Agent(A02/A03等)
    source_event_id: Optional[str] = None
    action_text: str = ""              # 建议动作
    due_time: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.now)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class KPIItem(BaseModel):
    """KPI指标项."""

    metric_id: str
    name: str                         # 如 "日营业额", "损耗率", "翻台率"
    value: float = 0.0
    unit: str = ""                    # 如 "¥", "%", "次"
    target: Optional[float] = None     # 目标值
    previous_value: Optional[float] = None  # 上期值(用于计算趋势)
    trend: MetricTrend = MetricTrend.UNKNOWN
    change_pct: float = 0.0            # 变化百分比
    status: str = "normal"             # normal / good / warning / critical
    details_url: Optional[str] = None


class AlertItem(BaseModel):
    """告警条目."""

    alert_id: str
    level: AlertLevel
    title: str
    message: str = ""
    source: str = ""                   # 来源模块
    source_id: Optional[str] = None
    detected_at: datetime = Field(default_factory=datetime.now)
    acknowledged: bool = False
    acknowledged_by: Optional[str] = None
    action_suggested: str = ""         # 建议处理动作
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DecisionSuggestion(BaseModel):
    """决策建议(A01核心)."""

    suggestion_id: str
    title: str
    description: str = ""
    category: str = ""                 # cost / revenue / quality / staffing
    impact_type: str = ""              # save / increase / reduce / improve
    impact_amount: float = 0.0         # 影响金额/百分比
    confidence: float = 0.5            # 置信度(0~1)
    data_sources: List[str] = Field(default_factory=list)  # 数据来源
    action_steps: List[str] = Field(default_factory=list)  # 建议步骤
    priority: Priority = Priority.MEDIUM
    expires_at: Optional[datetime] = None


class StoreMetric(BaseModel):
    """门店指标(用于对比)."""

    store_id: str
    store_name: str = ""
    metrics: Dict[str, float] = Field(default_factory=dict)   # {metric_id: value}
    period_start: Optional[date] = None
    period_end: Optional[date] = None


class ComparisonResult(BaseModel):
    """门店对比结果."""

    primary_store_id: str
    comparison_date: date
    stores: List[StoreMetric] = Field(default_factory=list)
    rankings: Dict[str, List[str]] = Field(default_factory=dict)  # {metric_id: [store_id按排名]}
    anomalies: List[Dict[str, Any]] = Field(default_factory=list)  # 异常门店


class DashboardData(BaseModel):
    """完整座舱数据(A01聚合输出)."""

    store_id: str
    generated_at: datetime = Field(default_factory=datetime.now)
    period_date: Optional[date] = None

    # 核心区域
    todos: List[TodoItem] = Field(default_factory=list)          # 今日待办
    kpis: List[KPIItem] = Field(default_factory=list)            # KPI指标
    alerts: List[AlertItem] = Field(default_factory=list)        # 告警汇总
    suggestions: List[DecisionSuggestion] = Field(default_factory=list)  # 决策建议

    # 辅助数据
    comparison: Optional[ComparisonResult] = None                # 门店对比
    trend_data: Dict[str, List[Dict[str, Any]]] = Field(default_factory=dict)  # 趋势数据

    @property
    def critical_todo_count(self) -> int:
        return sum(1 for t in self.todos if t.priority == Priority.CRITICAL and t.status != TodoStatus.COMPLETED)

    @property
    def active_alert_count(self) -> int:
        return sum(1 for a in self.alerts if not a.acknowledged and a.level in (AlertLevel.CRITICAL, AlertLevel.WARNING))

    @property
    def overall_health_score(self) -> float:
        """综合健康分(0~100)."""
        if not self.kpis:
            return 50.0
        scores = []
        for kpi in self.kpis:
            if kpi.status == "good":
                scores.append(100)
            elif kpi.status == "normal":
                scores.append(75)
            elif kpi.status == "warning":
                scores.append(50)
            else:
                scores.append(25)
        return round(sum(scores) / len(scores), 1) if scores else 50.0


# ──────────────────────────────────────────────────────────────
# A02 后厨助理专用模型
# ──────────────────────────────────────────────────────────────


class PrepReminder(BaseModel):
    """备货提醒."""

    item_name: str
    current_stock: float = 0.0
    suggested_qty: float = 0.0
    unit: str = ""
    reason: str = ""                   # 预测需求/历史均值
    urgency: Priority = Priority.LOW


class SOPDeviationItem(BaseModel):
    """SOP偏差项."""

    rule_name: str
    zone: str = ""
    deviation_type: str = ""           # violation / warning / info
    detected_at: datetime = Field(default_factory=datetime.now)
    suggested_correction: str = ""


class WasteAlertItem(BaseModel):
    """废料预警."""

    item_name: str
    waste_amount: float = 0.0
    unit: str = ""
    estimated_cost: float = 0.0
    trend: str = ""                    # increasing / stable / decreasing
    suggested_action: str = ""


class KitchenDashboardData(BaseModel):
    """后厨座舱数据(A02)."""

    store_id: str
    prep_reminders: List[PrepReminder] = Field(default_factory=list)
    sop_deviations: List[SOPDeviationItem] = Field(default_factory=list)
    waste_alerts: List[WasteAlertItem] = Field(default_factory=list)
    compliance_score: float = 0.0      # SOP合规分
    shift_summary: str = ""            # 班次摘要


# ──────────────────────────────────────────────────────────────
# A03 采购助理专用模型
# ──────────────────────────────────────────────────────────────


class PurchaseRecommendation(BaseModel):
    """采购建议."""

    item_name: str
    supplier: str = ""
    suggested_qty: float = 0.0
    unit: str = ""
    estimated_cost: float = 0.0
    urgency: str = ""                  # normal / urgent / expedite
    reason: str = ""                   # 预测/安全库存/促销
    alternatives: List[Dict[str, str]] = Field(default_factory=list)  # 备选供应商


class SupplierComparison(BaseModel):
    """供应商比价."""

    item_name: str
    suppliers: List[Dict[str, Any]] = Field(default_factory=list)  # [{name, price, quality_score, delivery_days}]
    recommended: str = ""              # 推荐供应商
    savings_potential: float = 0.0     # 潜在节省


class DeliveryTrackingItem(BaseModel):
    """到货跟踪."""

    po_id: str
    supplier: str = ""
    items: List[str] = Field(default_factory=list)
    expected_date: Optional[date] = None
    status: str = ""                   # pending / shipped / delivered / delayed
    actual_date: Optional[date] = None
    delay_days: int = 0


class ProcurementDashboardData(BaseModel):
    """采购座舱数据(A03)."""

    store_id: str
    purchase_recommendations: List[PurchaseRecommendation] = Field(default_factory=list)
    supplier_comparisons: List[SupplierComparison] = Field(default_factory=list)
    delivery_tracking: List[DeliveryTrackingItem] = Field(default_factory=list)
    total_estimated_cost: float = 0.0
    budget_remaining: float = 0.0
    period_spend_trend: List[Dict[str, Any]] = Field(default_factory=list)
