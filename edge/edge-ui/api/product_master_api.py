"""
火瞳 · Edge UI — 货品主数据管理 API (S01)

对应 PRD D1-S01: 冻品供应链 — 货品主数据管理

端点:
  GET    /api/v1/products              货品列表 (分页/搜索/筛选)
  GET    /api/v1/products/stats         统计概览
  GET    /api/v1/products/categories    品类列表
  GET    /api/v1/products/{sku_code}    货品详情
  POST   /api/v1/products              新建货品
  PUT    /api/v1/products/{sku_code}    更新货品
  POST   /api/v1/products/{sku_code}/lock    锁定货品
  POST   /api/v1/products/{sku_code}/unlock  解锁货品
  DELETE /api/v1/products/{sku_code}    删除货品 (仅draft)
  POST   /api/v1/products/init          初始化种子数据
  POST   /api/v1/products/{sku_code}/change  提交变更申请
  GET    /api/v1/products/changes       变更申请列表
  POST   /api/v1/products/changes/{id}/approve  审批变更

认证: 所有端点受 L2 PIN 保护 (Depends 模式)
"""

import logging
import os
from typing import Optional, List

from fastapi import APIRouter, HTTPException, Query, Depends
from pydantic import Field

# 认证依赖
from middleware import get_current_session

