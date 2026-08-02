"""
D2 岗位 AI 助理 API 层
=======================
13个REST端点，覆盖A01店长座舱/A02后厨/A03采购/A04供应商端
所有端点 L2 PIN 保护 (Depends(get_current_session))
"""

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel
from typing import Optional
from datetime import datetime

from hotpot_platform.auth.session import get_current_session
from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

router = APIRouter()


# =====================================================================
# Request/Response Models
# =====================================================================

class CompleteTaskRequest(BaseModel):
    """完成待办"""
    note: Optional[str] = None

class AcceptSuggestionRequest(BaseModel):
    """采纳建议"""
    note: Optional[str] = None


# =====================================================================
# A01 店长数字座舱
# =====================================================================

@router.get("/assistant/dashboard")
async def get_dashboard(session: dict = Depends(get_current_session)):
    """A01 店长数字座舱完整数据（KPI + 待办 + 建议 + 趋势）"""
    data = SupplyChainManager.get_store_manager_dashboard()
    return {"code": 0, "data": data, "msg": "ok"}


@router.get("/assistant/dashboard/kpi")
async def get_dashboard_kpi(session: dict = Depends(get_current_session)):
    """KPI 指标卡片数据"""
    dashboard = SupplyChainManager.get_store_manager_dashboard()
    return {"code": 0, "data": dashboard.get("kpis", []), "msg": "ok"}


@router.get("/assistant/dashboard/full")
async def get_dashboard_full(
    include_kitchen: bool = Query(False, description="是否包含A02后厨面板"),
    include_purchase: bool = Query(False, description="是否包含A03采购面板"),
    session: dict = Depends(get_current_session),
):
    """
    A01+ 增强版完整工作台 (Dashboard Full API)

    聚合所有面板数据，用于展会S4场景"店长工作台"展示:
    - 基础: KPI + Tasks + Suggestions + Trends (来自A01)
    - 可选: A02后厨助理面板 (备货+温控+SOP)
    - 可选: A03采购助理面板 (PO跟踪+比价)
    - 额外: D3集成引擎指标
    """
    data = SupplyChainManager.get_dashboard_full(
        include_kitchen=include_kitchen,
        include_purchase=include_purchase,
    )
    return {"code": 0, "data": data, "msg": "ok"}


# =====================================================================
# 待办事项 CRUD
# =====================================================================

@router.get("/assistant/tasks")
async def get_tasks(
    role: str = Query("store_manager", description="角色过滤"),
    status: str = Query("pending", description="状态过滤: pending/completed/dismissed/all"),
    session: dict = Depends(get_current_session),
):
    """获取当前角色待办列表（按优先级排序）"""
    tasks = SupplyChainManager.get_tasks(role=role, status=status)
    return {"code": 0, "data": tasks, "total": len(tasks), "msg": "ok"}


@router.get("/assistant/tasks/{task_id}")
async def get_task_detail(task_id: str, session: dict = Depends(get_current_session)):
    """待办详情"""
    task = SupplyChainManager.get_task_detail(task_id)
    if not task:
        raise HTTPException(status_code=404, detail=f"待办不存在: {task_id}")
    return {"code": 0, "data": task, "msg": "ok"}


@router.put("/assistant/tasks/{task_id}/complete")
async def complete_task(
    task_id: str,
    req: Optional[CompleteTaskRequest] = None,
    session: dict = Depends(get_current_session),
):
    """完成待办事项"""
    ok = SupplyChainManager.complete_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"待办不存在: {task_id}")
    return {"code": 0, "msg": "待办已完成", "data": {"task_id": task_id}}


@router.put("/assistant/tasks/{task_id}/dismiss")
async def dismiss_task(
    task_id: str,
    session: dict = Depends(get_current_session),
):
    """忽略/关闭待办"""
    ok = SupplyChainManager.dismiss_task(task_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"待办不存在: {task_id}")
    return {"code": 0, "msg": "待办已忽略", "data": {"task_id": task_id}}


# =====================================================================
# 采购审批流程（IP-5修正：符合最终方案要求）
# =====================================================================

class ApprovePurchaseTaskRequest(BaseModel):
    """采购任务审批请求"""
    approved_by: str = Field("manual", description="审批人标识（role或user_id）")
    notes: Optional[str] = Field(None, description="审批备注")


