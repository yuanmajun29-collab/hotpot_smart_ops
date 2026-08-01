"""
D1-S04 供应商协同与评分 — REST API 层

端点清单 (17个):
  POST   /suppliers              创建供应商
  GET    /suppliers              列表(筛选+排序+分页)
  GET    /suppliers/{id}         详情
  PUT    /suppliers/{id}         编辑
  DELETE /suppliers/{id}         删除(仅pending)
  POST   /suppliers/{id}/activate    激活
  POST   /suppliers/{id}/suspend     停用
  POST   /suppliers/{id}/blacklist   拉黑
  POST   /suppliers/{id}/restore     恢复
  GET    /suppliers/{id}/score       评分详情
  GET    /suppliers/{id}/score-history  评分历史
  POST   /suppliers/{id}/adjust-score  人工调分
  GET    /suppliers/{id}/orders       关联订单
  GET    /suppliers/ranking           排行榜
  GET    /suppliers/stats             统计概览
  POST   /suppliers/seed-demo         Demo数据

权限: 全部 L2 PIN 保护
"""

import logging
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from pydantic import BaseModel, Field

from middleware import get_current_session
from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager

logger = logging.getLogger(__name__)
router = APIRouter()


# ============================================================
# Request/Response Models
# ============================================================

class CreateSupplierRequest(BaseModel):
    name: str = Field(..., min_length=2, max_length=50)
    contact_person: str = ""
    phone: str = ""
    address: str = ""
    license_no: Optional[str] = None
    supplied_skus: Optional[List[str]] = None
    contract_start: Optional[date] = None
    contract_end: Optional[date] = None
    notes: Optional[str] = None


class UpdateSupplierRequest(BaseModel):
    contact_person: Optional[str] = None
    phone: Optional[str] = None
    address: Optional[str] = None
    license_no: Optional[str] = None
    supplied_skus: Optional[List[str]] = None
    contract_start: Optional[date] = None
    contract_end: Optional[date] = None
    notes: Optional[str] = None


class StatusActionRequest(BaseModel):
    reason: str = ""


class AdjustScoreRequest(BaseModel):
    adjustment: float = Field(..., ge=-10, le=10)
    reason: str = Field(..., min_length=2)


# ============================================================
# CRUD 端点
# ============================================================

@router.post("/suppliers")
async def create_supplier(
    req: CreateSupplierRequest,
    _session: dict = Depends(get_current_session),
):
    """创建供应商档案 (BR-05: 初始状态=pending)"""
    try:
        supplier = SupplyChainManager.create_supplier(
            name=req.name,
            contact_person=req.contact_person,
            phone=req.phone,
            address=req.address,
            license_no=req.license_no,
            supplied_skus=req.supplied_skus,
            contract_start=req.contract_start,
            contract_end=req.contract_end,
            notes=req.notes,
        )
        return {"code": 0, "data": supplier}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/suppliers")
async def list_suppliers(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None),
    keyword: Optional[str] = Query(None),
    grade: Optional[str] = Query(None),
    sort_by: str = Query("-score_overall"),
    _session: dict = Depends(get_current_session),
):
    """供应商列表（筛选+排序+分页）"""
    result = SupplyChainManager.get_supplier_list(
        page=page, page_size=page_size,
        status=status, keyword=keyword, grade=grade, sort_by=sort_by,
    )
    return {"code": 0, "data": result}


@router.get("/suppliers/{supplier_id}")
async def get_supplier(
    supplier_id: str,
    _session: dict = Depends(get_current_session),
):
    """供应商详情"""
    try:
        supplier = SupplyChainManager.get_supplier_detail(supplier_id)
        return {"code": 0, "data": supplier}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")


@router.put("/suppliers/{supplier_id}")
async def update_supplier(
    supplier_id: str,
    req: UpdateSupplierRequest,
    _session: dict = Depends(get_current_session),
):
    """编辑供应商信息"""
    try:
        update_data = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
        if not update_data:
            raise HTTPException(status_code=400, detail="无更新内容")
        supplier = SupplyChainManager.update_supplier(supplier_id, **update_data)
        return {"code": 0, "data": supplier}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/suppliers/{supplier_id}")
async def delete_supplier(
    supplier_id: str,
    _session: dict = Depends(get_current_session),
):
    """删除供应商（仅允许pending状态）"""
    try:
        SupplyChainManager.delete_supplier(supplier_id)
        return {"code": 0, "message": "删除成功"}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================
