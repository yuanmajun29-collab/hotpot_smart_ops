#!/usr/bin/env python3
"""Agent协作框架 — Pydantic数据模型 (H13-H14).

对应PRD:
- H13: Agent动态扩展框架(标准接口/热插拔/模板库/版本管理)
- H14: Agent协同消息总线(发布订阅/7类消息/依赖配置)
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ──────────────────────────────────────────────────────────────
# 枚举类型
# ──────────────────────────────────────────────────────────────


class AgentRole(str, Enum):
    """Agent角色(对应A01-A05)."""

    STORE_MANAGER = "store_manager"     # A01 店长助理
    KITCHEN = "kitchen"                 # A02 后厨助理
    PROCUREMENT = "procurement"         # A03 采购助理
    SUPPLIER = "supplier"               # A04 供应商端
    KNOWLEDGE = "knowledge"             # A05 知识库助理
    REGIONAL = "regional"               # H05 区域运营
    STRATEGY = "strategy"                # H03 战略Agent
    AUDIT = "audit"                     # H04 审计Agent


class AgentStatus(str, Enum):
    """Agent状态."""

    ACTIVE = "active"
    PAUSED = "paused"
    STOPPED = "stopped"
    ERROR = "error"


class MessageType(str, Enum):
    """消息类型(H14定义的7类消息)."""

    EVENT = "event"                     # 事件消息(如废料检测)
    REPORT = "report"                   # 报告消息(如损耗日报)
    STANDARD = "standard"               # 标准消息(如SOP更新)
    COMMAND = "command"                 # 指令消息(如调整订货量)
    DEVIATION = "deviation"             # 偏差消息(如超标预警)
    MODEL = "model"                     # 模型消息(如预测结果更新)
    ALERT = "alert"                     # 告警消息(如温度异常)


class MessagePriority(str, Enum):
    """消息优先级."""

    CRITICAL = "critical"
    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"


class Capability(str, Enum):
    """Agent能力类型."""

    MONITOR = "monitor"                # 监控
    ANALYZE = "analyze"                # 分析
    PREDICT = "predict"                # 预测
    RECOMMEND = "recommend"            # 推荐
    EXECUTE = "execute"                # 执行
    NOTIFY = "notify"                  # 通知
    APPROVE = "approve"                # 审批
    QUERY = "query"                    # 查询


# ──────────────────────────────────────────────────────────────
# 核心数据模型
# ──────────────────────────────────────────────────────────────


class SimulationMode(str, Enum):
    """模拟模式枚举 - 用于区分演示/生产环境"""
    OFF = "off"           # 生产模式：使用真实数据源
    DEMO = "demo"         # 演示模式：使用模拟数据，带 [SIMULATION] 标记
    EXPO = "expo"         # 展会模式：高度逼真的模拟数据，无标记


class AgentConfig(BaseModel):
    """Agent配置."""

    agent_id: str = Field(..., description="Agent唯一ID")
    name: str = Field(..., description="显示名称")
    role: AgentRole = Field(..., description="角色")
    version: str = Field("1.0.0", description="版本号")
    status: AgentStatus = Field(AgentStatus.ACTIVE)
    capabilities: List[Capability] = Field(default_factory=list, description="能力列表")
    config_schema: Dict[str, Any] = Field(default_factory=dict, description="配置参数Schema")
    default_config: Dict[str, Any] = Field(default_factory=dict, description="默认配置值")
    subscriptions: List[Any] = Field(default_factory=list, description="消息订阅列表")
    description: str = ""
    author: str = "system"
    simulation_mode: SimulationMode = Field(
        default=SimulationMode.DEMO,
        description="模拟模式: off=生产, demo=演示(有标记), expo=展会(无标记)"
    )
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)

    class Config:
        use_enum_values = True


class AgentMessage(BaseModel):
    """Agent间消息(H14消息总线)."""

    message_id: str = Field(default_factory=lambda: f"MSG-{__import__('uuid').uuid4().hex[:10].upper()}")
    msg_type: MessageType
    priority: MessagePriority = MessagePriority.NORMAL
    sender_id: str                       # 发送方Agent ID
    receiver_id: Optional[str] = None     # 接收方(None=广播)
    topic: str = ""                       # 主题(用于路由)
    payload: Dict[str, Any] = Field(default_factory=dict)  # 消息体
    correlation_id: Optional[str] = None  # 关联ID(用于请求-响应)
    reply_to: Optional[str] = None        # 响应目标
    timestamp: datetime = Field(default_factory=datetime.now)
    ttl_seconds: int = 3600               # 存活时间(秒)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True

    @property
    def is_expired(self) -> bool:
        """检查是否过期."""
        age = (datetime.now() - self.timestamp).total_seconds()
        return age > self.ttl_seconds


class AgentTask(BaseModel):
    """Agent任务."""

    task_id: str = Field(default_factory=lambda: f"TASK-{__import__('uuid').uuid4().hex[:10].upper()}")
    agent_id: str
    task_type: str                      # 任务类型
    input_data: Dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"              # pending / running / completed / failed
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.now)
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    duration_ms: int = 0


class AgentDependency(BaseModel):
    """Agent间依赖关系."""

    agent_id: str
    depends_on: str                     # 依赖的Agent ID
    dependency_type: str = "output"      # output(输出作为输入) / trigger(触发执行)
    input_mapping: Dict[str, str] = Field(default_factory=dict)  # {my_param: upstream_output_key}


class Subscription(BaseModel):
    """消息订阅."""

    subscriber_id: str                  # 订阅者Agent ID
    topic_pattern: str                   # 主题模式(支持通配符*)
    msg_types: List[MessageType] = Field(default_factory=list)   # 消息类型过滤
    handler_name: str = ""               # 处理方法名


class AgentTemplate(BaseModel):
    """Agent模板库(H13模板系统)."""

    template_id: str
    name: str
    role: AgentRole
    category: str = ""                  # 如 "运营监控", "采购决策", "品质审计"
    description: str = ""
    capabilities: List[Capability] = Field(default_factory=list)
    config_schema: Dict[str, Any] = Field(default_factory=dict)
    default_config: Dict[str, Any] = Field(default_factory=dict)
    dependencies: List[AgentDependency] = Field(default_factory=list)
    subscriptions: List[Subscription] = Field(default_factory=list)
    version: str = "1.0.0"
    is_builtin: bool = False            # 是否内置模板


class OrchestrationResult(BaseModel):
    """编排结果."""

    request_id: str
    tasks: List[AgentTask] = Field(default_factory=list)
    messages_exchanged: int = 0
    total_duration_ms: int = 0
    final_result: Optional[Dict[str, Any]] = None
    errors: List[str] = Field(default_factory=list)


# ──────────────────────────────────────────────────────────────
# 预置Agent模板 (H13模板库)
# ──────────────────────────────────────────────────────────────

BUILTIN_AGENT_TEMPLATES: List[Dict[str, Any]] = [
    {
        "template_id": "TPL-A01-MANAGER",
        "name": "店长AI助理",
        "role": "store_manager",
        "category": "运营监控",
        "description": "聚合今日待办、异常汇总、决策建议，支持一键处理(A01)",
        "capabilities": ["monitor", "analyze", "recommend", "notify"],
        "default_config": {
            "auto_summarize": True,
            "priority_threshold": "high",
            "include_predictions": True,
        },
        "dependencies": [
            {"agent_id": "A01", "depends_on": "A02", "dependency_type": "output"},
            {"agent_id": "A01", "depends_on": "A03", "dependency_type": "output"},
        ],
        "subscriptions": [
            {"subscriber_id": "A01", "topic_pattern": "sop.*", "msg_types": ["alert", "event"]},
            {"subscriber_id": "A01", "topic_pattern": "waste.*", "msg_types": ["event", "report"]},
            {"subscriber_id": "A01", "topic_pattern": "inventory.*", "msg_types": ["alert", "deviation"]},
        ],
    },
    {
        "template_id": "TPL-A02-KITCHEN",
        "name": "后厨AI助理",
        "role": "kitchen",
        "category": "运营监控",
        "description": "推送备货提醒、SOP纠偏、废料预警(A02)",
        "capabilities": ["monitor", "notify", "recommend"],
        "default_config": {
            "sop_alert_enabled": True,
            "waste_alert_enabled": True,
            "prep_reminder_enabled": True,
        },
        "dependencies": [],
        "subscriptions": [
            {"subscriber_id": "A02", "topic_pattern": "sop.*", "msg_types": ["event", "alert"]},
            {"subscriber_id": "A02", "topic_pattern": "vision.waste.*", "msg_types": ["event"]},
            {"subscriber_id": "A02", "topic_pattern": "kitchen.prep.*", "msg_types": ["event"]},
        ],
    },
    {
        "template_id": "TPL-A03-PROCUREMENT",
        "name": "采购AI助理",
        "role": "procurement",
        "category": "采购决策",
        "description": "推送采购清单确认、供应商比价、到货跟踪(A03)",
        "capabilities": ["analyze", "predict", "recommend", "query"],
        "default_config": {
            "auto_generate_po": False,
            "supplier_comparison": True,
            "delivery_tracking": True,
        },
        "dependencies": [
            {"agent_id": "A03", "depends_on": "N01", "dependency_type": "output"},
            {"agent_id": "A03", "depends_on": "N02", "dependency_type": "output"},
        ],
        "subscriptions": [
            {"subscriber_id": "A03", "topic_pattern": "forecast.*", "msg_types": ["model"]},
            {"subscriber_id": "A03", "topic_pattern": "inventory.*", "msg_types": ["deviation"]},
            {"subscriber_id": "A03", "topic_pattern": "supply_chain.*", "msg_types": ["report"]},
        ],
    },
    {
        "template_id": "TPL-A05-KNOWLEDGE",
        "name": "知识库助理",
        "role": "knowledge",
        "category": "知识服务",
        "description": "SOP问答和操作指引知识库，支持自然语言查询(A05)",
        "capabilities": ["query", "notify"],
        "default_config": {
            "knowledge_scope": "all",
            "auto_suggest": True,
        },
        "dependencies": [],
        "subscriptions": [],
    },
]
