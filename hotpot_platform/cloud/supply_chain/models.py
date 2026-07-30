"""
火瞳 · 冻品供应链 — Pydantic 数据模型 (S01-S04)

对应 PRD:
  S01: 供应商管理
  S02: 收货质检 (VLM)
  S03: 采购订单管理
  S04: 供应商协同

关键角色（来自门店标准）:
  潘总(潘厨): 品质管控 → 质检审批
  王总(供应商): 只对接潘厨 → 供货+对账
  曹总: 统一下单标准 → 采购规则制定
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from datetime import date, datetime


# ============================================================
# S01 — 供应商管理
# ============================================================

class SupplierInfo(BaseModel):
    """供应商基本信息"""
    supplier_id: Optional[str] = None
    name: str = Field(..., description="供应商名称，如'杭州冻品供应链'")
    contact_person: str = ""
    phone: str = ""
    address: str = ""
    license_no: Optional[str] = None  # 食品经营许可证号
    status: str = "active"  # active / suspended / blacklisted
    supplied_skus: List[str] = []  # 供应的SKU列表
    created_at: Optional[datetime] = None


class SupplierCollabData(BaseModel):
    """供应商协同数据 (S04)"""
    supplier_id: str
    store_id: str
    period_start: date
    period_end: date
    total_orders: int = 0
    total_amount: float = 0
    on_time_deliveries: int = 0
    quality_issues: int = 0
    return_items: int = 0
    avg_lead_time_hours: float = 0
    notes: Optional[str] = None


# ============================================================
# S02 — 收货质检
# ============================================================

class ReceivingItem(BaseModel):
    """收货单品"""
    sku: str
    sku_name: Optional[str] = None
    ordered_qty: float = 0
    received_qty: float = 0
    unit: str = "kg"
    batch_id: Optional[str] = None
    production_date: Optional[date] = None
    expiry_date: Optional[date] = None
    temperature_on_arrival: Optional[float] = None  # 到货温度(冻品必填)


class QualityCheckResult(BaseModel):
    """质检结果单项"""
    sku: str
    passed: bool = True
    grade: str = "A"  # A / B / C / D (拒收)
    weight_variance_pct: Optional[float] = None  # 短重率 (%)
    yield_rate: Optional[float] = None  # 出成率 (%)
    temperature_ok: bool = True
    visual_defects: List[str] = []  # 外观缺陷描述
    vlm_analysis: Optional[Dict[str, Any]] = None  # VLM 视觉分析结果
    inspector: Optional[str] = None  # 潘厨/品质管控
    inspected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None


class ReceivingRecord(BaseModel):
    """收货记录 (S02)"""
    record_id: Optional[str] = None
    store_id: str
    supplier_name: str
    po_number: Optional[str] = None  # 关联采购单号
    received_at: Optional[datetime] = None
    receiver: str = ""  # 收货人
    items: List[ReceivingItem] = []
    quality_results: List[QualityCheckResult] = []
    photos: List[str] = []
    total_passed: bool = True
    status: str = "pending"  # pending / inspecting / approved / rejected
    notes: Optional[str] = None


# ============================================================
# S03 — 采购订单管理
# ============================================================

class PurchaseOrderItem(BaseModel):
    """采购订单行项"""
    sku: str
    sku_name: Optional[str] = None
    quantity: float = 0
    unit: str = "kg"
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    supplier: Optional[str] = None  # 指定供应商
    delivery_date: Optional[date] = None
    notes: Optional[str] = None


class PurchaseOrder(BaseModel):
    """采购订单 (S03)"""
    po_number: Optional[str] = None
    store_id: str
    ordered_by: str = ""  # 下单人(曹总/店长)
    ordered_at: Optional[datetime] = None
    items: List[PurchaseOrderItem] = []
    total_amount: float = 0
    status: str = "draft"  # draft / submitted / confirmed / partial / received / cancelled
    supplier: Optional[str] = None  # 默认供应商
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    # 关联字段
    forecast_ref: Optional[str] = None  # 关联的销量预测建议ID
    auto_generated: bool = False  # 是否由系统自动生成


# ============================================================
# S04 — 供应商协同
# ============================================================

class SupplierScoreUpdate(BaseModel):
    """供应商评分更新（协同后自动计算）"""
    supplier_name: str
    store_id: str
    period: str  # e.g. "2026-07"
    on_time_rate: Optional[float] = None
    reject_rate: Optional[float] = None
    avg_variance_pct: Optional[float] = None
    score_adjustment: float = 0  # 人工调整分
    adjusted_by: Optional[str] = None  # 潘厨
    comments: Optional[str] = None
