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
