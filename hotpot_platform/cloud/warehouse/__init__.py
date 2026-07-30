"""
火瞳 · 仓库 IoT 管理层 — 统一入口 (hotpot_platform.cloud.warehouse)

对应详细架构 v1.1 §1.8，覆盖 PRD WH01-WH06 六大功能:

  WH01 RFID 批次追踪     → rfid_tracker.RFIDTracker
  WH02 温湿度监控         → iot_monitor.IoTMonitor
  WH03 FEFO 先失效先出    → fefo_monitor.FEFOMonitor
  WH04 库存预警           → inventory_alertor.InventoryAlertor
  WH05 效期管理           → fefo_monitor.FEFOMonitor (内含)
  WH06 IoT 设备管理       → iot_monitor.IoTMonitor (内含)

数据流:
  Edge IoT (MQTT) → Platform Ingest → Rule Engine → Alert / API

依赖:
  - event_hub: EventHubClient (事件上报)
  - data_engine: InventoryService (库存服务)
  - alert_gateway: AlertGateway (告警推送)
"""

# ---- 数据模型 ----
from hotpot_platform.cloud.warehouse.models import (  # noqa: F401
    # WH01 RFID
    RFIDItem, TrackingResult, Discrepancy,
    BatchTrace, BatchTimelineEntry, ItemLocation,
    # WH03/05 FEFO
    FEFORecommendation, FEVOStatus, PickList, PickAllocation, Allocation, OrderItem,
    # WH02/06 IoT
    IoTReading, IngestResult, DeviceThresholdConfig, DeviceStatus,
    TemperatureTimeline, TemperaturePoint,
    # WH04 库存预警
    StockAlertItem, StockAlertSummary, StockAlertReport, AlertRule,
)

# ---- WH01 RFID 批次追踪 ----
from hotpot_platform.cloud.warehouse.rfid_tracker import RFIDTracker  # noqa: F401

# ---- WH03/05 FEFO 监控 ----
from hotpot_platform.cloud.warehouse.fefo_monitor import FEFOMonitor  # noqa: F401

# ---- WH02/06 IoT 监控 ----
from hotpot_platform.cloud.warehouse.iot_monitor import IoTMonitor  # noqa: F401

# ---- WH04 库存预警 ----
from hotpot_platform.cloud.warehouse.inventory_alertor import InventoryAlertor  # noqa: F401


__all__ = [
    # 数据模型
    "RFIDItem", "TrackingResult", "Discrepancy",
    "BatchTrace", "BatchTimelineEntry", "ItemLocation",
    "FEFORecommendation", "FEVOStatus", "PickList", "PickAllocation",
    "Allocation", "OrderItem",
    "IoTReading", "IngestResult", "DeviceThresholdConfig", "DeviceStatus",
    "TemperatureTimeline", "TemperaturePoint",
    "StockAlertItem", "StockAlertSummary", "StockAlertReport", "AlertRule",
    # 核心引擎
    "RFIDTracker",      # WH01
    "FEFOMonitor",      # WH03 + WH05
    "IoTMonitor",       # WH02 + WH06
    "InventoryAlertor", # WH04
]
