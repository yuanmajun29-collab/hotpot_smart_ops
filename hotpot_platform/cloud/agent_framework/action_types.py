"""
火瞳 · Agent 行动类型与风险等级定义
=====================================

本模块定义了所有岗位AI助理可能执行的**行动类型(ActionType)**及其对应的**风险等级(RiskLevel)**。

设计原则:
  1. 统一替代散落在各处的字符串常量 (action_type="create_po" 等)
  2. 为 Agent Gateway 权限控制提供标准化的分类依据
  3. 支持基于 RiskLevel 的自动路由 (直接执行/需审批/拒绝)
  4. 符合《最终方案》第六、七章的 Agent 行动边界要求

使用方式:
  from hotpot_platform.cloud.agent_framework.action_types import ActionType, RiskLevel, PermissionMatrix

  # 检查行动风险
  risk = PermissionMatrix.get_risk_level("purchaser", ActionType.APPROVE_PURCHASE)
  # → RiskLevel.HIGH (需要人工审批)

作者: 火瞳AI团队
日期: 2026-08-02 (P0-2 Agent Gateway 规范化)
"""

from enum import Enum
from typing import Dict, List, Optional, Set
from dataclasses import dataclass, field


# =====================================================================
# 1. ActionType 枚举 — 统一的行动类型分类
# =====================================================================

class ActionType(str, Enum):
    """
    岗位AI助理行动类型枚举

    分类维度:
      - 读操作 (QUERY_*): 获取数据，无需审批
      - 低风险写操作 (*_TASK, *_SUGGESTION_LOW): 自动执行
      - 中风险写操作 (*_SUGGESTION_PURCHASE): 执行+审计
      - 高风险写操作 (CREATE_*, APPROVE_*): 必须人工审批
      - 通知操作 (SEND_*, PUSH_*): 自动执行，有频率限制

    命名规范:
      - 动词_对象: CREATE_PO, APPROVE_PURCHASE, QUERY_DASHBOARD
      - 风险隐含在名称中: *_LOW (低风险), *_PURCHASE (中高风险)
    """

    # ── 读操作（无需审批，自动执行）─────────────────────────────
    QUERY_DASHBOARD = "query_dashboard"
    """查询工作台面板数据 (KPI/待办/建议/趋势)"""

    QUERY_TASKS = "query_tasks"
    """查询待办任务列表"""

    QUERY_SUGGESTIONS = "query_suggestions"
    """查询AI建议列表"""

    QUERY_PURCHASE_ORDERS = "query_purchase_orders"
    """查询采购订单列表"""

    QUERY_SUPPLIERS = "query_suppliers"
    """查询供应商信息"""

    QUERY_INVENTORY = "query_inventory"
    """查询库存数据"""

    # ── 低风险写操作（自动执行，轻量审计）────────────────────────
    COMPLETE_TASK = "complete_task"
    """完成待办任务 (仅标记状态变更)"""

    DISMISS_TASK = "dismiss_task"
    """忽略/关闭待办任务"""

    ACCEPT_SUGGESTION_LOW = "accept_suggestion_low"
    """采纳非采购类型建议 (如供应商切换、成本优化)"""

    REJECT_SUGGESTION = "reject_suggestion"
    """拒绝AI建议"""

    SEED_DEMO_DATA = "seed_demo_data"
    """初始化演示数据 (仅Demo环境)"""

    # ── 中风险写操作（执行 + 审计记录）────────────────────────────
    ACCEPT_SUGGESTION_PURCHASE = "accept_suggestion_purchase"
    """
    采纳采购类型建议 ⚠️
    
    此操作会触发 IP-5 事件:
      → create_purchase_approval_task() (生成待审批任务)
      → 不会直接创建PO，但会启动审批流程
    
    风险原因: 间接触发高级行动(PO创建)，需完整审计链
    """

    SUBMIT_RECEIVING = "submit_receiving"
    """
    提交收货质检单 ⚠️
    
    可能触发:
      - IP-2: D级品项→后厨任务
      - 库存数量更新
    
    风险原因: 影响库存和后续采购决策
    """

    UPDATE_SUPPLIER_SCORE = "update_supplier_score"
    """
    更新供应商评分 ⚠️
    
    可能触发:
      - IP-4: 低分→预警任务
    
    风险原因: 影响供应商推荐和采购决策
    """

    # ── 高风险写操作（必须人工审批！）───────────────────────────
    CREATE_PO = "create_po"
    """
    🔴 创建正式采购订单 (CRITICAL)
    
    ⚠️ 根据《最终方案》第六章明确规定:
      "AI 不自动创建正式采购订单"
    
    审批要求:
      - 必须通过 approve_purchase_task() 人工审批
      - 审批人必须是 purchaser 角色
      - 完整记录 who/when/why 审计链
    
    当前实现:
      - 仅可通过 SupplyChainManager.approve_purchase_task() 调用
      - create_po_from_suggestion() 已标记 @require_approval
    """

    APPROVE_PURCHASE = "approve_purchase"
    """
    🔴 审批采购任务并创建正式PO (HIGH)
    
    这是"人确认关键动作"环节！
    
    权限要求:
      - 仅 purchaser 角色可执行
      - 任务状态必须为 pending_approval
      - 记录 approved_by 审批人
    """

    CREATE_SUPPLIER = "create_supplier"
    """
    🔴 创建新供应商 (HIGH)
    
    影响:
      - 新增可选供应商池
      - 影响后续比价和推荐
    
    审批要求:
      - 采购负责人或店长审批
      - 需要基础资质验证
    """

    MODIFY_INVENTORY = "modify_inventory"
    """
    🔴 手动修改库存数据 (HIGH)
    
    ⚠️ 高风险: 可能影响预测准确性和采购建议
    建议: 仅限管理员在特殊情况下使用
    """

    CANCEL_PO = "cancel_po"
    """
    🔴 取消采购订单 (HIGH)
    
    影响:
      - 供应链中断风险
      - 可能产生违约金
    
    审批要求:
      - 创建人或上级可取消
      - 需填写取消原因
    """

    # ── 通知操作（自动执行，频率限制）────────────────────────────
    SEND_NOTIFICATION = "send_notification"
    """发送站内通知或企微消息"""

    PUSH_ALERT = "push_alert"
    """推送告警 (critical级别立即推送)"""

    GENERATE_REPORT = "generate_report"
    """生成报表 (损耗日报/周报等)"""