# 状态流转端点
# ============================================================

@router.post("/suppliers/{supplier_id}/activate")
async def activate_supplier(
    supplier_id: str,
    _session: dict = Depends(get_current_session),
):
    """激活供应商 (pending→active) + 初始化评分"""
    try:
        supplier = SupplyChainManager.activate_supplier(supplier_id)
        return {"code": 0, "data": supplier}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/suppliers/{supplier_id}/suspend")
async def suspend_supplier(
    supplier_id: str,
    req: StatusActionRequest = StatusActionRequest(),
    _session: dict = Depends(get_current_session),
):
    """停用供应商 (active/probation→suspended) BR-08"""
    try:
        supplier = SupplyChainManager.suspend_supplier(supplier_id, reason=req.reason)
        return {"code": 0, "data": supplier}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/suppliers/{supplier_id}/blacklist")
async def blacklist_supplier(
    supplier_id: str,
    req: StatusActionRequest,
    _session: dict = Depends(get_current_session),
):
    """拉黑供应商 (suspended→blacklisted) BR-12"""
    if not req.reason:
        raise HTTPException(status_code=400, detail="拉黑原因为必填项")
    try:
        supplier = SupplyChainManager.blacklist_supplier(supplier_id, reason=req.reason)
        return {"code": 0, "data": supplier}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/suppliers/{supplier_id}/restore")
async def restore_supplier(
    supplier_id: str,
    _session: dict = Depends(get_current_session),
):
    """恢复供应商 (suspended/blacklisted→active) BR-11/13"""
    try:
        supplier = SupplyChainManager.restore_supplier(supplier_id)
        return {"code": 0, "data": supplier}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================
# 评分相关端点
# ============================================================

@router.get("/suppliers/{supplier_id}/score")
async def get_supplier_score(
    supplier_id: str,
    _session: dict = Depends(get_current_session),
):
    """供应商评分详情（四维+历史快照+调整记录）"""
    try:
        score_detail = SupplyChainManager.get_supplier_score(supplier_id)
        return {"code": 0, "data": score_detail}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")


@router.get("/suppliers/{supplier_id}/score-history")
async def get_score_history(
    supplier_id: str,
    _session: dict = Depends(get_current_session),
):
    """评分历史趋势（月度快照列表）"""
    try:
        history = SupplyChainManager.get_score_history(supplier_id)
        return {"code": 0, "data": history}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")


@router.post("/suppliers/{supplier_id}/adjust-score")
async def adjust_score(
    supplier_id: str,
    req: AdjustScoreRequest,
    _session: dict = Depends(get_current_session),
):
    """人工调整评分 (单次±10限制)"""
    operator = _session.get("user_id", "system")
    try:
        supplier = SupplyChainManager.adjust_score(
            supplier_id=supplier_id,
            adjustment=req.adjustment,
            reason=req.reason,
            operator=operator,
        )
        return {"code": 0, "data": supplier}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


# ============================================================
# 关联数据端点
# ============================================================

@router.get("/suppliers/{supplier_id}/orders")
async def get_supplier_orders(
    supplier_id: str,
    _session: dict = Depends(get_current_session),
):
    """关联采购订单列表"""
    try:
        orders = SupplyChainManager.get_supplier_orders(supplier_id)
        return {"code": 0, "data": orders}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"供应商不存在: {supplier_id}")


@router.get("/suppliers/ranking")
async def get_supplier_ranking(
    limit: int = Query(10, ge=1, le=50),
    _session: dict = Depends(get_current_session),
):
    """供应商排行榜（按评分降序）"""
    ranking = SupplyChainManager.get_supplier_ranking(limit=limit)
    return {"code": 0, "data": ranking}


@router.get("/suppliers/stats")
async def get_supplier_stats(
    _session: dict = Depends(get_current_session),
):
    """供应商统计概览"""
    stats = SupplyChainManager.get_supplier_stats()
    return {"code": 0, "data": stats}


# ============================================================
# Demo 数据
# ============================================================

@router.post("/suppliers/seed-demo")
async def seed_demo_suppliers(
    _session: dict = Depends(get_current_session),
):
    """加载Demo种子数据 - 5个供应商覆盖全部状态和等级"""
    count = SupplyChainManager.seed_demo_suppliers()
    return {
        "code": 0,
        "message": f"Demo供应商数据加载完成: {count} 个",
        "data": {"count": count},
    }
