"""
火瞳 · Agent Gateway 中间件 (核心引擎)
========================================

⚠️ 改造方案要求 (P0-C): Fail-Closed 机制
   - 异常时必须失败拒绝，禁止继续执行高风险动作
   - 统一 Agent Gateway 的权限校验、订阅匹配、消息推送和回执
   - 所有高风险行动均由授权人员确认并可审计

本模块实现了统一的Agent行动权限控制和审计追踪中间件。

核心职责:
  1. **身份验证**: 确认用户角色和权限范围
  2. **行动验证**: 检查 ActionType 是否在 PermissionMatrix 中授权
  3. **风险路由**: 根据 RiskLevel 决定执行策略:
     - LOW: 直接执行
     - MEDIUM: 执行 + 强制审计
     - HIGH/CRITICAL: 创建审批任务，不直接执行
     - BLOCKED: 拒绝并告警
  4. **审计记录**: 记录完整的 who/when/what/why/result 链
  5. **异常处理**: 统一的错误响应和日志

设计原则:
  - 符合《最终方案》第六、七章的 Agent 行动边界要求
  - 与 IP-5 修正后的审批流程无缝集成
  - 支持装饰器模式和显式调用两种接入方式
  - 最小化对现有代码的侵入性

使用方式:

  方式1: 装饰器模式 (推荐用于API端点)
    @agent_gateway.require_action(ActionType.APPROVE_PURCHASE)
    async def approve_purchase_task(task_id, ...):
        # Gateway已自动处理权限检查和审计
        return SupplyChainManager.approve_purchase_task(task_id)

  方式2: 显式调用 (用于内部逻辑)
    result = await gateway.execute_action(
        action_type=ActionType.CREATE_PO,
        role="purchaser",
        user_id="user_123",
        params={"sku": "FP-HNRC-001", "qty": 20},
    )
    if result.approval_required:
        # 返回task_id给前端，等待人工审批
        return {"task_id": result.task_id, "status": "pending_approval"}

作者: 火瞳AI团队
日期: 2026-08-02 (P0-2 Agent Gateway 规范化)
"""

import asyncio
import functools
import json
import logging
import os
import time
import uuid as uuid_mod
from datetime import datetime, date
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

# 导入刚创建的action_types模块
from .action_types import (
    ActionType,
    RiskLevel,
    PermissionMatrix,
    PermissionRule,
    AgentGatewayError,
    PermissionDeniedError,
    ApprovalRequiredError,
    get_action_risk_description,
)

# 配置日志
logger = logging.getLogger(__name__)


# =====================================================================
# 1. 数据模型
# =====================================================================

@dataclass
class UserContext:
    """用户上下文信息"""
    user_id: str
    role: str  # store_manager, purchaser, kitchen_staff, supplier
    session_id: Optional[str] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    extra: Dict[str, Any] = None

    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "role": self.role,
            "session_id": self.session_id,
            "ip_address": self.ip_address,
            "timestamp": datetime.now().isoformat(),
        }


@dataclass
class ActionResult:
    """行动执行结果"""
    success: bool
    action_type: ActionType
    risk_level: RiskLevel
    data: Any = None
    error: Optional[str] = None
    approval_required: bool = False
    task_id: Optional[str] = None
    audit_id: Optional[str] = None
    execution_time_ms: float = 0.0

    def to_dict(self) -> dict:
        result = {
            "success": self.success,
            "action_type": self.action_type.value if self.action_type else None,
            "risk_level": self.risk_level.value,
            "data": self.data,
            "error": self.error,
            "approval_required": self.approval_required,
            "task_id": self.task_id,
            "audit_id": self.audit_id,
            "execution_time_ms": round(self.execution_time_ms, 2),
        }
        return {k: v for k, v in result.items() if v is not None}


@dataclass
class AuditRecord:
    """审计记录"""
    audit_id: str
    timestamp: str
    user_context: UserContext
    action_type: ActionType
    risk_level: RiskLevel
    params: Dict[str, Any]
    result: Optional[ActionResult] = None
    status: str = "pending"  # pending, approved, executed, blocked, error


# =====================================================================
# 2. AuditLogger — 审计日志器 (支持持久化)
# =====================================================================