# =====================================================================
# 2. RiskLevel 枚举 — 风险等级定义
# =====================================================================

class RiskLevel(str, Enum):
    """
    行动风险等级

    决定 Gateway 的路由策略:
      - LOW: 直接执行 + 可选审计
      - MEDIUM: 执行 + 强制审计
      - HIGH: 不执行 → 创建审批任务 → 返回 task_id
      - CRITICAL: 不执行 → 创建双人审批任务 → 返回 task_id
      - BLOCKED: 拒绝执行 + 安全告警
    """

    LOW = "low"
    """🟢 低风险 - 自动执行 (读操作/低影响写操作)"""

    MEDIUM = "medium"
    """🟡 中风险 - 执行 + 强制审计 (间接影响核心业务)"""

    HIGH = "high"
    """🔴 高风险 - 必须人工审批 (创建/修改核心实体)"""

    CRITICAL = "critical"
    """🟣 严重风险 - 双人审批 (大额/敏感操作)"""

    BLOCKED = "blocked"
    """⛔ 已阻止 - 角色无权执行此操作"""


# =====================================================================
# 3. PermissionMatrix — 角色-行动权限矩阵
# =====================================================================

@dataclass
class PermissionRule:
    """单条权限规则"""
    action_type: ActionType
    risk_level: RiskLevel
    requires_approval: bool = False
    approval_role: Optional[str] = None  # 谁可以审批此行动
    description: str = ""
    max_frequency_per_hour: int = 0  # 0=无限制


