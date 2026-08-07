"""供应链既有业务模型的兼容层。

W2 收货/审批流程使用 ``models.py`` 中的 dataclass；早期 S01--S04
管理器仍依赖 Pydantic 的订单、货品和供应商模型。两套模型的
``ReceivingRecord``、``PurchaseOrder`` 等名称相同但字段不同，不能再从
同一模块隐式导入。该模块保留旧管理器的明确依赖，避免破坏 W2 公共模型。
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SupplierInfo(BaseModel):
    supplier_id: Optional[str] = None
    name: str
    contact_person: str = ""
    phone: str = ""
    address: str = ""
    license_no: Optional[str] = None
    status: str = "active"
    supplied_skus: List[str] = Field(default_factory=list)
    created_at: Optional[datetime] = None


class SupplierCollabData(BaseModel):
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


class ReceivingItem(BaseModel):
    sku: str
    sku_name: Optional[str] = None
    ordered_qty: float = 0
    received_qty: float = 0
    unit: str = "kg"
    batch_id: Optional[str] = None
    production_date: Optional[date] = None
    expiry_date: Optional[date] = None
    temperature_on_arrival: Optional[float] = None


class QualityCheckResult(BaseModel):
    sku: str
    passed: bool = True
    grade: str = "A"
    weight_variance_pct: Optional[float] = None
    yield_rate: Optional[float] = None
    temperature_ok: bool = True
    visual_defects: List[str] = Field(default_factory=list)
    vlm_analysis: Optional[Dict[str, Any]] = None
    inspector: Optional[str] = None
    inspected_at: Optional[datetime] = None
    rejection_reason: Optional[str] = None


class ReceivingRecord(BaseModel):
    record_id: Optional[str] = None
    store_id: str
    supplier_name: str
    po_number: Optional[str] = None
    received_at: Optional[datetime] = None
    receiver: str = ""
    items: List[ReceivingItem] = Field(default_factory=list)
    quality_results: List[QualityCheckResult] = Field(default_factory=list)
    photos: List[str] = Field(default_factory=list)
    total_passed: bool = True
    status: str = "pending"
    notes: Optional[str] = None


class PurchaseOrderItem(BaseModel):
    sku: str
    sku_name: Optional[str] = None
    quantity: float = 0
    unit: str = "kg"
    unit_price: Optional[float] = None
    amount: Optional[float] = None
    supplier: Optional[str] = None
    delivery_date: Optional[date] = None
    notes: Optional[str] = None


class PurchaseOrder(BaseModel):
    po_number: Optional[str] = None
    store_id: str
    ordered_by: str = ""
    ordered_at: Optional[datetime] = None
    items: List[PurchaseOrderItem] = Field(default_factory=list)
    total_amount: float = 0
    status: str = "draft"
    supplier: Optional[str] = None
    delivery_address: Optional[str] = None
    notes: Optional[str] = None
    forecast_ref: Optional[str] = None
    auto_generated: bool = False


class SupplierScoreUpdate(BaseModel):
    supplier_name: str
    store_id: str
    period: str
    on_time_rate: Optional[float] = None
    reject_rate: Optional[float] = None
    avg_variance_pct: Optional[float] = None
    score_adjustment: float = 0
    adjusted_by: Optional[str] = None
    comments: Optional[str] = None


class ProductCategory(BaseModel):
    category_code: str
    category_name: str
    parent_code: Optional[str] = None
    sort_order: int = 0
    status: str = "active"


class ProductMaster(BaseModel):
    sku_code: str
    name: str
    specification: str
    brand: str
    unit_price: float
    unit: str = "份"
    category: str
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    image_url: Optional[str] = None
    location_code: Optional[str] = None
    location_name: Optional[str] = None
    storage_area: Optional[str] = None
    shelf_life_days: Optional[int] = None
    min_stock_qty: Optional[float] = None
    tags: List[str] = Field(default_factory=list)
    status: str = "draft"
    locked: bool = False
    version: int = 1
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_by: Optional[str] = None
    updated_at: Optional[datetime] = None
    approval_status: str = "none"
    approval_notes: Optional[str] = None


class ChangeRequest(BaseModel):
    request_id: Optional[str] = None
    sku_code: str
    change_type: str
    old_value: Dict[str, Any] = Field(default_factory=dict)
    new_value: Dict[str, Any] = Field(default_factory=dict)
    reason: str
    requested_by: str = ""
    requested_at: Optional[datetime] = None
    status: str = "pending"
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    approval_notes: Optional[str] = None
    effective_version: Optional[int] = None


class TemporarySubstitute(BaseModel):
    substitute_id: Optional[str] = None
    original_sku_code: str
    substitute_sku_code: str
    substitute_brand: str
    reason: str = ""
    start_date: date
    end_date: date
    status: str = "active"
    created_by: str = ""
    created_at: Optional[datetime] = None


class ProductCreateRequest(BaseModel):
    sku_code: str
    name: str
    specification: str
    brand: str
    unit_price: float
    unit: str = "份"
    category: str
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    image_url: Optional[str] = None
    location_code: Optional[str] = None
    storage_area: Optional[str] = None
    shelf_life_days: Optional[int] = None
    min_stock_qty: Optional[float] = None
    tags: List[str] = Field(default_factory=list)


class ProductUpdateRequest(BaseModel):
    name: Optional[str] = None
    specification: Optional[str] = None
    brand: Optional[str] = None
    unit_price: Optional[float] = None
    unit: Optional[str] = None
    category: Optional[str] = None
    supplier_id: Optional[str] = None
    supplier_name: Optional[str] = None
    image_url: Optional[str] = None
    location_code: Optional[str] = None
    location_name: Optional[str] = None
    storage_area: Optional[str] = None
    shelf_life_days: Optional[int] = None
    min_stock_qty: Optional[float] = None
    tags: Optional[List[str]] = None
    status: Optional[str] = None


class ProductListResponse(BaseModel):
    total: int = 0
    page: int = 1
    page_size: int = 20
    items: List[ProductMaster] = Field(default_factory=list)
    categories: List[ProductCategory] = Field(default_factory=list)


class ProductStatsResponse(BaseModel):
    total_products: int = 0
    active_products: int = 0
    locked_products: int = 0
    draft_products: int = 0
    total_categories: int = 0
    total_suppliers: int = 0
    avg_unit_price: float = 0
    category_breakdown: Dict[str, int] = Field(default_factory=dict)