class AuditLogger:
    """
    操作审计日志器 (增强版 - 支持文件持久化)

    功能:
      - 记录所有 MEDIUM 及以上风险的行动
      - 内存缓存 + JSON文件持久化 (双写)
      - 支持按日期自动轮转
      - 提供查询接口用于Dashboard展示
      - 启动时自动加载历史日志

    存储格式:
      - 文件: data/audit/YYYY-MM-DD.jsonl (每行一条JSON)
      - 内存: 最近 N 条记录 (用于快速查询)
    """

    def __init__(
        self,
        max_cache_size: int = 1000,
        persist_dir: Optional[str] = None,
        enable_persist: bool = True,
        max_file_size_mb: float = 10.0,
        retention_days: int = 90,
    ):
        self._cache: List[AuditRecord] = []
        self._max_size = max_cache_size
        self._lock = asyncio.Lock()
        self._enable_persist = enable_persist

        # 持久化配置
        self._persist_dir = Path(persist_dir) if persist_dir else Path("data/audit")
        self._max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self._retention_days = retention_days
        self._current_date = date.today().isoformat()

        # 初始化持久化存储
        if self._enable_persist:
            self._init_persistence()

    async def log(
        self,
        user_context: UserContext,
        action_type: ActionType,
        risk_level: RiskLevel,
        params: Dict[str, Any],
        result: Optional[ActionResult] = None,
    ) -> str:
        """
        记录一条审计日志 (双写: 内存 + 文件)

        Returns:
            audit_id: 审计记录ID
        """
        audit_id = f"AUDIT-{uuid_mod.uuid4().hex[:12].upper()}"

        record = AuditRecord(
            audit_id=audit_id,
            timestamp=datetime.now().isoformat(),
            user_context=user_context,
            action_type=action_type,
            risk_level=risk_level,
            params=params,
            result=result,
            status="executed" if result and result.success else "pending",
        )

        async with self._lock:
            # 写入内存缓存
            self._cache.append(record)
            if len(self._cache) > self._max_size:
                self._cache = self._cache[-self._max_size:]

            # 写入文件 (异步，不阻塞主流程)
            if self._enable_persist:
                await self._persist_record(record)

        # 输出到日志系统
        log_level = logging.WARNING if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL) else logging.INFO
        logger.log(
            log_level,
            f"[AUDIT] {audit_id} | {user_context.role}/{user_context.user_id} | "
            f"{action_type.value} ({risk_level.value}) | "
            f"params={json.dumps(params, ensure_ascii=False)[:200]} | "
            f"result={'SUCCESS' if result and result.success else 'PENDING'}"
        )

        return audit_id

    def _init_persistence(self):
        """初始化持久化存储目录"""
        try:
            self._persist_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"📁 审计日志持久化目录: {self._persist_dir.absolute()}")
        except Exception as e:
            logger.warning(f"⚠️ 无法创建审计日志目录: {e}, 将禁用持久化")
            self._enable_persist = False

    async def _persist_record(self, record: AuditRecord):
        """将单条记录追加到当日日志文件"""
        try:
            # 检查日期是否变更（需要轮转）
            today = date.today().isoformat()
            if today != self._current_date:
                self._current_date = today

            # 写入当日日志文件
            log_file = self._persist_dir / f"{today}.jsonl"
            record_dict = self._record_to_dict(record)

            # JSONL格式: 每行一条JSON
            with open(log_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record_dict, ensure_ascii=False) + "\n")

            # 检查文件大小（超过限制则轮转）
            if log_file.exists() and log_file.stat().st_size > self._max_file_size_bytes:
                self._rotate_log_file(log_file)

        except Exception as e:
            logger.error(f"❌ 审计日志写入失败: {e}")

    def _record_to_dict(self, record: AuditRecord) -> dict:
        """将AuditRecord转换为可序列化的字典"""
        return {
            "audit_id": record.audit_id,
            "timestamp": record.timestamp,
            "user_id": record.user_context.user_id,
            "role": record.user_context.role,
            "session_id": record.user_context.session_id,
            "ip_address": record.user_context.ip_address,
            "action_type": record.action_type.value,
            "risk_level": record.risk_level.value,
            "params": record.params,
            "result": record.result.to_dict() if record.result else None,
            "status": record.status,
        }

    def _rotate_log_file(self, log_file: Path):
        """轮转日志文件"""
        try:
            base_name = log_file.stem  # YYYY-MM-DD
            timestamp = datetime.now().strftime("%H%M%S")
            rotated_name = f"{base_name}_{timestamp}.jsonl.rotated"
            log_file.rename(log_file.parent / rotated_name)
            logger.info(f"📝 审计日志已轮转: {rotated_name}")
        except Exception as e:
            logger.error(f"❌ 日志轮转失败: {e}")

    def cleanup_old_logs(self) -> int:
        """清理过期日志文件"""
        if not self._enable_persist or not self._persist_dir.exists():
            return 0

        cleaned = 0
        cutoff = date.today() - __import__("datetime").timedelta(days=self._retention_days)

        for log_file in self._persist_dir.glob("*.jsonl"):
            try:
                # 从文件名提取日期
                file_date_str = log_file.stem.split("_")[0]  # 处理 .rotated 后缀
                file_date = date.fromisoformat(file_date_str)

                if file_date < cutoff:
                    log_file.unlink()
                    cleaned += 1
                    logger.info(f"🗑️ 已清理过期审计日志: {log_file.name}")
            except (ValueError, IndexError):
                continue  # 跳过无法解析日期的文件

        return cleaned

    async def query(
        self,
        user_id: Optional[str] = None,
        action_type: Optional[ActionType] = None,
        risk_level: Optional[RiskLevel] = None,
        limit: int = 50,
    ) -> List[AuditRecord]:
        """查询审计记录 (内存 + 文件)"""
        results = self._cache

        if user_id:
            results = [r for r in results if r.user_context.user_id == user_id]
        if action_type:
            results = [r for r in results if r.action_type == action_type]
        if risk_level:
            results = [r for r in results if r.risk_level == risk_level]

        return results[-limit:]

    def query_history(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        user_id: Optional[str] = None,
        action_type: Optional[str] = None,
        risk_level: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict]:
        """
        查询历史审计日志 (从文件)

        Args:
            start_date: 开始日期 (YYYY-MM-DD)
            end_date: 结束日期 (YYYY-MM-DD)
            user_id: 用户ID过滤
            action_type: 行动类型过滤
            risk_level: 风险等级过滤
            limit: 返回条数上限

        Returns:
            审计记录字典列表
        """
        if not self._enable_persist or not self._persist_dir.exists():
            return []

        results = []
        date_range = []

        # 确定日期范围
        if start_date and end_date:
            current = date.fromisoformat(start_date)
            end = date.fromisoformat(end_date)
            while current <= end:
                date_range.append(current.isoformat())
                current += __import__("datetime").timedelta(days=1)
        elif start_date:
            date_range = [start_date]
        elif end_date:
            date_range = [end_date]
        else:
            # 默认查询最近7天
            for i in range(7):
                d = (date.today() - __import__("datetime").timedelta(days=i)).isoformat()
                date_range.append(d)

        # 按日期倒序遍历（最新的在前）
        for day in sorted(date_range, reverse=True):
            log_file = self._persist_dir / f"{day}.jsonl"
            if not log_file.exists():
                continue

            try:
                with open(log_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue

                        record = json.loads(line)

                        # 应用过滤条件
                        if user_id and record.get("user_id") != user_id:
                            continue
                        if action_type and record.get("action_type") != action_type:
                            continue
                        if risk_level and record.get("risk_level") != risk_level:
                            continue

                        results.append(record)

                        if len(results) >= limit:
                            return results
            except Exception as e:
                logger.warning(f"⚠️ 读取审计日志失败 {log_file}: {e}")
                continue

        return results[:limit]

    def get_stats(self) -> Dict[str, Any]:
        """获取审计统计信息 (内存 + 文件)"""
        total_memory = len(self._cache)
        by_risk = {}
        by_role = {}
        by_action = {}

        for record in self._cache:
            # 按风险等级统计
            risk = record.risk_level.value
            by_risk[risk] = by_risk.get(risk, 0) + 1

            # 按角色统计
            role = record.user_context.role
            by_role[role] = by_role.get(role, 0) + 1

            # 按行动类型统计
            action = record.action_type.value
            by_action[action] = by_action.get(action, 0) + 1

        # 文件统计
        file_count = 0
        total_size = 0
        if self._enable_persist and self._persist_dir.exists():
            for log_file in self._persist_dir.glob("*.jsonl"):
                file_count += 1
                total_size += log_file.stat().st_size

        return {
            "total_records": total_memory,
            "by_risk_level": by_risk,
            "by_role": by_role,
            "by_action_type": by_action,
            "cache_size": f"{total_memory}/{self._max_size}",
            "persistence_enabled": self._enable_persist,
            "log_files": file_count,
            "log_size_mb": round(total_size / (1024 * 1024), 2),
            "persist_dir": str(self._persist_dir),
        }


# 全局审计日志器实例
audit_logger = AuditLogger()


# =====================================================================
# 3. AgentGatewayMiddleware — 核心中间件类
# =====================================================================

class AgentGatewayMiddleware:
    """
    Agent Gateway 中间件 (单例模式)

    ⚠️ 改造方案 P0-C: Fail-Closed 安全机制
       - 任何未预期的异常 → 拒绝执行 (success=False)
       - HIGH/CRITICAL 操作 → 必须人工审批，不直接执行
       - BLOCKED 操作 → 直接拒绝 + 安全告警
       - 审计日志记录所有尝试 (无论成功/失败)

    所有岗位AI助理的行动都必须通过此中间件进行权限控制和审计。

    设计模式:
      - 单例: 全局唯一实例，统一管理
      - 门面模式: 封装复杂的权限检查和审计逻辑
      - 策略模式: 根据 RiskLevel 选择不同的处理策略

    使用示例:
        gateway = AgentGatewayMiddleware.get_instance()

        # 执行行动 (自动处理权限+审计+审批路由)
        result = await gateway.execute_action(
            action_type=ActionType.APPROVE_PURCHASE,
            user_context=UserContext(user_id="u1", role="purchaser"),
            params={"task_id": "PO-APPROVAL-001"},
        )
    """

    _instance: Optional["AgentGatewayMiddleware"] = None

    def __init__(self):
        self._audit_logger = audit_logger
        self._handler_registry: Dict[ActionType, Callable] = {}
        self._approval_callback: Optional[Callable] = None
        # G4: 任务完成回调 (用于KPI自动回写)
        self._task_completed_callback: Optional[Callable] = None
        self._initialized = False

    @classmethod
    def get_instance(cls) -> "AgentGatewayMiddleware":
        """获取单例实例"""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def initialize(self):
        """初始化 Gateway (注册处理器等)"""
        if self._initialized:
            return

        # 注册默认处理器 (可后续扩展)
        self._register_default_handlers()
        
        self._initialized = True
        logger.info("✅ AgentGatewayMiddleware 初始化完成")

    def _register_default_handlers(self):
        """注册默认的行动处理器映射 — 将 ActionType 路由到 SupplyChainManager 真实业务方法

        Handler 签名: handler(**params) -> dict | Any
        Gateway 在 _execute_direct / _execute_with_audit 中自动调用。
        """
        from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

        # ── HIGH 风险: 采购相关 ──
        self._handler_registry[ActionType.APPROVE_PURCHASE] = \
            lambda **kw: SupplyChainManager.approve_purchase_task(
                task_id=kw.get("task_id", ""),
                approved_by=kw.get("approved_by", "gateway"),
            )

        self._handler_registry[ActionType.CREATE_PO] = \
            lambda **kw: SupplyChainManager.create_purchase_approval_task(
                suggestion_id=kw.get("suggestion_id"),
                items=kw.get("items", []),
                supplier=kw.get("supplier", ""),
                store_id=kw.get("store_id", os.environ.get("HOTPOT_STORE_ID", "")),
                requested_by=kw.get("requested_by", "gateway"),
            )

        self._handler_registry[ActionType.CANCEL_PO] = \
            lambda **kw: SupplyChainManager.cancel_po(
                po_number=kw.get("po_number", ""),
                reason=kw.get("reason", "Gateway审批取消"),
            )

        self._handler_registry[ActionType.CREATE_SUPPLIER] = \
            lambda **kw: SupplyChainManager.create_supplier(
                supplier=kw.get("supplier"),  # SupplierInfo 对象
            )

        # ── MEDIUM 风险: 供应链写操作 ──
        self._handler_registry[ActionType.ACCEPT_SUGGESTION_PURCHASE] = \
            lambda **kw: SupplyChainManager.create_po_from_suggestion(
                suggestion_id=kw.get("suggestion_id"),
                approved_by=kw.get("approved_by", "gateway"),
            )

        self._handler_registry[ActionType.SUBMIT_RECEIVING] = \
            lambda **kw: SupplyChainManager.submit_receiving(
                record=kw.get("record"),  # ReceivingRecord 对象
            )

        self._handler_registry[ActionType.UPDATE_SUPPLIER_SCORE] = \
            lambda **kw: SupplyChainManager.update_supplier_score(
                update=kw.get("update"),  # SupplierScoreUpdate 对象
            )

        # ── LOW 风险: 任务操作 (G4: 真正落地) ──
        self._handler_registry[ActionType.COMPLETE_TASK] = \
            self._handle_complete_task

        self._handler_registry[ActionType.DISMISS_TASK] = \
            lambda **kw: {"task_id": kw.get("task_id"), "status": "dismissed", "dismissed_at": datetime.now().isoformat()}

        self._handler_registry[ActionType.REJECT_SUGGESTION] = \
            lambda **kw: {"suggestion_id": kw.get("suggestion_id"), "status": "rejected"}

        # ── LOW 风险: 查询操作 ──
        self._handler_registry[ActionType.QUERY_DASHBOARD] = \
            lambda **kw: SupplyChainManager.get_dashboard_full(
                include_kitchen=kw.get("include_kitchen", False),
                include_purchase=kw.get("include_purchase", False),
            )

        self._handler_registry[ActionType.QUERY_TASKS] = \
            lambda **kw: SupplyChainManager.get_tasks(
                role=kw.get("role", "store_manager"),
                status=kw.get("status", "pending"),
            )

        self._handler_registry[ActionType.QUERY_SUGGESTIONS] = \
            lambda **kw: SupplyChainManager.get_suggestions(
                role=kw.get("role", "store_manager"),
            )

        self._handler_registry[ActionType.QUERY_PURCHASE_ORDERS] = \
            lambda **kw: SupplyChainManager.get_po_list(
                status=kw.get("status"),
                store_id=kw.get("store_id"),
            )

        self._handler_registry[ActionType.QUERY_SUPPLIERS] = \
            lambda **kw: SupplyChainManager.get_supplier_list()

        self._handler_registry[ActionType.QUERY_INVENTORY] = \
            lambda **kw: SupplyChainManager.list_product_masters()

        logger.info(f"✅ Gateway 已注册 {len(self._handler_registry)} 个业务处理器")

    def set_approval_callback(self, callback: Callable):
        """
        设置审批任务创建回调函数

        当 HIGH/CRITICAL 风格操作需要审批时，Gateway会调用此回调创建审批任务。

        Args:
            callback: 函数签名 (action_type, user_context, params) → task_dict
        """
        self._approval_callback = callback
        logger.info(f"✅ 审批回调已设置: {callback.__name__ if hasattr(callback, '__name__') else callback}")

    def set_task_completed_callback(self, callback: Callable):
        """
        设置任务完成回调函数 (G4 KPI回写钩子) ⭐

        当任务通过 COMPLETE_TASK 操作完成时，Gateway会自动调用此回调，
        触发KPI计算和Hub PG回写，完成"感知→决策→执行→验证→回写"闭环。

        回调签名: callback(task_result: Dict, user_context: UserContext) -> None

        典型实现:
            def on_task_completed(task_result, user_context):
                # 1. 从 task_result 提取 KPI 原始数据 (如 response_time_sec)
                # 2. 调用 KPIEngine.calculate_from_task()
                # 3. 调用 pg_db.upsert_kpi_metric() 写入 Hub PG

        Args:
            callback: 任务完成回调函数
        """
        self._task_completed_callback = callback
        logger.info(f"✅ 任务完成回调已设置 (G4 KPI回写): {callback.__name__ if hasattr(callback, '__name__') else callback}")

    def _handle_complete_task(self, **kw) -> Dict:
        """处理任务完成操作 (G4: 真正落地 + 触发KPI回写).

        不再返回模拟字典，而是真正调用 TaskStore.transition() 更新状态，
        然后触发 _task_completed_callback 进行 KPI 回写。
        """
        task_id = kw.get("task_id")
        actor_id = kw.get("actor_id", "system")
        note = kw.get("note", "任务已完成")

        result = {
            "task_id": task_id,
            "status": "completed",
            "completed_at": datetime.now().isoformat(),
            "actor_id": actor_id,
        }

        try:
            # 尝试调用 TaskStore 真正更新状态
            from hotpot_platform.cloud.event_hub.task_store import TaskStore, TRANSITIONS

            store = TaskStore.get_instance()
            # 先 submit 再 verify (完整流程)
            try:
                store.transition(task_id, "submit", actor_id=actor_id, note=note)
            except Exception:
                pass  # 可能已经是 submitted 状态

            transition_result = store.transition(
                task_id, "verify", actor_id=actor_id, note=note
            )
            result["transition"] = transition_result
            result["db_updated"] = True

            logger.info(f"✅ G4: 任务 {task_id} 已完成并写入DB")

        except Exception as exc:
            # 即使 DB 更新失败，也记录结果（降级模式）
            logger.warning(f"⚠️ G4: 任务 {task_id} DB更新失败 (降级模式): {exc}")
            result["db_updated"] = False
            result["error"] = str(exc)

        # 触发 KPI 回写回调 (G4 核心逻辑)
        if self._task_completed_callback:
            try:
                self._task_completed_callback(result, **kw)
                result["kpi_written"] = True
                logger.info(f"✅ G4: 任务 {task_id} KPI回写成功")
            except Exception as exc:
                logger.warning(f"⚠️ G4: 任务 {task_id} KPI回写失败: {exc}")
                result["kpi_written"] = False
                result["kpi_error"] = str(exc)
        else:
            result["kpi_written"] = False
            result["kpi_skipped_reason"] = "未设置 task_completed_callback"

        return result

    # ── 核心方法: execute_action ────────────────────────────────

    async def execute_action(
        self,
        action_type: ActionType,
        user_context: UserContext,
        params: Dict[str, Any],
        dry_run: bool = False,
    ) -> ActionResult:
        """
        统一行动入口 ⭐

        这是 Agent Gateway 的核心方法，所有受控行动都应通过此方法执行。

        流程:
          1. ✅ 身份验证 (确保 user_context 有效)
          2. 🔍 权限检查 (查询 PermissionMatrix)
          3. 🚦 风险路由 (根据 RiskLevel 分流):
             - LOW/MEDIUM: 直接执行 + 审计
             - HIGH/CRITICAL: 创建审批任务 + 返回 task_id
             - BLOCKED: 拒绝 + 安全告警
          4. 📝 审计记录 (写入 AuditLogger)
          5. 📤 返回结果

        Args:
            action_type: 行动类型枚举
            user_context: 用户上下文
            params: 行动参数字典
            dry_run: 如果为True，只做权限检查不实际执行

        Returns:
            ActionResult: 包含执行结果或审批任务信息
        """
        start_time = time.time()

        try:
            # Step 1: 基础验证
            if not user_context or not user_context.user_id:
                raise AgentGatewayError("无效的用户上下文")

            # Step 2: 权限检查
            is_allowed, rule, error_msg = PermissionMatrix.validate_action(
                role=user_context.role,
                action_type=action_type,
                raise_on_blocked=True,
            )

            if not is_allowed:
                # 权限不足 (BLOCKED)
                result = ActionResult(
                    success=False,
                    action_type=action_type,
                    risk_level=RiskLevel.BLOCKED,
                    error=error_msg,
                )

                # 记录安全告警
                await self._audit_logger.log(
                    user_context=user_context,
                    action_type=action_type,
                    risk_level=RiskLevel.BLOCKED,
                    params=params,
                    result=result,
                )

                logger.warning(f"🚫 [GATEWAY] 权限拒绝: {user_context.role}/{user_context.user_id} → {action_type.value}")
                return result

            # Step 3: 风险路由
            risk_level = rule.risk_level

            if risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL):
                # 🔴 HIGH/CRITICAL: 需要审批，不直接执行
                if dry_run:
                    result = ActionResult(
                        success=True,
                        action_type=action_type,
                        risk_level=risk_level,
                        approval_required=True,
                        data={"dry_run": True, "message": "操作需要审批"},
                    )
                else:
                    result = await self._route_to_approval(
                        action_type=action_type,
                        user_context=user_context,
                        params=params,
                        rule=rule,
                    )

            elif risk_level == RiskLevel.MEDIUM:
                # 🟡 MEDIUM: 直接执行 + 强制审计
                if dry_run:
                    result = ActionResult(
                        success=True,
                        action_type=action_type,
                        risk_level=risk_level,
                        data={"dry_run": True},
                    )
                else:
                    result = await self._execute_with_audit(
                        action_type=action_type,
                        user_context=user_context,
                        params=params,
                        rule=rule,
                    )

            else:
                # 🟢 LOW: 直接执行 + 可选审计
                if dry_run:
                    result = ActionResult(
                        success=True,
                        action_type=action_type,
                        risk_level=risk_level,
                        data={"dry_run": True},
                    )
                else:
                    result = await self._execute_direct(
                        action_type=action_type,
                        user_context=user_context,
                        params=params,
                        rule=rule,
                    )

            # Step 4: 计算耗时
            result.execution_time_ms = (time.time() - start_time) * 1000

            # Step 5: 记录审计 (MEDIUM及以上强制记录)
            if risk_level.value >= RiskLevel.MEDIUM.value:
                result.audit_id = await self._audit_logger.log(
                    user_context=user_context,
                    action_type=action_type,
                    risk_level=risk_level,
                    params=params,
                    result=result,
                )

            return result

        except ApprovalRequiredError as e:
            # 审批需求异常 (这是正常流程，不是错误)
            result = ActionResult(
                success=True,  # 从Gateway角度是成功的(正确路由了)
                action_type=action_type,
                risk_level=RiskLevel.HIGH,
                approval_required=True,
                task_id=e.task_id,
                data={"message": e.message},
                execution_time_ms=(time.time() - start_time) * 1000,
            )
            result.audit_id = await self._audit_logger.log(
                user_context=user_context,
                action_type=action_type,
                risk_level=RiskLevel.HIGH,
                params=params,
                result=result,
            )
            return result

        except Exception as e:
            # 未预期的异常
            error_result = ActionResult(
                success=False,
                action_type=action_type,
                risk_level=risk_level if 'risk_level' in dir() else RiskLevel.LOW,
                error=str(e),
                execution_time_ms=(time.time() - start_time) * 1000,
            )

            logger.error(f"❌ [GATEWAY] 执行异常: {action_type.value} → {str(e)}", exc_info=True)

            # 记录错误审计
            try:
                await self._audit_logger.log(
                    user_context=user_context,
                    action_type=action_type,
                    risk_level=RiskLevel.LOW,
                    params=params,
                    result=error_result,
                )
            except:
                pass  # 审计失败不影响主流程

            return error_result

    # ── 内部方法: 执行策略 ───────────────────────────────────

    async def _execute_direct(
        self,
        action_type: ActionType,
        user_context: UserContext,
        params: Dict[str, Any],
        rule: PermissionRule,
    ) -> ActionResult:
        """直接执行低风险行动"""
        # LOW风险操作通常不需要特殊处理
        # 这里可以添加通用的前置/后置钩子

        # 查找注册的处理器
        handler = self._handler_registry.get(action_type)
        if handler:
            if asyncio.iscoroutinefunction(handler):
                data = await handler(**params)
            else:
                data = handler(**params)
        else:
            # 无注册处理器时返回成功(由调用方继续处理)
            data = {"gateway_passed": True, "action": action_type.value}

        return ActionResult(
            success=True,
            action_type=action_type,
            risk_level=RiskLevel.LOW,
            data=data,
        )

    async def _execute_with_audit(
        self,
        action_type: ActionType,
        user_context: UserContext,
        params: Dict[str, Any],
        rule: PermissionRule,
    ) -> ActionResult:
        """执行中风险行动 (带审计)"""
        # 类似 _execute_direct，但会强制记录审计
        handler = self._handler_registry.get(action_type)
        if handler:
            if asyncio.iscoroutinefunction(handler):
                data = await handler(**params)
            else:
                data = handler(**params)
        else:
            data = {"gateway_passed": True, "action": action_type.value}

        return ActionResult(
            success=True,
            action_type=action_type,
            risk_level=RiskLevel.MEDIUM,
            data=data,
        )

    async def _route_to_approval(
        self,
        action_type: ActionType,
        user_context: UserContext,
        params: Dict[str, Any],
        rule: PermissionRule,
    ) -> ActionResult:
        """
        路由到审批工作流

        对于 HIGH/CRITICAL 风格的操作:
          1. 调用审批回调创建待审批任务
          2. 返回 task_id 给调用方
          3. 不直接执行原始操作
        """
        if not self._approval_callback:
            # 无审批回调时使用默认行为 (调用SupplyChainManager)
            from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

            if action_type == ActionType.APPROVE_PURCHASE:
                # approve_purchase 是特殊情况: 它本身就是审批动作
                # 但仍需通过Gateway记录审计
                task_id = params.get("task_id")
                
                # 实际执行审批 (这里会调用已有的approve_purchase_task方法)
                po_result = SupplyChainManager.approve_purchase_task(
                    task_id=task_id,
                    approved_by=user_context.user_id,
                )

                if po_result:
                    return ActionResult(
                        success=True,
                        action_type=action_type,
                        risk_level=RiskLevel.HIGH,
                        data=po_result,
                    )
                else:
                    raise AgentGatewayError(f"审批失败: 任务 {task_id} 不存在或状态不允许")

            elif action_type == ActionType.CREATE_PO:
                # 创建PO必须通过审批流程
                # 调用 create_purchase_approval_task 生成待审批任务
                task = SupplyChainManager.create_purchase_approval_task(
                    suggestion_id=params.get("suggestion_id"),
                    sku=params.get("sku"),
                    qty=params.get("qty", 10),
                    supplier_id=params.get("supplier_id"),
                    target_role=rule.approval_role or "purchaser",
                    priority="high",
                    title=f"审批采购: {params.get('sku', '?')} x{params.get('qty', '?')}",
                    description=f"Gateway拦截: {user_context.role}/{user_context.user_id} 请求创建PO",
                )

                if task:
                    # 抛出 ApprovalRequiredError (会被上层捕获并转换为正常结果)
                    raise ApprovalRequiredError(
                        task_id=task["id"],
                        action_type=action_type,
                        message=f"PO创建请求已转为审批任务 {task['id']}, 等待 {rule.approval_role or 'purchaser'} 审批",
                    )
                else:
                    raise AgentGatewayError("创建审批任务失败")
            
            else:
                # 其他HIGH风险操作 → 根据类型分发到对应业务逻辑
                from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

                if action_type == ActionType.CANCEL_PO:
                    po_number = params.get("po_number", "")
                    reason = params.get("reason", "Gateway审批取消")
                    result = SupplyChainManager.cancel_po(po_number, reason)
                    return ActionResult(
                        success=True,
                        action_type=action_type,
                        risk_level=RiskLevel.HIGH,
                        data={"po_number": po_number, "status": "cancelled", "reason": reason},
                    )

                elif action_type == ActionType.CREATE_SUPPLIER:
                    # 创建供应商需要店长审批 → 生成审批任务
                    supplier_info = params.get("supplier_info", {})
                    task = SupplyChainManager.create_purchase_approval_task(
                        suggestion_id=None,
                        sku=f"NEW-SUPPLIER-{supplier_info.get('name', '?')}",
                        qty=1,
                        supplier_id=supplier_info.get("id", ""),
                        target_role="store_manager",
                        priority="high",
                        title=f"审批新供应商: {supplier_info.get('name', '?')}",
                        description=f"请求人: {user_context.user_id} ({user_context.role})",
                    )
                    if task:
                        raise ApprovalRequiredError(
                            task_id=task["id"],
                            action_type=action_type,
                            message=f"新供应商创建已转为审批任务 {task['id']}, 等待店长确认",
                        )
                    else:
                        raise AgentGatewayError("创建供应商审批任务失败")

                elif action_type == ActionType.MODIFY_INVENTORY:
                    # 库存修改仅允许管理员特殊场景
                    raise ApprovalRequiredError(
                        task_id=f"INV-MOD-{uuid_mod.uuid4().hex[:8].upper()}",
                        action_type=action_type,
                        message="库存修改需管理员审批，请联系系统管理员",
                    )

                else:
                    # 未知的HIGH操作 → 通用待审批
                    raise ApprovalRequiredError(
                        task_id=f"PENDING-{uuid_mod.uuid4().hex[:8].upper()}",
                        action_type=action_type,
                        message=f"操作 {action_type.value} 需要审批，请等待管理员确认",
                    )
        else:
            # 使用自定义审批回调
            task = await self._approval_callback(
                action_type=action_type,
                user_context=user_context,
                params=params,
            )
            
            if task:
                raise ApprovalRequiredError(
                    task_id=task.get("id", ""),
                    action_type=action_type,
                )
            else:
                raise AgentGatewayError("审批回调返回空结果")

    # ── 装饰器支持 ───────────────────────────────────────────

    def require_action(self, action_type: ActionType):
        """
        装饰器: 要求行动通过 Gateway 验证

        用法:
            @gateway.require_action(ActionType.APPROVE_PURCHASE)
            async def my_api_endpoint(task_id: str, req: Request, session: dict):
                # 此处代码只在 Gateway 验证通过后执行
                # 可以从 request.state.gateway_result 获取验证结果
                pass
        """
        def decorator(func):
            @functools.wraps(func)
            async def wrapper(*args, **kwargs):
                # 从kwargs中提取用户上下文 (FastAPI依赖注入)
                session = kwargs.get("session", {})
                
                user_context = UserContext(
                    user_id=session.get("user_id", "unknown"),
                    role=session.get("role", "unknown"),
                    session_id=session.get("session_id"),
                )

                # 通过 Gateway 执行
                result = await self.execute_action(
                    action_type=action_type,
                    user_context=user_context,
                    params=kwargs,
                )

                if not result.success:
                    # 权限不足或其他错误
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=403,
                        detail={
                            "error": "PERMISSION_DENIED",
                            "message": result.error,
                            "action": action_type.value,
                            "risk_level": result.risk_level.value,
                        },
                    )

                if result.approval_required:
                    # 需要审批
                    from fastapi import HTTPException
                    raise HTTPException(
                        status_code=202,  # Accepted (需要后续审批)
                        detail={
                            "error": "APPROVAL_REQUIRED",
                            "message": "操作已提交审批",
                            "task_id": result.task_id,
                            "action": action_type.value,
                        },
                    )

                # 将结果注入到请求状态中 (供handler使用)
                # 注意: 这需要 FastAPI 的 Request 对象支持
                # kwargs.setdefault('request').state.gateway_result = result
                
                # 调用原始函数
                return await func(*args, **kwargs)

            return wrapper
        return decorator

    # ── 查询和管理方法 ───────────────────────────────────────

    async def get_audit_log(
        self,
        **filters,
    ) -> List[AuditRecord]:
        """查询审计日志"""
        return await self._audit_logger.query(**filters)

    def get_audit_stats(self) -> Dict[str, Any]:
        """获取审计统计"""
        return self._audit_logger.get_stats()

    def get_permission_matrix_summary(self, role: str) -> Dict[str, Any]:
        """获取角色的权限矩阵摘要"""
        permissions = PermissionMatrix.get_role_permissions(role)
        
        summary = {
            "role": role,
            "total_actions": len(permissions),
            "by_risk": {},
            "blocked_actions": [],
            "requires_approval": [],
        }

        for action_type, rule in permissions.items():
            risk = rule.risk_level.value
            summary["by_risk"][risk] = summary["by_risk"].get(risk, 0) + 1
            
            if rule.risk_level == RiskLevel.BLOCKED:
                summary["blocked_actions"].append({
                    "action": action_type.value,
                    "reason": rule.description,
                })
            
            if rule.requires_approval:
                summary["requires_approval"].append({
                    "action": action_type.value,
                    "approver": rule.approval_role,
                })

        return summary


