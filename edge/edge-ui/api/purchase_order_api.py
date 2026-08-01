"""
火瞳 · Edge UI — 采购订单 API (S03)

对应 PRD D1-S03: 冻品供应链 — 采购订单管理

端点:
  POST   /api/v1/purchase-orders                  创建采购订单
  GET    /api/v1/purchase-orders                  订单列表 (分页+筛选)
  GET    /api/v1/purchase-orders/{po_number}      订单详情
  PUT    /api/v1/purchase-orders/{po_number}      更新订单 (仅draft)
  DELETE /api/v1/purchase-orders/{po_number}      删除草稿订单
  POST   /api/v1/purchase-orders/{po_number}/submit       提交确认
  POST   /api/v1/purchase-orders/{po_number}/confirm      审批确认
  POST   /api/v1/purchase-orders/{po_number}/cancel       取消订单
  POST   /api/v1/purchase-orders/{po_number}/return-draft 退回草稿
  POST   /api/v1/purchase-orders/{po_number}/mark-received 手动标记收货
  GET    /api/v1/purchase-orders/{po_number}/receiving     关联收货记录
  GET    /api/v1/purchase-orders/stats             采购统计概览
  GET    /api/v1/purchase-orders/suppliers/{name}/history  供应商采购历史
  POST   /api/v1/purchase-orders/seed-demo         加载Demo数据

认证: 所有端点受 L2 PIN 保护 (Depends 模式)
"""

import logging
import os
from typing import Optional, List, Dict, Any

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import BaseModel, Field

# 认证依赖
from middleware import get_current_session

# 数据层
from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager
from hotpot_platform.cloud.supply_chain.models import (
    PurchaseOrder,
    PurchaseOrderItem,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 数据存储路径 (与S01/S02共享同一数据文件) ──
DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCT_DATA_FILE = os.path.join(DATA_DIR, "data", "product_master.json")

# ── 初始化标志 ──
_initialized = False


def _ensure_init():
    """确保数据已初始化（懒加载，复用S01的初始化）。"""
    global _initialized
    if not _initialized:
        os.makedirs(os.path.dirname(PRODUCT_DATA_FILE), exist_ok=True)
        SupplyChainManager.init_product_data(PRODUCT_DATA_FILE)
        _initialized = True
        logger.info("采购订单模块已初始化: %s", PRODUCT_DATA_FILE)


# ============================================================
# 请求/响应模型
# ============================================================

class POItemRequest(BaseModel):
    """订单行项目请求"""
    sku: str = Field(..., description="SKU编码")
    quantity: float = Field(..., gt=0, description="数量")
    unit_price: Optional[float] = Field(None, ge=0, description="单价(可选,默认取主数据)")
    supplier: Optional[str] = None
    expected_date: Optional[str] = None
    notes: Optional[str] = None


class CreatePORequest(BaseModel):
    """创建采购订单请求"""
    supplier: Optional[str] = Field(None, description="供应商名称")
    delivery_address: Optional[str] = Field(None, description="送货地址")
    expected_date: Optional[str] = Field(None, description="期望到货日期 YYYY-MM-DD")
    notes: Optional[str] = None
    items: List[POItemRequest] = Field(
        ..., min_length=1, description="订单行项目列表(至少1项)"
    )


class UpdatePORequest(BaseModel):
    """更新采购订单请求（仅draft）"""
    supplier: Optional[str] = None
    delivery_address: Optional[str] = None
    expected_date: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[List[POItemRequest]] = None


class ConfirmPORequest(BaseModel):
    """确认订单请求"""
    notes: Optional[str] = Field(None, description="确认备注")


class CancelPORequest(BaseModel):
    """取消订单请求"""
    reason: str = Field(..., min_length=1, description="取消原因")


class MarkReceivedRequest(BaseModel):
    """标记收货请求"""
    received_by: Optional[str] = Field(None, description="收货确认人")


# ============================================================
# 端点实现
# ============================================================

@router.post("/purchase-orders", response_model=dict, status_code=201)
async def create_purchase_order(
    body: CreatePORequest,
    session: dict = Depends(get_current_session),
):
    """
    创建采购订单

    基于S01货品主数据选择SKU，自动计算金额。
    BR-01~BR-07 校验。
    """
    _ensure_init()
    try:
        order_data = {
            "store_id": session.get("store_id", "store-jiaojiang"),
            "ordered_by": f"{session.get('role', '店长')}-{session.get('username', '用户')}",
            "supplier": body.supplier,
            "delivery_address": body.delivery_address,
            "expected_date": body.expected_date,
            "notes": body.notes,
            "items": [item.model_dump() for item in body.items],
        }
        order = SupplyChainManager.create_purchase_order(order_data)
        return {"code": 0, "message": "OK", "data": order.model_dump()}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("创建采购订单失败: %s", e)
        raise HTTPException(status_code=500, detail=f"内部错误: {e}")


@router.get("/purchase-orders", response_model=dict)
async def list_purchase_orders(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    status: Optional[str] = Query(None, description="状态筛选"),
    supplier: Optional[str] = Query(None, description="供应商筛选"),
    start_date: Optional[str] = Query(None, description="开始日期"),
    end_date: Optional[str] = Query(None, description="结束日期"),
    session: dict = Depends(get_current_session),
):
    """采购订单列表（分页+多维度筛选）"""
    _ensure_init()
    result = SupplyChainManager.get_po_list(
        page=page, page_size=page_size,
        status=status, supplier=supplier,
        start_date=start_date, end_date=end_date,
    )
    return {"code": 0, "message": "OK", "data": result}


@router.get("/purchase-orders/{po_number}", response_model=dict)
async def get_purchase_order_detail(
    po_number: str,
    session: dict = Depends(get_current_session),
):
    """获取采购订单详情"""
    _ensure_init()
    try:
        order = SupplyChainManager.get_po_detail(po_number)
        return {"code": 0, "message": "OK", "data": order.model_dump()}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"订单不存在: {po_number}")


