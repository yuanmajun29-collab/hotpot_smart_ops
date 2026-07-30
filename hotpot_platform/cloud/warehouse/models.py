"""
火瞳 · 仓库 IoT 管理层 — Pydantic 数据模型 (WH01-WH06)

对应详细架构 v1.1 §1.8，覆盖:
  WH01 RFID 批次追踪
  WH02 温湿度监控
  WH03 FEFO 先失效先出
  WH04 库存预警
  WH05 效期管理
  WH06 IoT 设备管理
"""

from pydantic import BaseModel, Field
from typing import Optional, Dict, List, Any
from datetime import date, datetime


# ============================================================
# WH01 — RFID 批次追踪
# ============================================================

class RFIDItem(BaseModel):
    """RFID 标签物品 — 批次追踪的最小单元"""
    epc: str = Field(..., description="电子产品码(唯一标识)")
    sku: str = Field(..., description="商品编码")
    batch_id: str = Field(..., description="所属批次号")
    quantity: float = Field(default=1.0, ge=0, description="数量")
    unit: str = Field(default="kg", description="单位: kg/件/箱")
    production_date: Optional[date] = None
    expiry_date: Optional[date] = None


class Discrepancy(BaseModel):
    """批次追踪差异明细"""
    epc: str
    sku: str
    expected_qty: float = 0
    actual_qty: float = 0
    reason: str = Field(default="unknown", description="missing / extra / wrong_location")


class TrackingResult(BaseModel):
    """批次流转记录结果 (RFIDTracker.track_batch 返回值)"""
    batch_id: str
    store_id: str
    operation: str  # receive / transfer / consume / waste / ship_out
    items_tracked: int = 0
    items_expected: int = 0
    match_rate: float = Field(default=1.0, ge=0, le=1)
    discrepancies: List[Discrepancy] = []
    ledger_entries_created: int = 0
    alerts_triggered: List[str] = []
    recorded_at: Optional[datetime] = None


class BatchTimelineEntry(BaseModel):
    """批次时间线单条记录"""
    timestamp: datetime
    operation: str
    operator: str
    location: str
    qty_change: float = 0
    photos: List[str] = []


class BatchTrace(BaseModel):
    """批次完整追溯链 (RFIDTracker.query_batch_trace 返回值)"""
    batch_id: str
    store_id: str
    sku: Optional[str] = None
    supplier_name: Optional[str] = None
    received_at: Optional[datetime] = None
    current_location: Optional[str] = None
    current_qty: float = 0
    timeline: List[BatchTimelineEntry] = []
    remaining_shelf_life_days: int = 0
    fefo_status: str = "normal"  # normal / warning / expired


class ItemLocation(BaseModel):
    """单品位置 (RFIDTracker.locate_item 返回值)"""
    epc: str
    sku: str
    batch_id: str
    location: str
    last_seen_at: Optional[datetime] = None
    qty: float = 1.0


# ============================================================
# WH03 — FEFO 先失效先出 + WH05 效期管理
# ============================================================

class FEFORecommendation(BaseModel):
    """FEFO 出库建议单项"""
    sku: str
    batch_id: str
    expiry_date: Optional[date] = None
    days_remaining: int = 0
    on_hand_qty: float = 0
    action: str = Field(default="consume_first", description="consume_first / discard / discount_sale")
    priority: int = Field(default=99, ge=1, description="1=最紧急")


class FEVOStatus(BaseModel):
    """FEFO 检查状态 (FEFOMonitor.check_fevo 返回值)"""
    store_id: str
    checked_at: Optional[datetime] = None
    items_checked: int = 0
    items_normal: int = 0      # 效期充足(>7天)
    items_warning: int = 0     # 即将过期(1~7天)
    items_expired: int = 0     # 已过期
    recommendations: List[FEFORecommendation] = []
    overall_score: float = Field(default=100.0, ge=0, le=100, description="FEFO健康分")


class Allocation(BaseModel):
    """FEFO 拣货分配明细"""
    batch_id: str
    qty: float = 0
    expiry_date: Optional[date] = None
    location: Optional[str] = None


class PickAllocation(BaseModel):
    """FEFO 拣货单项分配"""
    sku: str
    required_qty: float = 0
    allocations: List[Allocation] = []


