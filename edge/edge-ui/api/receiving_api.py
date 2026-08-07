"""
火瞳 · Edge UI — 收货质检 API (S02)

对应 PRD D1-S02: 冻品供应链 — 收货质检 (VLM + 潘厨审批)

端点:
  POST   /api/receiving/records              新建收货记录
  GET    /api/receiving/records              收货记录列表 (分页)
  GET    /api/receiving/records/{record_id}  收货详情
  PUT    /api/receiving/records/{record_id}  更新收货记录 (仅draft)
  POST   /api/receiving/records/{record_id}/submit     提交质检
  POST   /api/receiving/records/{record_id}/photos     上传照片
  POST   /api/receiving/records/{record_id}/inspect    触发VLM质检
  GET    /api/receiving/records/{record_id}/quality    获取质检结果
  POST   /api/receiving/records/{record_id}/approve    潘厨审批通过
  POST   /api/receiving/records/{record_id}/reject     潘厨拒收
  POST   /api/receiving/records/{record_id}/partial    部分通过
  POST   /api/receiving/records/{record_id}/return     退回修改
  GET    /api/receiving/stats                 收货统计概览
  GET    /api/receiving/suppliers/{name}/history  供应商收货历史
  POST   /api/receiving/seed-demo             加载Demo数据

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
from hotpot_platform.cloud.supply_chain.legacy_models import (
    ReceivingRecord,
    ReceivingItem,
    QualityCheckResult,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# ── 数据存储路径 (与S01共享同一数据文件) ──
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
        logger.info("收货质检模块已初始化: %s", PRODUCT_DATA_FILE)


# ============================================================
# 请求/响应模型
# ============================================================

class CreateReceivingRequest(BaseModel):
    """新建收货记录请求"""
    supplier_name: str = Field(..., description="供应商名称")
    po_number: Optional[str] = Field(None, description="采购单号")
    receiver: str = Field(..., description="收货人")
    items: List[Dict[str, Any]] = Field(
        ...,
        min_length=1,
        description="收货品项列表",
        example=[{
            "sku": "FP-MW-001",
            "ordered_qty": 10.0,
            "received_qty": 9.8,
            "unit": "kg",
            "batch_id": "20260801-HDW",
            "temperature_on_arrival": -15.5,
        }]
    )
    notes: Optional[str] = Field(None, description="备注")


class UpdateReceivingRequest(BaseModel):
    """更新收货记录请求 (仅draft状态)"""
    supplier_name: Optional[str] = None
    receiver: Optional[str] = None
    po_number: Optional[str] = None
    notes: Optional[str] = None
    items: Optional[List[Dict[str, Any]]] = None


class ApproveRequest(BaseModel):
    """审批请求"""
    notes: Optional[str] = Field(None, description="审批意见")


class RejectRequest(BaseModel):
    """拒收请求"""
    reason: str = Field(..., description="拒收原因(必填)")


class PhotoUploadRequest(BaseModel):
    """照片上传请求"""
    photo_url: str = Field(..., description="照片URL或路径")
    photo_type: str = Field("overview", description="照片类型: overview/item_detail/weight_scale/defect/package_label")


class InspectRequest(BaseModel):
    """触发VLM质检请求"""
    use_vlm: bool = Field(True, description="是否使用VLM(True时若VLM未部署则自动用Mock)")


# ============================================================
# 端点实现
# ============================================================

@router.post("/receiving/records", tags=["收货质检"])
async def create_receiving_record(
    req: CreateReceivingRequest,
    _: dict = Depends(get_current_session),
):
    """
    新建收货记录。

    业务规则:
      - BR-01: SKU必须在ProductMaster中存在且为active
      - BR-03: 实收量必须>0
      - BR-04: 自动计算短重率
      - BR-05: 短重>15%自动标记为需关注
    """
    _ensure_init()
    try:
        result = SupplyChainManager.create_receiving_record(
            supplier_name=req.supplier_name,
            receiver=req.receiver,
            items=req.items,
            po_number=req.po_number,
            notes=req.notes,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("创建收货记录失败: %s", e)
        raise HTTPException(status_code=500, detail=f"内部错误: {str(e)}")


@router.get("/receiving/records", tags=["收货质检"])
async def list_receiving_records(
    page: int = Query(1, ge=1, description="页码"),
    page_size: int = Query(20, ge=1, le=100, description="每页数量"),
    status: str = Query("", description="状态筛选(draft/pending/inspecting/pending_approval/approved/partial/rejected)"),
    supplier_name: str = Query("", description="供应商名称筛选"),
    _: dict = Depends(get_current_session),
):
    """获取收货记录列表（分页+筛选）。"""
    _ensure_init()
    try:
        result = SupplyChainManager.get_receiving_list(
            page=page,
            page_size=page_size,
            status=status or None,
            supplier_name=supplier_name or None,
        )
        return {"success": True, "data": result}
    except Exception as e:
        logger.error("获取收货列表失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/receiving/records/{record_id}", tags=["收货质检"])
async def get_receiving_detail(
    record_id: str,
    _: dict = Depends(get_current_session),
):
    """获取收货记录详情。"""
    _ensure_init()
    try:
        result = SupplyChainManager.get_receiving_detail(record_id)
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("获取收货详情失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/receiving/records/{record_id}", tags=["收货质检"])
async def update_receiving_record(
    record_id: str,
    req: UpdateReceivingRequest,
    _: dict = Depends(get_current_session),
):
    """更新收货记录（仅draft状态可编辑）。"""
    _ensure_init()
    try:
        update_data = req.model_dump(exclude_none=True)
        result = SupplyChainManager.update_receiving_record(record_id, update_data)
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("更新收货记录失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/receiving/records/{record_id}/submit", tags=["收货质检"])
async def submit_for_inspection(
    record_id: str,
    _: dict = Depends(get_current_session),
):
    """
    提交收货单进入质检流程。

    状态流转: draft → pending → inspecting (如有照片)
    """
    _ensure_init()
    try:
        result = SupplyChainManager.submit_for_inspection(record_id)
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("提交质检失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/receiving/records/{record_id}/photos", tags=["收货质检"])
async def upload_photo(
    record_id: str,
    req: PhotoUploadRequest,
    _: dict = Depends(get_current_session),
):
    """添加收货照片。"""
    _ensure_init()
    try:
        result = SupplyChainManager.add_photo(
            record_id,
            photo_url=req.photo_url,
            photo_type=req.photo_type,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("添加照片失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/receiving/records/{record_id}/inspect", tags=["收货质检"])
async def run_vlm_inspection(
    record_id: str,
    req: InspectRequest = InspectRequest(),
    _: dict = Depends(get_current_session),
):
    """
    执行VLM视觉质检。

    当VLM Bridge未部署时，自动使用Mock模式基于规则生成质检结果。
    Mock模式模拟以下规则:
      - 短重>15% 或 温度>-8°C → D级(拒收)
      - 短重7-15% 或 温度>-12°C → C级
      - 短重3-7% → B级
      - 其他 → A级
    """
    _ensure_init()
    # VLM 可用性由环境变量 HOTPOT_VLM_DISABLED=1 控制
    import os as _os
    use_mock = _os.environ.get("HOTPOT_VLM_DISABLED") == "1"
    try:
        result = SupplyChainManager.run_vlm_inspection(
            record_id,
            use_mock=use_mock,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("VLM质检失败: %s", e)
        raise HTTPException(status_code=500, detail=f"质检执行失败: {str(e)}")


@router.get("/receiving/records/{record_id}/quality", tags=["收货质检"])
async def get_quality_results(
    record_id: str,
    _: dict = Depends(get_current_session),
):
    """获取质检结果。"""
    _ensure_init()
    try:
        detail = SupplyChainManager.get_receiving_detail(record_id)
        return {
            "success": True,
            "data": {
                "record_id": record_id,
                "total_passed": detail.get("total_passed"),
                "quality_results": [qr.model_dump() if hasattr(qr, 'model_dump') else qr for qr in detail.get("quality_results", [])],
            }
        }
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("获取质检结果失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/receiving/records/{record_id}/approve", tags=["收货质检"])
async def approve_receiving(
    record_id: str,
    req: ApproveRequest = ApproveRequest(),
    session: dict = Depends(get_current_session),
):
    """
    潘厨审批：全部通过。

    BR-07: 存在D级品项时不允许全部通过。
    """
    _ensure_init()
    try:
        operator = session.get("user_id", "unknown")
        result = SupplyChainManager.approve_receiving(
            record_id,
            approver=operator,
            notes=req.notes,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("审批通过失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/receiving/records/{record_id}/reject", tags=["收货质检"])
async def reject_receiving(
    record_id: str,
    req: RejectRequest,
    session: dict = Depends(get_current_session),
):
    """
    潘厨审批：整批拒收。

    必须提供拒收原因。
    """
    _ensure_init()
    try:
        operator = session.get("user_id", "unknown")
        result = SupplyChainManager.reject_receiving(
            record_id,
            approver=operator,
            reason=req.reason,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("拒收失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/receiving/records/{record_id}/partial", tags=["收货质检"])
async def partial_approve(
    record_id: str,
    req: ApproveRequest = ApproveRequest(),
    session: dict = Depends(get_current_session),
):
    """潘厨审批：部分通过（部分品项有问题但可接收）。"""
    _ensure_init()
    try:
        operator = session.get("user_id", "unknown")
        result = SupplyChainManager.partial_approve(
            record_id,
            approver=operator,
            notes=req.notes,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("部分通过失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/receiving/records/{record_id}/return", tags=["收货质检"])
async def return_for_revision(
    record_id: str,
    req: RejectRequest,
    session: dict = Depends(get_current_session),
):
    """潘厨退回修改（信息不全时使用）。"""
    _ensure_init()
    try:
        operator = session.get("user_id", "unknown")
        result = SupplyChainManager.return_for_revision(
            record_id,
            approver=operator,
            reason=req.reason,
        )
        return {"success": True, "data": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("退回修改失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/receiving/stats", tags=["收货质检"])
async def get_receiving_stats(_: dict = Depends(get_current_session)):
    """
    获取收货统计概览。

    返回今日统计、本周统计、Top供应商排行、告警信息。
    """
    _ensure_init()
    try:
        result = SupplyChainManager.get_receiving_stats()
        return {"success": True, "data": result}
    except Exception as e:
        logger.error("获取收货统计失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/receiving/suppliers/{supplier_name}/history", tags=["收货质检"])
async def get_supplier_history(
    supplier_name: str,
    limit: int = Query(20, ge=1, le=100, description="返回条数"),
    _: dict = Depends(get_current_session),
):
    """
    获取供应商收货历史。

    用于N07供应商画像: 聚合品质趋势、短重率、通过率等。
    """
    _ensure_init()
    try:
        result = SupplyChainManager.get_supplier_receiving_history(supplier_name, limit)
        return {"success": True, "data": result}
    except Exception as e:
        logger.error("获取供应商历史失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/receiving/seed-demo", tags=["收货质检"])
async def seed_demo_data(_: dict = Depends(get_current_session)):
    """
    加载展会Demo用的收货种子数据。

    包含3种典型场景:
      - RC-DEMO-001: 正常收货(A级通过) — 杭州冻品供应链
      - RC-DEMO-002: 部分通过(C级) — 张记肉业
      - RC-DEMO-003: 整批拒收(D级) — 李记海鲜
    """
    _ensure_init()
    try:
        count = SupplyChainManager.seed_demo_receiving_data()
        return {
            "success": True,
            "message": f"已加载 {count} 条Demo收货数据",
            "data": {"loaded_count": count},
        }
    except Exception as e:
        logger.error("加载Demo数据失败: %s", e)
        raise HTTPException(status_code=500, detail=str(e))
