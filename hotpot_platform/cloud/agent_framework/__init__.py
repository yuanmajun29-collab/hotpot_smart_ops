#!/usr/bin/env python3
"""Agent协作框架包 — 统一入口 (H13-H14).

模块:
- models: Pydantic数据模型(AgentConfig, AgentMessage, AgentTask, OrchestrationResult等)
- orchestrator: RoleAgent(岗位Agent基类) + AgentOrchestrator(多Agent编排器) + MessageBus(消息总线)
- action_types: ActionType枚举 + RiskLevel + PermissionMatrix权限矩阵 (P0-2 Gateway)
- agent_gateway: AgentGatewayMiddleware中间件 + 审计日志 (P0-2 Gateway)

对应PRD:
- H13: Agent动态扩展框架
- H14: Agent协同消息总线
- P0-2: Agent Gateway行动权限控制中间件
"""

from .models import (
    AgentConfig,
    AgentDependency,
    AgentMessage,
    AgentStatus,
    AgentTask,
    AgentTemplate,
    BUILTIN_AGENT_TEMPLATES,
    Capability,
    MessageType,
    MessagePriority,
    OrchestrationResult,
    Subscription,
)
from .orchestrator import (
    AgentOrchestrator,
    MessageBus,
    RoleAgent,
)

# 基础 __all__ 定义 (在 try 块之前，避免 NameError)
__all__ = [
    # 核心类
    "RoleAgent",
    "AgentOrchestrator",
    "MessageBus",
    # 模型
    "AgentConfig",
    "AgentMessage",
    "AgentTask",
    "AgentTemplate",
    "OrchestrationResult",
    "Subscription",
    "AgentDependency",
    # 枚举
    "AgentStatus",
    "MessageType",
    "MessagePriority",
    "Capability",
    # 常量
    "BUILTIN_AGENT_TEMPLATES",
]

# P0-2 Agent Gateway 模块导出
try:
    from .action_types import (
        ActionType,
        RiskLevel,
        PermissionMatrix,
        PermissionDeniedError,
        ActionNotAllowedError,
        ApprovalRequiredError,
        get_action_risk_description,
    )
    from .agent_gateway import (
        AgentGatewayMiddleware,
        AuditLogger,
        AuditRecord,
        get_gateway,
        execute_agent_action,
        get_gateway_status,
    )

    __all__ += [
        # ActionType & 权限系统
        "ActionType",
        "RiskLevel",
        "PermissionMatrix",
        "PermissionDeniedError",
        "ActionNotAllowedError",
        "ApprovalRequiredError",
        "get_action_risk_description",
        # Gateway 核心
        "AgentGatewayMiddleware",
        "AuditLogger",
        "AuditRecord",
        "get_gateway",
        "execute_agent_action",
        "get_gateway_status",
    ]
except ImportError:
    # Gateway模块可选，缺失时降级运行
    pass

# 四类岗位 Agent (Step 3: Agent Gateway 统一)
try:
    from .agents import (
        StoreManagerAgent,
        KitchenAgent,
        ProcurementAgent,
        FrontHallAgent,
        create_agent,
        create_all_agents,
        AGENT_REGISTRY,
    )

    __all__ += [
        "StoreManagerAgent",
        "KitchenAgent",
        "ProcurementAgent",
        "FrontHallAgent",
        "create_agent",
        "create_all_agents",
        "AGENT_REGISTRY",
    ]
except ImportError:
    pass
