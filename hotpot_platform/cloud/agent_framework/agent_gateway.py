"""
火瞳 · Agent Gateway 中间件 (核心引擎)
========================================

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
import time
import uuid
from datetime import datetime
from dataclasses import dataclass, field
from enum import Enum
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
# 2. AuditLogger — 审计日志器
# =====================================================================

class AuditLogger:
    """
    操作审计日志器

    功能:
      - 记录所有 MEDIUM 及以上风险的行动
      - 支持内存缓存 + 可选持久化
      - 提供查询接口用于Dashboard展示
    """

    def __init__(self, max_cache_size: int = 1000):
        self._cache: List[AuditRecord] = []
        self._max_size = max_cache_size
        self._lock = asyncio.Lock()

    async def log(
        self,
        user_context: UserContext,
        action_type: ActionType,
        risk_level: RiskLevel,
        params: Dict[str, Any],
        result: Optional[ActionResult] = None,
    ) -> str:
        """
        记录一条审计日志

        Returns:
            audit_id: 审计记录ID
        """
        audit_id = f"AUDIT-{uuid4().hex[:12].upper()}"
        
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
            self._cache.append(record)
            # 限制缓存大小
            if len(self._cache) > self._max_size:
                self._cache = self._cache[-self._max_size:]

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

    async def query(
        self,
        user_id: Optional[str] = None,
        action_type: Optional[ActionType] = None,
        risk_level: Optional[RiskLevel] = None,
        limit: int = 50,
    ) -> List[AuditRecord]:
        """查询审计记录"""
        results = self._cache
        
        if user_id:
            results = [r for r in results if r.user_context.user_id == user_id]
        if action_type:
            results = [r for r in results if r.action_type == action_type]
        if risk_level:
            results = [r for r in results if r.risk_level == risk_level]
        
        return results[-limit:]

    def get_stats(self) -> Dict[str, Any]:
        """获取审计统计信息"""
        total = len(self._cache)
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
        
        return {
            "total_records": total,
            "by_risk_level": by_risk,
            "by_role": by_role,
            "by_action_type": by_action,
            "cache_size": f"{total}/{self._max_size}",
        }


# 全局审计日志器实例
audit_logger = AuditLogger()


# =====================================================================
# 3. AgentGatewayMiddleware — 核心中间件类
# =====================================================================

class AgentGatewayMiddleware:
    """
    Agent Gateway 中间件 (单例模式)

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
        """注册默认的行动处理器映射"""
        # 这里可以注册从 ActionType 到实际业务函数的映射
        # 示例:
        # self._handler_registry[ActionType.APPROVE_PURCHASE] = \
        #     SupplyChainManager.approve_purchase_pass
        pass

    def set_approval_callback(self, callback: Callable):
        """
        设置审批任务创建回调函数

        当 HIGH/CRITICAL 风格操作需要审批时，Gateway会调用此回调创建审批任务。

        Args:
            callback: 函数签名 (action_type, user_context, params) → task_dict
        """
        self._approval_callback = callback
        logger.info(f"✅ 审批回调已设置: {callback.__name__ if hasattr(callback, '__name__') else callback}")

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
                # 其他HIGH风险操作的默认处理
                raise ApprovalRequiredError(
                    task_id=f"PENDING-{uuid4().hex[:8].upper()}",
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
