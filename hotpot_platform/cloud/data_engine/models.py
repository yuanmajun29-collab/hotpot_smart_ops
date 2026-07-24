"""
火瞳 · 数据引擎 — Pydantic 数据模型 (N01-N06)

复用现有架构模式: 所有模型继承 BaseModel, 支持 JSON 序列化。
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List
from datetime import date, datetime


# ============================================================
# N01 — 销量预测
# ============================================================

class SalesRecord(BaseModel):
    """per-SKU 日销量记录"""
    store_id: str
    business_date: date
    sku: str
    sku_name: Optional[str] = None
    category: Optional[str] = None
    qty_sold: float = Field(ge=0)
    unit: str = "份"
    unit_price: Optional[float] = None
    revenue: Optional[float] = None
    hour_dist: Optional[Dict[str, int]] = None  # {hour: qty}
    source: str = "pos"


class SalesForecast(BaseModel):
    """销量预测结果"""
    store_id: str
    sku: str
    forecast_date: date
    predicted_qty: float
    confidence: float = Field(ge=0, le=1)
    lower_bound: Optional[float] = None
    upper_bound: Optional[float] = None
    model_version: str = "L1-rule"
    features_used: Optional[Dict] = None


# ============================================================
# N02 — 订货建议
# ============================================================

class OrderSuggestion(BaseModel):
    """订货建议"""
    store_id: str
    sku: str
    suggested_qty: float
    unit: str = "kg"
    current_stock: float = 0
    safety_stock: float = 0
    forecast_demand: float = 0
    lead_time_days: int = 1
    supplier: Optional[str] = None
    urgency: str = "normal"  # urgent / normal / low
    reason: Optional[str] = None
    status: str = "pending"  # pending / approved / rejected / ordered


# ============================================================
# N03 — 库存
# ============================================================

class InventoryMovement(BaseModel):
    """库存变动流水"""
    store_id: str
    sku: str
    batch_id: Optional[str] = None
    movement_type: str  # stock_in / stock_out / adjust / waste / transfer
    qty_change: float   # 正=入库, 负=出库
    unit: str = "kg"
    unit_cost: Optional[float] = None
    reason: Optional[str] = None
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None
    operator: Optional[str] = None
    recorded_at: Optional[datetime] = None


class InventorySnapshot(BaseModel):
    """库存快照"""
    store_id: str
    sku: str
    on_hand_qty: float
    in_transit_qty: float = 0
    unit: str = "kg"
    avg_daily_consumption: Optional[float] = None
    shelf_life_days: Optional[int] = None
    earliest_expiry: Optional[str] = None


# ============================================================
# N04 — 损耗分析
# ============================================================

class LossAnalysis(BaseModel):
    """per-SKU 损耗分析"""
    store_id: str
    sku: str
    date: date
    loss_rate_pct: float  # 损耗率 %
    loss_amount: float     # 损耗金额
    root_cause: Optional[str] = None
    suggestion: Optional[str] = None


class LossTrend(BaseModel):
    """损耗趋势"""
    store_id: str
    sku: str
    days: int = 30
    daily_rates: List[Dict] = []  # [{date, rate, amount}]


# ============================================================
# N05 — 供应商
# ============================================================

class SupplierScorecard(BaseModel):
    """供应商评分卡"""
    store_id: Optional[str] = None
    supplier_name: str
    sku: Optional[str] = None
    total_batches: int = 0
    avg_variance_pct: Optional[float] = None    # 平均短重率
    avg_yield_rate: Optional[float] = None      # 平均出成率
    quality_grade_dist: Optional[Dict[str, int]] = None  # {A:80, B:15, C:5}
    avg_price: Optional[float] = None
    price_stability: Optional[float] = None     # 价格波动率
    on_time_rate: Optional[float] = None        # 准时交货率
    reject_rate: Optional[float] = None         # 拒收率
    total_score: Optional[float] = None         # 综合评分 0-100
    score_level: Optional[str] = None           # A/B/C/D


# ============================================================
# N06 — ERP
# ============================================================

class ErpSyncResult(BaseModel):
    """ERP 同步结果"""
    store_id: str
    synced_at: datetime
    records_pulled: int = 0
    records_pushed: int = 0
    errors: List[str] = []
    status: str = "ok"  # ok / partial / failed