class PermissionMatrix:
    """
    角色-行动权限矩阵 (RBAC)

    基于《最终方案》第七章"岗位Agent行动边界"定义:
      - 店长: 监控+分析+推荐+通知 (无execute权限)
      - 采购: 分析+预测+推荐+查询 (有限execute，需审批)
      - 后厨: 监控+通知+推荐 (纯观察者)
      - 供应商: 只读查询
      - 系统: 全权限 (仅内部调用)

    使用示例:
        # 检查权限
        rule = PermissionMatrix.check("purchaser", ActionType.APPROVE_PURCHASE)
        if rule.risk_level == RiskLevel.HIGH:
            # 需要创建审批任务
            task = gateway.create_approval_task(...)
        
        # 批量获取角色所有权限
        rules = PermissionMatrix.get_role_permissions("store_manager")
    """

    # ── 权限矩阵定义 ──────────────────────────────────────────
    MATRIX: Dict[str, Dict[ActionType, PermissionRule]] = {
        # ── 店长 (Store Manager) ────────────────────────────────
        "store_manager": {
            # ✅ 读操作
            ActionType.QUERY_DASHBOARD: PermissionRule(
                action_type=ActionType.QUERY_DASHBOARD,
                risk_level=RiskLevel.LOW,
                description="查看工作台KPI/待办/建议",
            ),
            ActionType.QUERY_TASKS: PermissionRule(
                action_type=ActionType.QUERY_TASKS,
                risk_level=RiskLevel.LOW,
                description="查看待办任务列表",
            ),
            ActionType.QUERY_SUGGESTIONS: PermissionRule(
                action_type=ActionType.QUERY_SUGGESTIONS,
                risk_level=RiskLevel.LOW,
                description="查看AI建议列表",
            ),
            ActionType.QUERY_PURCHASE_ORDERS: PermissionRule(
                action_type=ActionType.QUERY_PURCHASE_ORDERS,
                risk_level=RiskLevel.LOW,
                description="查看采购订单",
            ),

            # ✅ 低风险写操作
            ActionType.COMPLETE_TASK: PermissionRule(
                action_type=ActionType.COMPLETE_TASK,
                risk_level=RiskLevel.LOW,
                description="完成自己的待办任务",
            ),
            ActionType.DISMISS_TASK: PermissionRule(
                action_type=ActionType.DISMISS_TASK,
                risk_level=RiskLevel.LOW,
                description="忽略待办任务",
            ),
            ActionType.ACCEPT_SUGGESTION_LOW: PermissionRule(
                action_type=ActionType.ACCEPT_SUGGESTION_LOW,
                risk_level=RiskLevel.MEDIUM,
                description="采纳非采购建议 (审计)",
            ),
            ActionType.REJECT_SUGGESTION: PermissionRule(
                action_type=ActionType.REJECT_SUGGESTION,
                risk_level=RiskLevel.LOW,
                description="拒绝AI建议",
            ),

            # ⚠️ 中风险 (可执行但需审计)
            ActionType.ACCEPT_SUGGESTION_PURCHASE: PermissionRule(
                action_type=ActionType.ACCEPT_SUGGESTION_PURCHASE,
                risk_level=RiskLevel.MEDIUM,
                requires_approval=False,  # 店长可采纳，但只生成task不创建PO
                description="采纳采购建议 (触发IP-5审批流程)",
            ),

            # ❌ 无权执行的高风险操作
            ActionType.CREATE_PO: PermissionRule(
                action_type=ActionType.CREATE_PO,
                risk_level=RiskLevel.BLOCKED,
                description="❌ 店长不能直接创建PO",
            ),
            ActionType.APPROVE_PURCHASE: PermissionRule(
                action_type=ActionType.APPROVE_PURCHASE,
                risk_level=RiskLevel.BLOCKED,
                description="❌ 店长不能审批采购 (仅采购员可)",
            ),
            ActionType.CREATE_SUPPLIER: PermissionRule(
                action_type=ActionType.CREATE_SUPPLIER,
                risk_level=RiskLevel.BLOCKED,
                description="❌ 店长不能创建供应商",
            ),
            ActionType.MODIFY_INVENTORY: PermissionRule(
                action_type=ActionType.MODIFY_INVENTORY,
                risk_level=RiskLevel.BLOCKED,
                description="❌ 店长不能修改库存",
            ),
        },

        # ── 采购员 (Purchaser) ─────────────────────────────────
        "purchaser": {
            # ✅ 读操作
            ActionType.QUERY_DASHBOARD: PermissionRule(
                action_type=ActionType.QUERY_DASHBOARD,
                risk_level=RiskLevel.LOW,
                description="查看采购工作台",
            ),
            ActionType.QUERY_TASKS: PermissionRule(
                action_type=ActionType.QUERY_TASKS,
                risk_level=RiskLevel.LOW,
                description="查看待办任务",
            ),
            ActionType.QUERY_SUGGESTIONS: PermissionRule(
                action_type=ActionType.QUERY_SUGGESTIONS,
                risk_level=RiskLevel.LOW,
                description="查看采购建议",
            ),
            ActionType.QUERY_PURCHASE_ORDERS: PermissionRule(
                action_type=ActionType.QUERY_PURCHASE_ORDERS,
                risk_level=RiskLevel.LOW,
                description="查看采购订单",
            ),
            ActionType.QUERY_SUPPLIERS: PermissionRule(
                action_type=ActionType.QUERY_SUPPLIERS,
                risk_level=RiskLevel.LOW,
                description="查看供应商信息",
            ),

            # ✅ 低风险写操作
            ActionType.COMPLETE_TASK: PermissionRule(
                action_type=ActionType.COMPLETE_TASK,
                risk_level=RiskLevel.LOW,
                description="完成自己的待办任务",
            ),
            ActionType.REJECT_SUGGESTION: PermissionRule(
                action_type=ActionType.REJECT_SUGGESTION,
                risk_level=RiskLevel.LOW,
                description="拒绝AI建议",
            ),

            # ⚠️ 中风险 (可执行+审计)
            ActionType.ACCEPT_SUGGESTION_PURCHASE: PermissionRule(
                action_type=ActionType.ACCEPT_SUGGESTION_PURCHASE,
                risk_level=RiskLevel.MEDIUM,
                description="采纳采购建议 (触发IP-5)",
            ),
            ActionType.SUBMIT_RECEIVING: PermissionRule(
                action_type=ActionType.SUBMIT_RECEIVING,
                risk_level=RiskLevel.MEDIUM,
                description="提交收货质检单",
            ),
            ActionType.UPDATE_SUPPLIER_SCORE: PermissionRule(
                action_type=ActionType.UPDATE_SUPPLIER_SCORE,
                risk_level=RiskLevel.MEDIUM,
                description="更新供应商评分",
            ),

            # 🔴 高风险 (需审批)
            ActionType.APPROVE_PURCHASE: PermissionRule(
                action_type=ActionType.APPROVE_PURCHASE,
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                approval_role="purchaser",  # 采购员自审或上级复审
                description="🔴 审批采购任务并创建正式PO (人确认关键动作)",
            ),
            ActionType.CREATE_PO: PermissionRule(
                action_type=ActionType.CREATE_PO,
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                approval_role="purchaser",
                description="🔴 创建采购订单 (需审批)",
            ),
            ActionType.CREATE_SUPPLIER: PermissionRule(
                action_type=ActionType.CREATE_SUPPLIER,
                risk_level=RiskLevel.HIGH,
                requires_approval=True,
                approval_role="store_manager",  # 供应商创建需店长审批
                description="🔴 创建新供应商 (需店长审批)",
            ),

            # ❌ 无权操作
            ActionType.MODIFY_INVENTORY: PermissionRule(
                action_type=ActionType.MODIFY_INVENTORY,
                risk_level=RiskLevel.BLOCKED,
                description="❌ 采购员不能修改库存",
            ),
        },

        # ── 后厨人员 (Kitchen Staff) ────────────────────────────
        "kitchen_staff": {
            ActionType.QUERY_DASHBOARD: PermissionRule(
                action_type=ActionType.QUERY_DASHBOARD,
                risk_level=RiskLevel.LOW,
                description="查看后厨工作台",
            ),
            ActionType.COMPLETE_TASK: PermissionRule(
                action_type=ActionType.COMPLETE_TASK,
                risk_level=RiskLevel.LOW,
                description="完成后厨相关任务",
            ),
            # 其他操作均为 BLOCKED 或继承默认值
        },

        # ── 供应商 (Supplier Portal) ────────────────────────────
        "supplier": {
            ActionType.QUERY_DASHBOARD: PermissionRule(
                action_type=ActionType.QUERY_DASHBOARD,
                risk_level=RiskLevel.LOW,
                description="查看供应商门户",
            ),
            ActionType.QUERY_PURCHASE_ORDERS: PermissionRule(
                action_type=ActionType.QUERY_PURCHASE_ORDERS,
                risk_level=RiskLevel.LOW,
                description="查看相关采购订单",
            ),
            # 供应商只有只读权限
        },

        # ── 系统/内部调用 (System) ─────────────────────────────
        "_system": {
            # 系统拥有全部权限 (用于Integration Engine等内部调用)
            # 但仍需审计记录
            action: PermissionRule(
                action_type=action,
                risk_level=RiskLevel.LOW if action.name.startswith("QUERY") else RiskLevel.MEDIUM,
                description=f"[系统内部] {action.value}",
            )
            for action in ActionType
            if not action.name.startswith("QUERY")
        },
    }

    # ── 类方法 ─────────────────────────────────────────────────

    @classmethod
    def check(cls, role: str, action_type: ActionType) -> PermissionRule:
        """
        查询角色对某行动的权限规则

        Args:
            role: 角色标识 (store_manager, purchaser, kitchen_staff, supplier)
            action_type: 行动类型枚举

        Returns:
            PermissionRule: 包含 risk_level/requires_approval 等信息

        Raises:
            KeyError: 如果角色不存在于矩阵中
        """
        role_permissions = cls.MATRIX.get(role, {})
        
        # 精确匹配
        if action_type in role_permissions:
            return role_permissions[action_type]
        
        # 默认规则: 未明确授权的操作 = BLOCKED
        return PermissionRule(
            action_type=action_type,
            risk_level=RiskLevel.BLOCKED,
            description=f"⚠️ {role} 角色未授权此操作: {action_type.value}",
        )

    @classmethod
    def get_risk_level(cls, role: str, action_type: ActionType) -> RiskLevel:
        """快捷方法: 获取风险等级"""
        return cls.check(role, action_type).risk_level

    @classmethod
    def requires_approval(cls, role: str, action_type: ActionType) -> bool:
        """快捷方法: 是否需要审批"""
        return cls.check(role, action_type).requires_approval

    @classmethod
    def get_role_permissions(cls, role: str) -> Dict[ActionType, PermissionRule]:
        """获取角色的所有权限规则"""
        return cls.MATRIX.get(role, {})

    @classmethod
    def get_allowed_actions(cls, role: str, max_risk: RiskLevel = RiskLevel.MEDIUM) -> List[ActionType]:
        """
        获取角色允许的所有行动 (按风险等级过滤)

        Args:
            role: 角色
            max_risk: 最大允许风险等级 (默认MEDIUM，排除HIGH和BLOCKED)

        Returns:
            允许的行动列表
        """
        allowed = []
        for action_type, rule in cls.get_role_permissions(role).items:
            if rule.risk_level.value <= max_risk.value and rule.risk_level != RiskLevel.BLOCKED:
                allowed.append(action_type)
        return allowed

    @classmethod
    def validate_action(
        cls,
        role: str,
        action_type: ActionType,
        raise_on_blocked: bool = True,
    ) -> tuple:
        """
        验证行动是否被允许

        Returns:
            (is_allowed: bool, rule: PermissionRule, error_msg: Optional[str])
        """
        rule = cls.check(role, action_type)

        if rule.risk_level == RiskLevel.BLOCKED:
            error_msg = f"权限不足: {role} 无法执行 {action_type.value} - {rule.description}"
            if raise_on_blocked:
                raise PermissionDeniedError(error_msg)
            return (False, rule, error_msg)

        return (True, rule, None)


