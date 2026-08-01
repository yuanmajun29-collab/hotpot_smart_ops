#!/usr/bin/env python3
"""Agent协作框架包 — 统一入口 (H13-H14).

模块:
- models: Pydantic数据模型(AgentConfig, AgentMessage, AgentTask, OrchestrationResult等)
- orchestrator: RoleAgent(岗位Agent基类) + AgentOrchestrator(多Agent编排器) + MessageBus(消息总线)

对应PRD:
- H13: Agent动态扩展框架
- H14: Agent协同消息总线
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
