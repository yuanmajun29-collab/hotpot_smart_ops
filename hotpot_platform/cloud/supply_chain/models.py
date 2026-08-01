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


# ============================================================
# S01 — 货品主数据管理 (D1 新增)
# ============================================================

class ProductCategory(BaseModel):
    """货品分类"""
    category_code: str  # e.g. "FROZEN_MEAT", "HOTPOT_BASE", "VEGETABLE"
    category_name: str  # e.g. "冻品荤菜", "锅底", "素菜"
    parent_code: Optional[str] = None  # 父分类(支持二级)
    sort_order: int = 0
    status: str = "active"  # active / inactive

    class Config:
        json_schema_extra = {
            "examples": [
                {"category_code": "FROZEN_MEAT", "category_name": "冻品荤菜", "sort_order": 1},
                {"category_code": "HOTPOT_BASE", "category_name": "锅底/汤底", "sort_order": 2},
                {"category_code": "VEGETABLE", "category_name": "素菜", "sort_order": 3},
                {"category_code": "STAPLE", "category_name": "主食/小吃", "sort_order": 4},
                {"category_code": "DRINK", "category_name": "酒水饮料", "sort_order": 5},
                {"category_code": "SEASONING", "category_name": "调料蘸料", "sort_order": 6},
            ]
        }


class ProductMaster(BaseModel):
    """
    货品主数据 (S01 核心)

    统一管理所有供货产品的名称、规格、品牌、价格，形成电子版下单标准。
    规格变更需提前反馈并走审批流，供应商断货换品牌必须提前告知。

    EARS: The system shall maintain a single source of truth for all product
    master data including name, specification, brand, and standard price.
    """
    # ── 基础信息 (关键字段, 锁定后不可改) ──
    sku_code: str = Field(..., description="SKU编码 (唯一标识)", min_length=2, max_length=30)
    name: str = Field(..., description="货品名称", min_length=1, max_length=50)
    specification: str = Field(..., description="规格型号 (如'500g/盒','2kg/件')", max_length=50)
    brand: str = Field(..., description="品牌 (如'海霸王','喜得佳')", max_length=30)
    unit_price: float = Field(..., description="标准采购价 (元)", ge=0)
    unit: str = Field(default="份", description="计量单位 (kg/份/盒/件)")
    category: str = Field(..., description="品类分类")

    # ── 供应商关联 ──
    supplier_id: Optional[str] = None  # 默认供应商ID
    supplier_name: Optional[str] = None  # 冗余存储供应商名称

    # ── 扩展信息 ──
    image_url: Optional[str] = None  # 产品图片(S02视觉比对用)
    location_code: Optional[str] = None  # 库位编码 (如"A-01-03")
    location_name: Optional[str] = None  # 库位名称
    storage_area: Optional[str] = None  # 存放区域 (冷冻/冷藏/常温)
    shelf_life_days: Optional[int] = Field(default=None, ge=1, description="保质期(天)")
    min_stock_qty: Optional[float] = Field(default=None, ge=0, description="安全库存量")
    tags: List[str] = []  # 标签 (如["热销","新品","季节限定"])

    # ── 状态控制 ──
    status: str = Field(default="draft", description="状态: draft/pending_approval/active/discontinued")
    locked: bool = Field(default=False, description="是否锁定 (锁定后关键字段不可修改)")
    version: int = Field(default=1, description="数据版本号 (变更时+1)")

    # ── 审计字段 ──
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    approval_status: str = Field(default="none", description="审批状态: none/pending/approved/rejected")
    approval_notes: Optional[str] = None

    class Config:
        json_schema_extra = {
            "example": {
                "sku_code": "FP-MW-001",
                "name": "精品毛肚",
                "specification": "500g/盒",
                "brand": "海霸王",
                "unit_price": 128.0,
                "unit": "盒",
                "category": "FROZEN_MEAT",
                "supplier_name": "杭州冻品供应链",
                "storage_area": "冷冻",
                "shelf_life_days": 180,
                "status": "active",
                "locked": True,
                "version": 1,
            }
        }


class ChangeRequest(BaseModel):
    """变更申请单"""
    request_id: Optional[str] = None
    sku_code: str
    change_type: str  # brand_replace / price_adjust / spec_modify / discontinue / reactivate
    old_value: Dict[str, Any] = {}  # 变更前值快照
    new_value: Dict[str, Any] = {}  # 申请新值
    reason: str = Field(..., description="变更原因")
    requested_by: str = ""  # 申请人
    requested_at: Optional[datetime] = None
    status: str = "pending"  # pending / approved / rejected / cancelled
    approved_by: Optional[str] = None  # 审批人 (潘厨/曹总)
    approved_at: Optional[datetime] = None
    approval_notes: Optional[str] = None
    effective_version: Optional[int] = None  # 生效后的版本号


class TemporarySubstitute(BaseModel):
    """临时替代品 (供应商断货应急)"""
    substitute_id: Optional[str] = None
    original_sku_code: str  # 原SKU
    substitute_sku_code: str  # 替代SKU
    substitute_brand: str  # 替代品牌
    reason: str = ""  # 替代原因 (如"原品牌断货")
    start_date: date
    end_date: date  # 替代到期日
    status: str = "active"  # active / expired / cancelled
    created_by: str = ""
    created_at: Optional[datetime] = None


# ============================================================
# API 请求/响应模型
# ============================================================

class ProductCreateRequest(BaseModel):
    """新建货品请求"""
    sku_code: str = Field(..., min_length=2, max_length=30)
    name: str = Field(..., min_length=1, max_length=50)
    specification: str = Field(..., max_length=50)
    brand: str = Field(..., max_length=30)
    unit_price: float = Field(..., ge=0)
    unit: str = "份"
    category: str
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    image_url: Optional[str] = None
    location_code: Optional[str] = None
    storage_area: Optional[str] = None
    shelf_life_days: Optional[int] = Field(default=None, ge=1)
    min_stock_qty: Optional[float] = Field(default=None, ge=0)
    tags: List[str] = []


class ProductUpdateRequest(BaseModel):
    """更新货品请求 (仅允许非锁定字段或全部字段如果未锁定)"""
    name: Optional[str] = Field(default=None, max_length=50)
    specification: Optional[str] = Field(default=None, max_length=50)
    brand: Optional[str] = Field(default=None, max_length=30)
    unit_price: Optional[float] = Field(default=None, ge=0)
    unit: Optional[str] = None
    category: Optional[str] = None
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    image_url: Optional[str] = None
    location_code: Optional[str] = None
    location_name: Optional[str] = None
    storage_area: Optional[str] = None
    shelf_life_days: Optional[int] = Field(default=None, ge=1)
    min_stock_qty: Optional[float] = Field(default=None, ge=0)
    tags: Optional[List[str]] = None
    status: Optional[str] = None  # 允许停用/重新激活


class ProductListResponse(BaseModel):
    """货品列表响应 (分页)"""
    total: int = 0
    page: int = 1
    page_size: int = 20
    items: List[ProductMaster] = []
    categories: List[ProductCategory] = []  # 可用的分类列表


class ProductStatsResponse(BaseModel):
    """货品统计概览"""
    total_products: int = 0
    active_products: int = 0
    locked_products: int = 0
    draft_products: int = 0
    total_categories: int = 0
    total_suppliers: int = 0
    avg_unit_price: float = 0
    category_breakdown: Dict[str, int] = {}  # {category_code: count}