# =====================================================================
# 4. 自定义异常
# =====================================================================

class AgentGatewayError(Exception):
    """Agent Gateway 基础异常"""
    pass


class PermissionDeniedError(AgentGatewayError):
    """权限不足异常"""
    def __init__(self, message: str, role: str = "", action: ActionType = None):
        self.role = role
        self.action = action
        super().__init__(message)


class ApprovalRequiredError(AgentGatewayError):
    """需要审批异常 (HIGH风险操作的正常响应)"""
    def __init__(self, task_id: str, action_type: ActionType, message: str = ""):
        self.task_id = task_id
        self.action_type = action_type
        self.message = message or f"操作 {action_type.value} 需要审批，已创建任务 {task_id}"
        super().__init__(self.message)


# =====================================================================
# 5. 辅助函数
# =====================================================================

def infer_action_from_api_path(api_path: str, method: str = "GET") -> Optional[ActionType]:
    """
    从API路径推断 ActionType (用于快速接入现有端点)

    示例:
        infer_action_from_api_path("/assistant/tasks/{id}/complete", "POST")
        → ActionType.COMPLETE_TASK

        infer_action_from_api_path("/assistant/suggestions/{id}/accept", "PUT")
        → ActionType.ACCEPT_SUGGESTION_PURCHASE (如果suggestion_type=purchase_order)
    """
    path_mapping = {
        ("POST", "/dashboard"): ActionType.QUERY_DASHBOARD,
        ("GET", "/tasks"): ActionType.QUERY_TASKS,
        ("POST", "/tasks/{id}/complete"): ActionType.COMPLETE_TASK,
        ("POST", "/tasks/{id}/dismiss"): ActionType.DISMISS_TASK,
        ("GET", "/suggestions"): ActionType.QUERY_SUGGESTIONS,
        ("PUT", "/suggestions/{id}/accept"): ActionType.ACCEPT_SUGGESTION_PURCHASE,
        ("PUT", "/suggestions/{id}/reject"): ActionType.REJECT_SUGGESTION,
        ("POST", "/tasks/{id}/approve-purchase"): ActionType.APPROVE_PURCHASE,
        ("GET", "/purchase-orders"): ActionType.QUERY_PURCHASE_ORDERS,
        ("POST", "/suppliers"): ActionType.CREATE_SUPPLIER,
        ("POST", "/seed-demo"): ActionType.SEED_DEMO_DATA,
    }

    # 标准化路径 (移除ID参数)
    import re
    normalized = re.sub(r'\{[^}]+\}', '{id}', api_path.strip('/'))
    key = (method.upper(), normalized)

    return path_mapping.get(key)


