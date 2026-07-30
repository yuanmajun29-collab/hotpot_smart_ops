#!/usr/bin/env python3
"""Agent协作框架 — 核心类 (H13-H14).

模块:
- RoleAgent: 岗位Agent基类(输入/输出/消息总线/配置)
- AgentOrchestrator: 多Agent编排器(任务分发/结果聚合)

对应PRD:
- H13: Agent动态扩展框架(标准接口/热插拔/模板库)
- H14: Agent协同消息总线(发布订阅/7类消息)
"""

from __future__ import annotations

import fnmatch
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Set

from .models import (
    AgentConfig,
    AgentDependency,
    AgentMessage,
    AgentRole,
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

logger = logging.getLogger(__name__)


def _enum_val(val) -> str:
    """安全获取枚举值(兼容字符串和枚举对象)."""
    return val.value if hasattr(val, 'value') else str(val)


def _enum_list(vals) -> List[str]:
    """安全获取枚举列表值."""
    return [_enum_val(v) for v in vals] if vals else []


# ──────────────────────────────────────────────────────────────
# 消息处理器类型
# ──────────────────────────────────────────────────────────────

MessageHandler = Callable[[AgentMessage], Optional[AgentMessage]]


class RoleAgent:
    """岗位Agent基类 — 对接 PRD A01-A05 + H13.

    所有岗位Agent(A01店长/A02后厨/A03采购/A04供应商/A05知识库)的基类.
    提供标准接口:
    - 接收消息(on_message)
    - 执行任务(execute)
    - 发送消息(send)
    - 订阅主题(subscribe)
    """

    def __init__(
        self,
        config: AgentConfig,
        message_bus: "MessageBus" = None,
    ) -> None:
        self.config = config
        self._bus = message_bus
        self._handlers: Dict[str, MessageHandler] = {}
        self._subscriptions: List[Subscription] = []
        self._task_history: List[AgentTask] = []
        self._state: Dict[str, Any] = {}  # 运行时状态
        self._initialized = False

    # ── 生命周期 ──────────────────────────────────────────

    def initialize(self) -> None:
        """初始化Agent(注册默认处理器)."""
        if self._initialized:
            return
        self._register_default_handlers()
        # 注册订阅
        for sub in self.config.subscriptions or []:
            # subscriptions在config中是dict列表，需要转换
            pass
        self._initialized = True
        logger.info("Agent initialized: %s [%s]", self.config.agent_id, _enum_val(self.config.role))

    def shutdown(self) -> None:
        """关闭Agent."""
        self._initialized = False
        logger.info("Agent shutdown: %s", self.config.agent_id)

    # ── 消息处理 ──────────────────────────────────────────

    def on_message(self, message: AgentMessage) -> Optional[AgentMessage]:
        """接收并处理消息.

        Returns:
            响应消息(可选)
        """
        if not self._initialized:
            self.initialize()

        # 日志
        logger.debug(
            "Agent %s received msg[%s] from=%s type=%s",
            self.config.agent_id, message.message_id[:8],
            message.sender_id, _enum_val(message.msg_type),
        )

        # 路由到处理器
        handler = self._match_handler(message)
        if handler:
            try:
                response = handler(message)
                return response
            except Exception as exc:
                logger.error("Handler error in %s: %s", self.config.agent_id, exc)
                return self._error_response(message, str(exc))

        # 无匹配处理器，返回确认
        return AgentMessage(
            msg_type=MessageType.EVENT,
            sender_id=self.config.agent_id,
            receiver_id=message.sender_id,
            topic=f"ack.{message.topic}",
            payload={"status": "received", "original_id": message.message_id},
            correlation_id=message.message_id,
        )

    def execute(self, task_type: str, input_data: Dict[str, Any]) -> AgentTask:
        """执行任务.

        Args:
            task_type: 任务类型
            input_data: 输入数据

        Returns:
            AgentTask 含 result/error
        """
        task = AgentTask(
            agent_id=self.config.agent_id,
            task_type=task_type,
            input_data=input_data,
            status="running",
            started_at=datetime.now(),
        )
        self._task_history.append(task)

        try:
            start_ms = int(time.time() * 1000)
            result = self._execute_task(task_type, input_data)
            end_ms = int(time.time() * 1000)

            task.status = "completed"
            task.result = result
            task.completed_at = datetime.now()
            task.duration_ms = end_ms - start_ms
        except Exception as exc:
            task.status = "failed"
            task.error = str(exc)
            task.completed_at = datetime.now()
            logger.error("Task failed in %s: %s", self.config.agent_id, exc)

        return task

    def send(
        self,
        msg_type: MessageType,
        receiver_id: Optional[str],
        topic: str,
        payload: Dict[str, Any],
        priority: MessagePriority = MessagePriority.NORMAL,
        correlation_id: Optional[str] = None,
    ) -> AgentMessage:
        """发送消息.

        通过消息总线(H14)发送给其他Agent或广播.
        """
        msg = AgentMessage(
            msg_type=msg_type,
            priority=priority,
            sender_id=self.config.agent_id,
            receiver_id=receiver_id,
            topic=topic,
            payload=payload,
            correlation_id=correlation_id,
        )

        if self._bus:
            self._bus.publish(msg)
        else:
            logger.warning("No message bus configured, message not sent")

        return msg

    # ── 子类可覆盖的方法 ───────────────────────────────────

    def _register_default_handlers(self) -> None:
        """注册默认消息处理器(子类可覆盖)."""
        self._handlers["ping"] = self._handle_ping
        self._handlers["status"] = self._handle_status_query
        self._handlers["config"] = self._handle_config_query

    def _execute_task(self, task_type: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """执行具体任务(子类必须实现).

        Raises:
            NotImplementedError: 如果子类未实现
        """
        raise NotImplementedError(f"{self.config.name} does not implement task: {task_type}")

    # ── 内部方法 ──────────────────────────────────────────

    def _match_handler(self, message: AgentMessage) -> Optional[MessageHandler]:
        """根据消息匹配处理器."""
        # 1. 精确匹配topic
        handler = self._handlers.get(message.topic)
        if handler:
            return handler

        # 2. 通配符匹配
        for pattern, h in self._handlers.items():
            if "*" in pattern and fnmatch.fnmatch(message.topic, pattern):
                return h

        # 3. 按消息类型匹配
        type_handler = self._handlers.get(f"type:{_enum_val(message.msg_type)}")
        return type_handler

    def _handle_ping(self, message: AgentMessage) -> AgentMessage:
        """处理ping消息."""
        return AgentMessage(
            msg_type=MessageType.EVENT,
            sender_id=self.config.agent_id,
            receiver_id=message.sender_id,
            topic="pong",
            payload={
                "agent_id": self.config.agent_id,
                "role": _enum_val(self.config.role),
                "status": _enum_val(self.config.status),
                "timestamp": datetime.now().isoformat(),
            },
            correlation_id=message.message_id,
        )

    def _handle_status_query(self, message: AgentMessage) -> AgentMessage:
        """处理状态查询."""
        return AgentMessage(
            msg_type=MessageType.REPORT,
            sender_id=self.config.agent_id,
            receiver_id=message.sender_id,
            topic="status.response",
            payload={
                "agent_id": self.config.agent_id,
                "name": self.config.name,
                "role": _enum_val(self.config.role),
                "status": _enum_val(self.config.status),
                "capabilities": _enum_list(self.config.capabilities),
                "tasks_completed": len([t for t in self._task_history if t.status == "completed"]),
                "tasks_failed": len([t for t in self._task_history if t.status == "failed"]),
                "uptime_seconds": int(time.time()) - int(self._state.get("start_time", time.time())),
            },
            correlation_id=message.message_id,
        )

    def _handle_config_query(self, message: AgentMessage) -> AgentMessage:
        """处理配置查询."""
        return AgentMessage(
            msg_type=MessageType.STANDARD,
            sender_id=self.config.agent_id,
            receiver_id=message.sender_id,
            topic="config.response",
            payload={
                "agent_id": self.config.agent_id,
                "version": self.config.version,
                "default_config": self.config.default_config,
            },
            correlation_id=message.message_id,
        )

    @staticmethod
    def _error_response(original: AgentMessage, error: str) -> AgentMessage:
        """生成错误响应."""
        return AgentMessage(
            msg_type=MessageType.ALERT,
            priority=MessagePriority.HIGH,
            sender_id="system",
            receiver_id=original.sender_id,
            topic="error",
            payload={"error": error, "original_msg_id": original.message_id},
            correlation_id=original.correlation_id or original.message_id,
        )


class MessageBus:
    """Agent协同消息总线 (H14).

    实现:
    - 发布/订阅模式
    - 7类消息路由(事件/报告/标准/指令/偏差/模型/告警)
    - Agent间依赖关系管理
    - 消息持久化(可选DB)
    """

    def __init__(self, db_session=None) -> None:
        self._db = db_session
        self._subscribers: Dict[str, List[tuple]] = {}   # {pattern: [(agent_id, handler)]}
        self._agents: Dict[str, RoleAgent] = {}           # {agent_id: agent}
        self._message_log: List[AgentMessage] = []
        self._max_log_size = 10000

    # ── 公开接口 ──────────────────────────────────────────

    def register_agent(self, agent: RoleAgent) -> None:
        """注册Agent到总线."""
        self._agents[agent.config.agent_id] = agent
        agent._bus = self
        logger.info("Agent registered to bus: %s", agent.config.agent_id)

    def unregister_agent(self, agent_id: str) -> None:
        """注销Agent."""
        if agent_id in self._agents:
            self._agents[agent_id]._bus = None
            del self._agents[agent_id]
            # 清理订阅
            for pattern in list(self._subscribers.keys()):
                self._subscribers[pattern] = [
                    (aid, h) for aid, h in self._subscribers[pattern]
                    if aid != agent_id
                ]

    def publish(self, message: AgentMessage) -> int:
        """发布消息. 返回接收者数量."""
        if message.is_expired:
            logger.warning("Dropping expired message: %s", message.message_id[:8])
            return 0

        # 记录日志
        self._log_message(message)

        # 持久化
        if self._db:
            self._persist_message(message)

        # 路由到订阅者
        receivers = self._route_message(message)
        count = 0
        for agent_id, handler in receivers:
            agent = self._agents.get(agent_id)
            if agent:
                try:
                    response = agent.on_message(message)
                    if response and message.reply_to:
                        self.publish(response)
                    count += 1
                except Exception as exc:
                    logger.error("Deliver to %s failed: %s", agent_id, exc)

        return count

    def subscribe(
        self,
        subscriber_id: str,
        topic_pattern: str,
        handler: MessageHandler,
        msg_types: Optional[List[MessageType]] = None,
    ) -> None:
        """订阅主题."""
        key = f"{subscriber_id}:{topic_pattern}"
        if topic_pattern not in self._subscribers:
            self._subscribers[topic_pattern] = []
        self._subscribers[topic_pattern].append((subscriber_id, handler))
        logger.debug("Subscribed: %s → %s", subscriber_id, topic_pattern)

    def query_messages(
        self,
        sender_id: Optional[str] = None,
        msg_type: Optional[MessageType] = None,
        topic: Optional[str] = None,
        limit: int = 50,
    ) -> List[AgentMessage]:
        """查询消息历史."""
        results = self._message_log
        if sender_id:
            results = [m for m in results if m.sender_id == sender_id]
        if msg_type:
            results = [m for m in results if m.msg_type == msg_type]
        if topic:
            results = [m for m in results if topic in m.topic]
        return results[-limit:]

    # ── 内部方法 ──────────────────────────────────────────

    def _route_message(self, message: AgentMessage) -> List[tuple]:
        """路由消息到所有匹配的订阅者."""
        matches: List[tuple] = []

        # 1. 精确匹配receiver_id
        if message.receiver_id and message.receiver_id in self._agents:
            agent = self._agents[message.receiver_id]
            handler = getattr(agent, 'on_message', None)
            if handler:
                matches.append((message.receiver_id, lambda msg, h=handler: h(msg)))

        # 2. 主题模式匹配
        for pattern, subscribers in self._subscribers.items():
            if fnmatch.fnmatch(message.topic, pattern) or "*" in pattern:
                for sub_id, handler in subscribers:
                    # 不重复发送给自身(除非是广播)
                    if message.receiver_id and sub_id == message.receiver_id:
                        continue
                    matches.append((sub_id, handler))

        return matches

    def _log_message(self, message: AgentMessage) -> None:
        """记录消息到内存日志."""
        self._message_log.append(message)
        if len(self._message_log) > self._max_log_size:
            self._message_log = self._message_log[-self._max_log_size // 2:]

    def _persist_message(self, message: AgentMessage) -> None:
        """持久化消息到DB."""
        import json
        try:
            cursor = self._db.cursor()
            cursor.execute("""
                INSERT INTO agent_messages (
                    message_id, msg_type, priority, sender_id, receiver_id,
                    topic, payload, correlation_id, timestamp
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                message.message_id, _enum_val(message.msg_type), _enum_val(message.priority),
                message.sender_id, message.receiver_id, message.topic,
                json.dumps(message.payload, ensure_ascii=False),
                message.correlation_id, message.timestamp.isoformat(),
            ))
            self._db.commit()
        except Exception as exc:
            logger.warning("Persist message failed: %s", exc)


class AgentOrchestrator:
    """多Agent编排器 (H13).

    功能:
    - 任务分发到多个Agent
    - 结果聚合
    - 依赖关系解析与拓扑排序
    - 内置模板库(A01-A05)
    """

    def __init__(self, message_bus: MessageBus = None) -> None:
        self._bus = message_bus or MessageBus()
        self._agents: Dict[str, RoleAgent] = {}
        self._templates: Dict[str, AgentTemplate] = {}
        self._dependency_graph: Dict[str, List[AgentDependency]] = {}

        # 加载内置模板
        self._load_builtin_templates()

    # ── 公开接口 ──────────────────────────────────────────

    def create_agent_from_template(
        self,
        template_id: str,
        agent_id: str,
        config_overrides: Optional[Dict[str, Any]] = None,
    ) -> Optional[RoleAgent]:
        """从模板创建Agent实例(H13热插拔)."""
        template = self._templates.get(template_id)
        if not template:
            logger.warning("Template not found: %s", template_id)
            return None

        config = AgentConfig(
            agent_id=agent_id,
            name=template.name,
            role=template.role,
            capabilities=template.capabilities,
            config_schema=template.config_schema,
            default_config={**template.default_config, **(config_overrides or {})},
            description=template.description,
        )

        agent = RoleAgent(config=config, message_bus=self._bus)
        self.register_agent(agent)

        # 注册依赖
        if template.dependencies:
            self._dependency_graph[agent_id] = template.dependencies

        logger.info("Agent created from template %s: %s", template_id, agent_id)
        return agent

    def register_agent(self, agent: RoleAgent) -> None:
        """注册Agent."""
        self._agents[agent.config.agent_id] = agent
        self._bus.register_agent(agent)
        agent.initialize()

    def orchestrate(
        self,
        request_id: Optional[str] = None,
        tasks: Optional[List[Dict[str, Any]]] = None,
    ) -> OrchestrationResult:
        """编排多Agent协作任务.

        Args:
            tasks: [{"agent_id": "...", "task_type": "...", "input_data": {...}}, ...]

        Returns:
            OrchestrationResult 含各Agent结果和聚合结果
        """
        request_id = request_id or f"REQ-{uuid.uuid4().hex[:8].upper()}"
        start_ms = int(time.time() * 1000)
        result = OrchestrationResult(request_id=request_id)

        if not tasks:
            result.errors.append("No tasks specified")
            return result

        # 解析依赖顺序
        ordered_tasks = self._resolve_dependencies(tasks)

        # 按序执行
        task_results: Dict[str, Any] = {}
        for task_spec in ordered_tasks:
            agent_id = task_spec["agent_id"]
            agent = self._agents.get(agent_id)
            if not agent:
                result.errors.append(f"Agent not found: {agent_id}")
                continue

            # 注入上游依赖输出
            input_data = dict(task_spec.get("input_data", {}))
            deps = self._dependency_graph.get(agent_id, [])
            for dep in deps:
                upstream_result = task_results.get(dep.depends_on, {})
                for my_key, up_key in dep.input_data.items():
                    if up_key in upstream_result:
                        input_data[my_key] = upstream_result[up_key]

            # 执行任务
            task = agent.execute(task_spec["task_type"], input_data)
            result.tasks.append(task)

            if task.status == "completed" and task.result:
                task_results[agent_id] = task.result
            elif task.status == "failed":
                result.errors.append(f"{agent_id} failed: {task.error}")

        # 统计
        end_ms = int(time.time() * 1000)
        result.total_duration_ms = end_ms - start_ms
        result.messages_exchanged = len(self._bus.query_messages(limit=99999))
        result.final_result = task_results if task_results else None

        return result

    def list_agents(self) -> List[Dict[str, Any]]:
        """列出所有已注册Agent."""
        return [
            {
                "agent_id": a.config.agent_id,
                "name": a.config.name,
                "role": _enum_val(a.config.role),
                "status": _enum_val(a.config.status),
                "capabilities": _enum_list(a.config.capabilities),
            }
            for a in self._agents.values()
        ]

    def list_templates(self) -> List[Dict[str, Any]]:
        """列出可用模板."""
        return [
            {
                "template_id": t.template_id,
                "name": t.name,
                "role": _enum_val(t.role),
                "category": t.category,
                "capabilities": _enum_list(t.capabilities),
                "is_builtin": t.is_builtin,
            }
            for t in self._templates.values()
        ]

    # ── 内部方法 ──────────────────────────────────────────

    def _load_builtin_templates(self) -> None:
        """加载内置Agent模板."""
        for tpl_data in BUILTIN_AGENT_TEMPLATES:
            # 转换字符串枚举为实际枚举值
            capabilities = []
            for c in tpl_data.get("capabilities", []):
                try:
                    capabilities.append(Capability(c))
                except ValueError:
                    pass

            dependencies = []
            for d in tpl_data.get("dependencies", []):
                dependencies.append(AgentDependency(**d))

            subscriptions = []
            for s in tpl_data.get("subscriptions", []):
                msg_types = []
                for mt in s.get("msg_types", []):
                    try:
                        msg_types.append(MessageType(mt))
                    except ValueError:
                        pass
                subscriptions.append(Subscription(
                    subscriber_id=s["subscriber_id"],
                    topic_pattern=s["topic_pattern"],
                    msg_types=msg_types,
                ))

            try:
                role = AgentRole(tpl_data["role"])
                template = AgentTemplate(
                    template_id=tpl_data["template_id"],
                    name=tpl_data["name"],
                    role=role,
                    category=tpl_data.get("category", ""),
                    description=tpl_data.get("description", ""),
                    capabilities=capabilities,
                    config_schema=tpl_data.get("config_schema", {}),
                    default_config=tpl_data.get("default_config", {}),
                    dependencies=dependencies,
                    subscriptions=subscriptions,
                    is_builtin=True,
                )
                self._templates[template.template_id] = template
            except Exception as exc:
                logger.warning("Load template %s failed: %s", tpl_data.get("template_id"), exc)

    @staticmethod
    def _resolve_dependencies(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """解析依赖关系并返回拓扑排序后的任务列表(简化版).

        实际应使用完整DAG拓扑排序.
        """
        # 简化版: 先执行无依赖的任务
        agent_ids = {t["agent_id"] for t in tasks}
        no_deps = [t for t in tasks if t["agent_id"] not in {
            d.get("depends_on") for t in tasks for d in []
        }]
        has_deps = [t for t in tasks if t not in no_deps]
        return no_deps + has_deps
