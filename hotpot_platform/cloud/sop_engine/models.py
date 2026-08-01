#!/usr/bin/env python3
"""SOP合规引擎 — Pydantic数据模型 (SC01-SC03).

对应架构设计 v1.1 §1.6 SOP合规引擎层.
覆盖: SOPRule, SOPTemplate, ComplianceReport, ViolationRecord 等.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────
# 枚举类型
# ──────────────────────────────────────────────────────────────


class Severity(str, Enum):
    """违规严重程度."""

    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"
    INFO = "info"


class ViolationStatus(str, Enum):
    """违规处理状态."""

    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    RESOLVED = "resolved"


class TemplateStatus(str, Enum):
    """模板状态."""

    DRAFT = "draft"
    ACTIVE = "active"
    ARCHIVED = "archived"


class Zone(str, Enum):
    """检查区域."""

    KITCHEN = "kitchen"
    WAREHOUSE = "warehouse"
    FRONT = "front"
    DINING = "dining"


class CheckStrategy(str, Enum):
    """检查策略ID."""

    MASK_DETECT = "mask_detect"           # 口罩佩戴检测(视觉)
    HAND_WASH = "hand_wash"               # 洗手合规(视觉+IoT)
    TEMP_MONITOR = "temp_monitor"         # 温控合规(IoT)
    FEFO_CHECK = "fefo_check"             # FEFO先失效先出(RFID+库存)
    TABLE_CLEANUP = "table_cleanup"       # 桌面清洁(视觉)
    GREETING_STD = "greeting_std"         # 迎宾标准(视觉)
    UNIFORM_CHECK = "uniform_check"       # 着装规范(视觉)
    FOOD_SAFETY = "food_safety"          # 食品安全(综合)


class SOPCategory(str, Enum):
    """SOP分类."""

    KITCHEN_HYGIENE = "kitchen_hygiene"     # 厨房卫生
    FOOD_SAFETY_CAT = "food_safety"         # 食品安全
    SERVICE_STD = "service_std"             # 服务标准
    WAREHOUSE_OP = "warehouse_op"           # 仓库操作
    PREP_STD = "prep_std"                   # 备料标准


# ──────────────────────────────────────────────────────────────
# 核心数据模型
# ──────────────────────────────────────────────────────────────


class SOPRule(BaseModel):
    """SOP规则定义.

    对应架构 §1.6 CHECK_STRATEGIES 注册表.
    """

    rule_id: str = Field(..., description="规则ID, 如 SOP-KITCHEN-001")
    name: str = Field(..., description="规则名称")
    description: str = Field("", description="自然语言描述")
    severity: Severity = Field(Severity.MINOR, description="严重程度")
    check_strategy: CheckStrategy = Field(..., description="检查策略")
    threshold: Optional[Dict[str, Any]] = Field(None, description="策略参数")
    corrective_action: str = Field("", description="纠正动作指引")
    evidence_required: bool = Field(True, description="是否需要证据")
    category: SOPCategory = Field(SOPCategory.KITCHEN_HYGIENE, description="SOP分类")
    zone: Zone = Field(Zone.KITCHEN, description="适用区域")
    enabled: bool = Field(True, description="是否启用")


class SOPTemplate(BaseModel):
    """SOP模板.

    对应架构 §1.6.2 SOPTemplateManager.
    支持SemVer版本控制.
    """

    template_id: str = Field(..., description="模板ID")
    name: str = Field(..., description="模板名称")
    category: SOPCategory = Field(..., description="分类")
    zone: Zone = Field(..., description="适用区域")
    rules: List[SOPRule] = Field(default_factory=list, description="规则列表")
    version: str = Field("1.0.0", description="SemVer版本号")
    status: TemplateStatus = Field(TemplateStatus.DRAFT, description="状态")
    author: str = Field("system", description="创建人")
    store_scope: Optional[str] = Field(None, description="门店范围(None=全连锁)")
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    updater: str = Field("")

    class Config:
        use_enum_values = True


class TemplateVersion(BaseModel):
    """模板版本历史记录."""

    version: str
    changed_by: str
    changed_at: datetime
    change_summary: str
    rule_count: int


class CheckpointResult(BaseModel):
    """单个检查点结果."""

    checkpoint_id: str
    name: str
    check_type: str  # vision / iot / manual / rfid
    passed: bool
    actual_value: Optional[Any] = None
    expected_value: Optional[Any] = None
    evidence_ref: Optional[str] = None  # 事件ID/照片路径
    message: str = ""


class ViolationItem(BaseModel):
    """单个违规项."""

    rule_id: str
    rule_name: str
    severity: Severity
    zone: Zone
    evidence_ref: str = ""
    suggested_action: str = ""
    detected_at: datetime = Field(default_factory=datetime.now)


class ComplianceReport(BaseModel):
    """合规检查报告.

    对应架构 §1.6.1 SOPChecker.check() 返回值.
    """

    store_id: str
    zone: Zone
    checked_at: datetime = Field(default_factory=datetime.now)
    total_rules: int = 0
    passed_count: int = 0
    failed_count: int = 0
    pending_count: int = 0
    compliance_score: float = Field(0.0, description="0~100合规分")
    checkpoints: List[CheckpointResult] = Field(default_factory=list)
    violations: List[ViolationItem] = Field(default_factory=list)

    @property
    def pass_rate(self) -> float:
        if self.total_rules == 0:
            return 100.0
        return round(self.passed_count / self.total_rules * 100, 1)


class ComplianceTrend(BaseModel):
    """合规趋势.

    对应架构 §1.6.1 SOPChecker.get_compliance_trend() 返回值.
    """

    store_id: str
    period_days: int
    daily_scores: List[Dict[str, Any]] = Field(default_factory=list)
    avg_score: float = 0.0
    worst_zone: str = ""
    improvement_pct: float = 0.0
    top_violations: List[Dict[str, Any]] = Field(default_factory=list)


class ViolationRecord(BaseModel):
    """违规记录.

    对应架构 §1.6.3 ViolationTracker.
    """

    violation_id: str = Field(..., description="违规记录ID")
    report: Optional[ComplianceReport] = None  # 关联的合规报告(可选，DB中不持久化)
    severity: Severity
    status: ViolationStatus = Field(ViolationStatus.OPEN)
    store_id: str
    zone: Zone
    rule_id: str
    rule_name: str
    detected_at: datetime = Field(default_factory=datetime.now)
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[str] = None
    ack_note: str = ""
    corrective_evidence: Optional[str] = None  # 纠正照片
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None
    auto_acknowledged: bool = False  # minor级别自动确认

    class Config:
        use_enum_values = True


class ViolationStats(BaseModel):
    """违规统计.

    对应架构 §1.6.3 ViolationTracker.getViolationStats().
    """

    store_id: str
    period_days: int
    total_violations: int = 0
    by_severity: Dict[str, int] = Field(default_factory=dict)
    by_category: Dict[str, int] = Field(default_factory=dict)
    avg_resolution_hours: float = 0.0
    repeat_rate: float = 0.0  # 同一规则重复违规率
    top_3_repeat_rules: List[Dict[str, Any]] = Field(default_factory=list)


class PaginatedResult(BaseModel):
    """通用分页结果."""

    items: List[Any] = Field(default_factory=list)
    total: int = 0
    page: int = 1
    size: int = 20
    pages: int = 0

    def __init__(self, **data: Any) -> None:
        super().__init__(**data)
        if self.size > 0:
            self.pages = (self.total + self.size - 1) // self.size


# ──────────────────────────────────────────────────────────────
# 预置检查策略配置
# ──────────────────────────────────────────────────────────────

CHECK_STRATEGIES: Dict[str, Dict[str, Any]] = {
    "mask_detect": {
        "name": "口罩佩戴检测",
        "zone": Zone.KITCHEN,
        "evidence_type": "vision",
        "description": "厨房区域内人脸未检测到口罩 → 违规",
        "default_threshold": {"min_confidence": 0.8},
    },
    "hand_wash": {
        "name": "洗手合规",
        "zone": Zone.KITCHEN,
        "evidence_type": "vision+iot",
        "description": "进入操作台前30s内无洗手记录 → 违规",
        "default_threshold": {"window_sec": 30},
    },
    "temp_monitor": {
        "name": "温控合规",
        "zone": Zone.WAREHOUSE,
        "evidence_type": "iot",
        "description": "冷链温度 > 阈值持续 > 15min → 违规",
        "default_threshold": {"alarm_duration_sec": 900},
    },
    "fefo_check": {
        "name": "FEFO先失效先出",
        "zone": Zone.WAREHOUSE,
        "evidence_type": "rfid+inventory",
        "description": "出库批次非最早过期 → 违规",
        "default_threshold": {},
    },
    "table_cleanup": {
        "name": "桌面清洁",
        "zone": Zone.FRONT,
        "evidence_type": "vision",
        "description": "顾客离桌 > 10min 未清理 → 提醒",
        "default_threshold": {"idle_min": 10},
    },
    "greeting_std": {
        "name": "迎宾标准",
        "zone": Zone.FRONT,
        "evidence_type": "vision",
        "description": "顾客进门 > 30s 无迎宾 → 提醒",
        "default_threshold": {"response_sec": 30},
    },
    "uniform_check": {
        "name": "着装规范",
        "zone": Zone.KITCHEN,
        "evidence_type": "vision",
        "description": "员工未按标准着装 → 违规",
        "default_threshold": {},
    },
    "food_safety": {
        "name": "食品安全",
        "zone": Zone.KITCHEN,
        "evidence_type": "comprehensive",
        "description": "留样/保质期/温度超标等综合检测",
        "default_threshold": {},
    },
}