def get_action_risk_description(action_type: ActionType) -> str:
    """获取行动的风险描述 (用于日志和UI展示)"""
    descriptions = {
        ActionType.CREATE_PO: "🔴 创建采购订单 [必须审批]",
        ActionType.APPROVE_PURCHASE: "🔴 审批采购 [人确认关键动作]",
        ActionType.CREATE_SUPPLIER: "🔴 创建供应商 [需审批]",
        ActionType.ACCEPT_SUGGESTION_PURCHASE: "🟡 采纳采购建议 [触发IP-5]",
        ActionType.SUBMIT_RECEIVING: "🟡 提交收货质检 [审计]",
        ActionType.COMPLETE_TASK: "🟢 完成任务 [自动]",
        ActionType.QUERY_DASHBOARD: "🟢 查看工作台 [自动]",
    }
    return descriptions.get(action_type, f"{action_type.value}")


# =====================================================================
# 6. 导出
# =====================================================================

__all__ = [
    # 枚举
    "ActionType",
    "RiskLevel",
    # 数据类
    "PermissionRule",
    "PermissionMatrix",
    # 异常
    "AgentGatewayError",
    "PermissionDeniedError",
    "ApprovalRequiredError",
    # 辅助函数
    "infer_action_from_api_path",
    "get_action_risk_description",
]


