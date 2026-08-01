#!/usr/bin/env python3
"""SOP合规引擎包 — 统一入口 (SC01-SC03).

模块:
- models: Pydantic数据模型(SOPRule, SOPTemplate, ComplianceReport, ViolationRecord等)
- checker: SOPChecker合规检查器(8种检查策略)
- template_manager: SOPTemplateManager模板管理(CRUD+SemVer版本控制)
- violation_tracker: ViolationTracker违规记录与追踪

对应架构设计 v1.1 §1.6 SOP合规引擎层.
"""

from .checker import SOPChecker
from .models import (
    CHECK_STRATEGIES,
    CheckStrategy,
    CheckpointResult,
    ComplianceReport,
    ComplianceTrend,
    PaginatedResult,
    Severity,
    SOPCategory,
    SOPRule,
    SOPTemplate,
    TemplateStatus,
    TemplateVersion,
    ViolationItem,
    ViolationRecord,
    ViolationStats,
    ViolationStatus,
    Zone,
)
from .template_manager import SOPTemplateManager
from .violation_tracker import ViolationTracker

__all__ = [
    # 核心类
    "SOPChecker",
    "SOPTemplateManager",
    "ViolationTracker",
    # 模型
    "SOPRule",
    "SOPTemplate",
    "ComplianceReport",
    "ComplianceTrend",
    "ViolationRecord",
    "ViolationStats",
    "ViolationItem",
    "CheckpointResult",
    "TemplateVersion",
    "PaginatedResult",
    # 枚举
    "Severity",
    "ViolationStatus",
    "TemplateStatus",
    "Zone",
    "CheckStrategy",
    "SOPCategory",
    # 常量
    "CHECK_STRATEGIES",
]