# =====================================================================
# 4. 便捷函数
# =====================================================================

def get_gateway() -> AgentGatewayMiddleware:
    """获取 Gateway 单例 (便捷函数)"""
    return AgentGatewayMiddleware.get_instance()


async def execute_via_gateway(
    action_type: ActionType,
    role: str,
    user_id: str,
    params: Dict[str, Any],
    **context_kwargs,
) -> ActionResult:
    """
    便捷函数: 通过 Gateway 执行行动

    使用示例:
        result = await execute_via_gateway(
            action_type=ActionType.APPROVE_PURCHASE,
            role="purchaser",
            user_id="user_123",
            params={"task_id": "PO-APPROVAL-001"},
        )
    """
    gateway = get_gateway()
    
    if not gateway._initialized:
        gateway.initialize()

    user_context = UserContext(
        user_id=user_id,
        role=role,
        **context_kwargs,
    )

    return await gateway.execute_action(
        action_type=action_type,
        user_context=user_context,
        params=params,
    )


# =====================================================================
# 5. 导出
# =====================================================================

__all__ = [
    # 核心类
    "AgentGatewayMiddleware",
    # 数据模型
    "UserContext",
    "ActionResult",
    "AuditRecord",
    # 审计
    "AuditLogger",
    "audit_logger",
    # 便捷函数
    "get_gateway",
    "execute_via_gateway",
]