@router.put("/purchase-orders/{po_number}", response_model=dict)
async def update_purchase_order(
    po_number: str,
    body: UpdatePORequest,
    session: dict = Depends(get_current_session),
):
    """更新采购订单（仅draft状态, BR-08）"""
    _ensure_init()
    try:
        update_data = body.model_dump(exclude_none=True)
        order = SupplyChainManager.update_purchase_order(po_number, update_data)
        return {"code": 0, "message": "OK", "data": order.model_dump()}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"订单不存在: {po_number}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/purchase-orders/{po_number}", response_model=dict, status_code=204)
async def delete_purchase_order(
    po_number: str,
    session: dict = Depends(get_current_session),
):
    """删除草稿订单"""
    _ensure_init()
    try:
        SupplyChainManager.delete_purchase_order(po_number)
        return None  # 204 No Content
    except KeyError:
        raise HTTPException(status_code=404, detail=f"订单不存在: {po_number}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/purchase-orders/{po_number}/submit", response_model=dict)
async def submit_purchase_order(
    po_number: str,
    session: dict = Depends(get_current_session),
):
    """提交采购订单（draft → submitted）"""
    _ensure_init()
    try:
        order = SupplyChainManager.submit_po(po_number)
        return {"code": 0, "message": "提交成功", "data": order.model_dump()}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"订单不存在: {po_number}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/purchase-orders/{po_number}/confirm", response_model=dict)
async def confirm_purchase_order(
    po_number: str,
    body: ConfirmPORequest = ConfirmPORequest(),
    session: dict = Depends(get_current_session),
):
    """审批确认采购订单（submitted → confirmed, 曹总操作）"""
    _ensure_init()
    try:
        order = SupplyChainManager.confirm_po(po_number, notes=body.notes)
        return {"code": 0, "message": "确认成功", "data": order.model_dump()}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"订单不存在: {po_number}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/purchase-orders/{po_number}/cancel", response_model=dict)
async def cancel_purchase_order(
    po_number: str,
    body: CancelPORequest,
    session: dict = Depends(get_current_session),
):
    """取消采购订单（BR-09~BR-11）"""
    _ensure_init()
    try:
        order = SupplyChainManager.cancel_po(po_number, reason=body.reason)
        return {"code": 0, "message": "取消成功", "data": order.model_dump()}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"订单不存在: {po_number}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/purchase-orders/{po_number}/return-draft", response_model=dict)
async def return_po_to_draft(
    po_number: str,
    session: dict = Depends(get_current_session),
):
    """退回草稿（submitted → draft）"""
    _ensure_init()
    try:
        order = SupplyChainManager.return_po_to_draft(po_number)
        return {"code": 0, "message": "已退回草稿", "data": order.model_dump()}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"订单不存在: {po_number}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/purchase-orders/{po_number}/mark-received", response_model=dict)
async def mark_po_received(
    po_number: str,
    body: MarkReceivedRequest = MarkReceivedRequest(),
    session: dict = Depends(get_current_session),
):
    """手动标记全部收货（confirmed/partial → received）"""
    _ensure_init()
    try:
        order = SupplyChainManager.mark_po_received(
            po_number, received_by=body.received_by or session.get("username", "")
        )
        return {"code": 0, "message": "标记成功", "data": order.model_dump()}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"订单不存在: {po_number}")
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.get("/purchase-orders/{po_number}/receiving", response_model=dict)
async def get_po_receiving_links(
    po_number: str,
    session: dict = Depends(get_current_session),
):
    """获取PO关联的收货记录列表（S02联动）"""
    _ensure_init()
    try:
        links = SupplyChainManager.get_po_receiving_links(po_number)
        return {"code": 0, "message": "OK", "data": links}
    except KeyError:
        raise HTTPException(status_code=404, detail=f"订单不存在: {po_number}")


@router.get("/purchase-orders/stats", response_model=dict)
async def get_po_stats(
    session: dict = Depends(get_current_session),
):
    """采购统计概览"""
    _ensure_init()
    stats = SupplyChainManager.get_po_stats(store_id=session.get("store_id", "store-jiaojiang"))
    return {"code": 0, "message": "OK", "data": stats}


@router.get("/purchase-orders/suppliers/{supplier_name}/history", response_model=dict)
async def get_supplier_po_history(
    supplier_name: str,
    session: dict = Depends(get_current_session),
):
    """供应商采购历史趋势"""
    _ensure_init()
    history = SupplyChainManager.get_supplier_po_history(supplier_name)
    return {"code": 0, "message": "OK", "data": history}


@router.post("/purchase-orders/seed-demo", response_model=dict)
async def seed_demo_po_data(
    session: dict = Depends(get_current_session),
):
    """加载展会Demo用的采购订单种子数据（4种场景）"""
    _ensure_init()
    count = SupplyChainManager.seed_demo_po_data()
    return {
        "code": 0,
        "message": f"Demo数据加载完成: {count} 条",
        "data": {"loaded_count": count},
    }