# =====================================================================
# 7. 自测代码 (模块级文档示例)
# =====================================================================

if __name__ == "__main__":
    print("=" * 70)
    print("🔍 ActionTypes & PermissionMatrix 自检")
    print("=" * 70)

    # 测试1: 枚举完整性
    print(f"\n✅ ActionType 总数: {len(ActionType)}")
    print(f"   - 读操作: {len([a for a in ActionType if a.name.startswith('QUERY')])}")
    print(f"   - 低风险: {len([a for a in ActionType if 'TASK' in a.name or 'LOW' in a.name])}")
    print(f"   - 中风险: {len([a for a in ActionType if 'PURCHASE' in a.name or 'RECEIVING' in a.name])}")
    print(f"   - 高风险: {len([a for a in ActionType if 'CREATE' in a.name or 'APPROVE' in a.name or 'MODIFY' in a.name])}")

    # 测试2: 权限矩阵检查
    print("\n📋 关键权限验证:")
    test_cases = [
        ("store_manager", ActionType.CREATE_PO, RiskLevel.BLOCKED),
        ("purchaser", ActionType.APPROVE_PURCHASE, RiskLevel.HIGH),
        ("purchaser", ActionType.QUERY_DASHBOARD, RiskLevel.LOW),
        ("kitchen_staff", ActionType.CREATE_PO, RiskLevel.BLOCKED),
    ]

    for role, action, expected_risk in test_cases:
        actual_risk = PermissionMatrix.get_risk_level(role, action)
        status = "✅" if actual_risk == expected_risk else "❌"
        print(f"  {status} {role:15} + {action.value:30} → {actual_risk.value:10} (期望: {expected_risk.value})")

    # 测试3: API路径推断
    print("\n🔗 API路径推断测试:")
    api_tests = [
        ("POST", "/assistant/tasks/{id}/complete"),
        ("PUT", "/assistant/suggestions/{id}/accept"),
        ("POST", "/assistant/tasks/{id}/approve-purchase"),
    ]
    for method, path in api_tests:
        inferred = infer_action_from_api_path(path, method)
        print(f"  {method:4} {path:50} → {inferred.value if inferred else '❌ 未匹配'}")

    print("\n" + "=" * 70)
    print("✅ ActionTypes 模块自检完成")
    print("=" * 70)