@router.post("/assistant/tasks/{task_id}/approve-purchase")
async def approve_purchase_task(
    task_id: str,
    req: ApprovePurchaseTaskRequest,
    session: dict = Depends(get_current_session),
):
    """
    审批采购任务 → 创建正式采购订单

    ⚠️ 这是IP-5流程的"人确认关键动作"环节
    根据《火瞳餐饮AI智能体运营系统_最终方案》第七章:
    - 采购Agent: "可生成建议和待办；**正式下单必须审批**"
    - 收货/质检Agent: "最终签字由授权人员完成"

    流程:
    用户调用此API → 系统验证任务状态 → 调用create_po_from_suggestion()
    → 返回PO信息 + 更新任务审计记录
    """
    # 执行审批
    result = SupplyChainManager.approve_purchase_task(
        task_id=task_id,
        approved_by=req.approved_by or session.get("user", {}).get("role", "unknown"),
    )

    if not result:
        # 区分不同错误类型
        task = SupplyChainManager.get_task_detail(task_id)
        if not task:
            raise HTTPException(status_code=404, detail=f"采购任务不存在: {task_id}")
        elif task.get("status") == "approved":
            raise HTTPException(status_code=400, detail="该任务已审批通过，请勿重复操作")
        elif task.get("status") != "pending_approval":
            raise HTTPException(status_code=400, detail=f"任务状态不允许审批: {task.get('status')}")
        else:
            raise HTTPException(status_code=500, detail="审批处理失败，请查看系统日志")

    return {
        "code": 0,
        "msg": "✅ 采购任务审批通过，正式PO已创建",
        "data": result,
    }


@router.get("/assistant/tasks/purchase/pending")
async def get_pending_purchase_tasks(
    session: dict = Depends(get_current_session),
):
    """获取待审批的采购任务列表（IP-5修正后新增）"""
    all_tasks = SupplyChainManager.get_tasks(role="purchaser", status="pending")

    # 过滤出采购审批类型的待办
    purchase_tasks = [
        t for t in all_tasks
        if t.get("type") == "purchase_approval" and t.get("status") == "pending_approval"
    ]

    return {
        "code": 0,
        "data": purchase_tasks,
        "total": len(purchase_tasks),
        "msg": f"共{len(purchase_tasks)}个待审批采购任务",
    }


# =====================================================================
# AI 建议操作
# =====================================================================

@router.get("/assistant/suggestions")
async def get_suggestions(
    role: str = Query("store_manager", description="角色过滤"),
    session: dict = Depends(get_current_session),
):
    """AI 建议列表"""
    suggestions = SupplyChainManager.get_suggestions(role=role)
    return {"code": 0, "data": suggestions, "total": len(suggestions), "msg": "ok"}


@router.put("/assistant/suggestions/{suggestion_id}/accept")
async def accept_suggestion(
    suggestion_id: str,
    req: Optional[AcceptSuggestionRequest] = None,
    session: dict = Depends(get_current_session),
):
    """采纳AI建议"""
    ok = SupplyChainManager.accept_suggestion(suggestion_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"建议不存在: {suggestion_id}")
    return {"code": 0, "msg": "建议已采纳", "data": {"suggestion_id": suggestion_id}}


@router.put("/assistant/suggestions/{suggestion_id}/reject")
async def reject_suggestion(
    suggestion_id: str,
    req: Optional[AcceptSuggestionRequest] = None,
    session: dict = Depends(get_current_session),
):
    """拒绝AI建议"""
    ok = SupplyChainManager.reject_suggestion(suggestion_id)
    if not ok:
        raise HTTPException(status_code=404, detail=f"建议不存在: {suggestion_id}")
    return {"code": 0, "msg": "建议已拒绝", "data": {"suggestion_id": suggestion_id}}


# =====================================================================
# A02 后厨助理面板
# =====================================================================

@router.get("/assistant/kitchen")
async def get_kitchen_panel(session: dict = Depends(get_current_session)):
    """A02 后厨助理面板（备货清单+温控+SOP+废料）"""
    data = SupplyChainManager.get_kitchen_assistant_panel()
    return {"code": 0, "data": data, "msg": "ok"}


# =====================================================================
# A03 采购助理面板
# =====================================================================

@router.get("/assistant/purchase")
async def get_purchase_panel(session: dict = Depends(get_current_session)):
    """A03 采购助理面板（建议+PO跟踪+比价）"""
    data = SupplyChainManager.get_purchase_assistant_panel()
    return {"code": 0, "data": data, "msg": "ok"}


# =====================================================================
# A04 供应商协同端
# =====================================================================

@router.get("/assistant/supplier-portal")
async def get_supplier_portal(
    supplier_id: Optional[str] = Query(None, description="供应商ID(可选)"),
    session: dict = Depends(get_current_session),
):
    """A04 供应商协同端"""
    try:
        data = SupplyChainManager.get_supplier_portal(supplier_id=supplier_id)
        return {"code": 0, "data": data, "msg": "ok"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# =====================================================================
# Demo 数据
# =====================================================================

@router.post("/assistant/seed-demo")
async def seed_demo_assistant_data(session: dict = Depends(get_current_session)):
    """加载 AI 助理 Demo 数据（展会演示用）"""
    count = SupplyChainManager.seed_demo_assistant_data()
    return {
        "code": 0,
        "msg": f"Demo AI 助理数据加载完成",
        "data": {
            "tasks_count": count,
            "loaded_at": datetime.now().isoformat(),
        },
    }