class PickList(BaseModel):
    """FEFO 拣货清单 (FEFOMonitor.generate_pick_list 返回值)"""
    store_id: str
    generated_at: Optional[datetime] = None
    picks: List[PickAllocation] = []
    warnings: List[str] = []


class OrderItem(BaseModel):
    """订货单项（用于生成拣货清单的输入）"""
    sku: str
    required_qty: float = 0
    unit: str = "kg"


# ============================================================
# WH02 / WH06 — IoT 温湿度监控 + 设备管理
# ============================================================

class IoTReading(BaseModel):
    """IoT 遥测数据单条"""
    device_id: str
    sensor_type: str = Field(default="temperature", description="temperature / humidity / combined")
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None
    battery_pct: Optional[float] = Field(default=None, ge=0, le=100)
    signal_rssi: Optional[int] = Field(default=None, ge=-128, le=0)
    reading_at: datetime
    raw_payload: Optional[Dict[str, Any]] = None


class IngestResult(BaseModel):
    """遥测数据写入结果 (IoTMonitor.ingest_telemetry 返回值)"""
    readings_received: int = 0
    readings_stored: int = 0
    alerts_triggered: int = 0
    errors: List[str] = []


class DeviceThresholdConfig(BaseModel):
    """设备阈值配置"""
    device_id: str
    temp_min_c: float = 0
    temp_max_c: float = 40
    humidity_min_pct: Optional[float] = None
    humidity_max_pct: Optional[float] = None
    alarm_duration_sec: int = 900  # 默认15分钟持续超限告警
    configured_by: str = ""
    configured_at: Optional[datetime] = None


class DeviceStatus(BaseModel):
    """设备状态 (IoTMonitor.get_device_status 返回值)"""
    device_id: str
    device_type: str  # temperature_sensor / humidity_sensor / rfid_gateway / combined
    location: str
    last_reading_at: Optional[datetime] = None
    current_temp_c: Optional[float] = None
    current_humidity_pct: Optional[float] = None
    battery_pct: Optional[float] = None
    signal_rssi: Optional[int] = None
    status: str = "offline"  # online / offline / alarm / maintenance
    threshold_config: Optional[DeviceThresholdConfig] = None


class TemperaturePoint(BaseModel):
    """温湿度时间线数据点"""
    timestamp: datetime
    temperature_c: Optional[float] = None
    humidity_pct: Optional[float] = None


class TemperatureTimeline(BaseModel):
    """温湿度时间线 (IoTMonitor.get_temperature_timeline 返回值)"""
    device_id: str
    store_id: str
    start: datetime
    end: datetime
    interval_minutes: int = 5
    points: List[TemperaturePoint] = []
    violations_count: int = 0  # 超限次数


# ============================================================
# WH04 — 库存预警
# ============================================================

class StockAlertItem(BaseModel):
    """单品库存预警"""
    sku: str
    sku_name: Optional[str] = None
    category: Optional[str] = None
    current_qty: float = 0
    unit: str = "kg"
    safety_stock_level: float = 0
    days_of_stock: float = 0       # 可销售天数
    daily_avg_consumption: float = 0
    alert_type: str = Field(default="stockout", description="stockout / overstock / slow_moving / expiring")
    urgency: str = Field(default="low", description="critical / high / medium / low")
    suggested_order_qty: float = 0
    estimated_stockout_date: Optional[date] = None


class StockAlertSummary(BaseModel):
    """库存预警汇总"""
    critical_count: int = 0
    high_count: int = 0
    medium_count: int = 0
    total_at_risk_sku: int = 0


class StockAlertReport(BaseModel):
    """库存水位检查报告 (InventoryAlertor.check_stock_levels 返回值)"""
    store_id: str
    checked_at: Optional[datetime] = None
    alerts: List[StockAlertItem] = []
    summary: StockAlertSummary = StockAlertSummary()


class AlertRule(BaseModel):
    """单品级预警规则配置"""
    rule_id: Optional[str] = None
    sku: str
    store_id: str
    rule_type: str  # stockout / overstock / expiring
    threshold_value: float = 0
    unit: str = "days"  # days / qty / pct
    enabled: bool = True
    created_by: Optional[str] = None
    created_at: Optional[datetime] = None