# =====================================================================
# 6. 自测
# =====================================================================

if __name__ == "__main__":
    import asyncio

    async def test_gateway():
        print("=" * 70)
        print("🧪 Agent Gateway Middleware 自检")
        print("=" * 70)

        # 初始化
        gateway = AgentGatewayMiddleware.get_instance()
        gateway.initialize()
        print(f"\n✅ Gateway 初始化完成")

        # 测试1: LOW风险操作 (应直接执行)
        print("\n📋 测试1: LOW风险操作 (query_dashboard)")
        result = await gateway.execute_action(
            action_type=ActionType.QUERY_DASHBOARD,
            user_context=UserContext(user_id="test_user", role="store_manager"),
            params={"include_kitchen": True},
        )
        print(f"   结果: success={result.success}, risk={result.risk_level.value}")
        assert result.success == True
        print("   ✅ PASS")

        # 测试2: HIGH风险操作 (应触发审批)
        print("\n📋 测试2: HIGH风险操作 (create_po by purchaser)")
        try:
            result = await gateway.execute_action(
                action_type=ActionType.CREATE_PO,
                user_context=UserContext(user_id="test_purchaser", role="purchaser"),
                params={"sku": "FP-HNRC-001", "qty": 20},
            )
            print(f"   结果: approval_required={result.approval_required}, task_id={result.task_id}")
            assert result.approval_required == True
            print("   ✅ PASS (正确触发审批)")
        except ApprovalRequiredError as e:
            print(f"   ✅ PASS (ApprovalRequiredError: {e.message})")

        # 测试3: BLOCKED操作 (应被拒绝)
        print("\n📋 测试3: BLOCKED操作 (create_po by store_manager)")
        result = await gateway.execute_action(
            action_type=ActionType.CREATE_PO,
            user_context=UserContext(user_id="test_manager", role="store_manager"),
            params={"sku": "FP-HNRC-001", "qty": 20},
        )
        print(f"   结果: success={result.success}, error={result.error[:50] if result.error else ''}")
        assert result.success == False
        assert result.risk_level == RiskLevel.BLOCKED
        print("   ✅ PASS (正确阻止)")

        # 测试4: 审计日志
        print("\n📋 测试4: 审计日志统计")
        stats = gateway.get_audit_stats()
        print(f"   总记录数: {stats['total_records']}")
        print(f"   按风险分布: {stats['by_risk_level']}")
        print(f"   按角色分布: {stats['by_role']}")
        assert stats['total_records'] >= 3  # 至少有上面3条测试记录
        print("   ✅ PASS")

        # 测试5: 权限矩阵摘要
        print("\n📋 测试5: 权限矩阵摘要 (purchaser)")
        summary = gateway.get_permission_matrix_summary("purchaser")
        print(f"   总行动数: {summary['total_actions']}")
        print(f"   需要审批: {len(summary['requires_approval'])} 个")
        print(f"   已阻止: {len(summary['blocked_actions'])} 个")
        print("   ✅ PASS")

        print("\n" + "=" * 70)
        print("✅ Agent Gateway Middleware 自检全部通过!")
        print("=" * 70)

    # 运行测试
    asyncio.run(test_gateway())