# 数据层
from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager
from hotpot_platform.cloud.supply_chain.models import (
    ProductMaster,
    ProductCategory,
    ChangeRequest,
    ProductCreateRequest,
    ProductUpdateRequest,
    ProductListResponse,
    ProductStatsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 数据存储路径 ──
DATA_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PRODUCT_DATA_FILE = os.path.join(DATA_DIR, "data", "product_master.json")

# ── 初始化标志 ──
_initialized = False


def _ensure_init():
    """确保货品数据已初始化（懒加载）。"""
    global _initialized
    if not _initialized:
        os.makedirs(os.path.dirname(PRODUCT_DATA_FILE), exist_ok=True)
        SupplyChainManager.init_product_data(PRODUCT_DATA_FILE)
        _initialized = True
        logger.info("货品主数据模块已初始化: %s", PRODUCT_DATA_FILE)


# ============================================================
# 端点实现
# ============================================================

@router.get("/products", response_model=ProductListResponse, tags=["货品主数据"])
async def list_products(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    keyword: str = Query("", description="搜索关键词(名称/品牌/SKU)"),
    category: str = Query("", description="品类筛选"),
    status: str = Query("", description="状态筛选(draft/active/discontinued)"),
    _: dict = Depends(get_current_session),
):
    """货品列表（分页 + 搜索 + 筛选）。"""
    _ensure_init()
    return SupplyChainManager.list_product_masters(
        page=page, page_size=page_size,
        keyword=keyword, category=category, status=status,
    )


@router.get("/products/stats", response_model=ProductStatsResponse, tags=["货品主数据"])
async def get_product_stats(_: dict = Depends(get_current_session)):
    """货品统计概览。"""
    _ensure_init()
    return SupplyChainManager.get_product_stats()


@router.get("/categories", response_model=List[ProductCategory], tags=["货品主数据"])
async def get_categories(_: dict = Depends(get_current_session)):
    """获取可用品类分类列表。"""
    _ensure_init()
    return SupplyChainManager.get_categories()


@router.get("/products/{sku_code}", response_model=ProductMaster, tags=["货品主数据"])
async def get_product(sku_code: str, _: dict = Depends(get_current_session)):
    """按 SKU 查询货品详情。"""
    _ensure_init()
    product = SupplyChainManager.get_product_by_sku(sku_code)
    if not product:
        raise HTTPException(status_code=404, detail=f"SKU 不存在: {sku_code}")
    return product


@router.post("/products", response_model=ProductMaster, status_code=201, tags=["货品主数据"])
async def create_product(req: ProductCreateRequest, operator: dict = Depends(get_current_session)):
    """新建货品主数据。"""
    _ensure_init()
    try:
        return SupplyChainManager.create_product_master(req, operator=operator.get("user_id", "admin"))
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        logger.error("创建货品失败: %s", e)
        raise HTTPException(status_code=500, detail=f"创建失败: {str(e)}")


@router.put("/products/{sku_code}", response_model=ProductMaster, tags=["货品主数据"])
async def update_product(
    sku_code: str, req: ProductUpdateRequest, operator: dict = Depends(get_current_session)
):
    """更新货品主数据（未锁定时可修改全部字段，锁定后仅非关键字段）。"""
    _ensure_init()
    try:
        return SupplyChainManager.update_product_master(
            sku_code, req, operator=operator.get("user_id", "admin")
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except Exception as e:
        logger.error("更新货品失败: %s", e)
        raise HTTPException(status_code=500, detail=f"更新失败: {str(e)}")


@router.post("/products/{sku_code}/lock", response_model=ProductMaster, tags=["货品主数据"])
async def lock_product(sku_code: str, operator: dict = Depends(get_current_session)):
    """锁定货品标准（锁定后关键字段不可直接修改）。"""
    _ensure_init()
    try:
        return SupplyChainManager.lock_product_master(
            sku_code, operator=operator.get("user_id", "admin")
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/products/{sku_code}/unlock", response_model=ProductMaster, tags=["货品主数据"])
async def unlock_product(
    sku_code: str,
    reason: str = Query("", description="解锁原因"),
    operator: dict = Depends(get_current_session),
):
    """解锁货品（管理员操作）。"""
    _ensure_init()
    try:
        return SupplyChainManager.unlock_product_master(
            sku_code, operator=operator.get("user_id", "admin"), reason=reason
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.delete("/products/{sku_code}", tags=["货品主数据"])
async def delete_product(sku_code: str, operator: dict = Depends(get_current_session)):
    """删除货品（仅 draft 状态可删除）。"""
    _ensure_init()
    try:
        SupplyChainManager.delete_product_master(
            sku_code, operator=operator.get("user_id", "admin")
        )
        return {"ok": True, "message": f"货品 {sku_code} 已删除"}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))


@router.post("/products/init", tags=["货品主数据"])
async def init_seed_data(operator: dict = Depends(get_current_session)):
    """
    初始化种子数据（展会演示用）。

    加载 20+ 火锅常用冻品 SKU，覆盖全品类。
    幂等操作：已有数据时不重复加载。
    """
    global _initialized
    _initialized = False  # 强制重新初始化
    _ensure_init()
    count = SupplyChainManager.load_seed_data()
    return {
        "ok": True,
        "message": f"种子数据加载完成",
        "count": count,
    }


# ============================================================
# 变更管理端点
# ============================================================

@router.post("/products/{sku_code}/change", response_model=ChangeRequest, tags=["货品变更"])
async def submit_change(
    sku_code: str, change: ChangeRequest, operator: dict = Depends(get_current_session)
):
    """提交变更申请单。"""
    _ensure_init()
    try:
        return SupplyChainManager.submit_change_request(
            sku_code, change, operator=operator.get("user_id", "admin")
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("提交变更申请失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/products/changes", response_model=List[ChangeRequest], tags=["货品变更"])
async def list_changes(
    sku_code: Optional[str] = Query(None, description="按SKU筛选"),
    status: Optional[str] = Query(None, description="按状态筛选(pending/approved/rejected)"),
    _: dict = Depends(get_current_session),
):
    """查询变更申请列表。"""
    _ensure_init()
    return SupplyChainManager.list_change_requests(
        sku_code=sku_code or "", status=status or ""
    )


@router.post("/products/changes/{request_id}/approve", tags=["货品变更"])
async def approve_change(
    request_id: str,
    approved: bool = Query(..., description="是否通过"),
    notes: str = Query("", description="审批意见"),
    operator: dict = Depends(get_current_session),
):
    """审批变更申请。"""
    _ensure_init()
    result = SupplyChainManager.approve_change_request(
        request_id, approved=approved,
        approver=operator.get("user_id", "admin"),
        notes=notes,
    )
    if not result:
        raise HTTPException(status_code=404, detail=f"变更申请不存在或已处理: {request_id}")
    return {
        "ok": True,
        "message": f"变更{'通过' if approved else '驳回'}成功",
        "request_id": request_id,
        "new_version": result.effective_version,
    }
