"""
火瞳 · 冻品供应链 — 统一入口 (hotpot_platform.cloud.supply_chain)

对应 PRD S01-S04:

  S01 供应商管理       → SupplyChainManager.create_supplier / get_supplier / list_suppliers
  S02 收货质检(VLM)    → SupplyChainManager.submit_receiving / approve_quality_check
  S03 采购订单管理     → SupplyChainManager.create_purchase_order / submit / confirm
  S04 供应商协同       → SupplyChainManager.get_supplier_collab_data / update_supplier_score

关键角色:
  潘总(潘厨) → 品质管控 (质检审批)
  王总(供应商) → 供货+对账
  曹总 → 统一下单标准

集成:
  warehouse.RFIDTracker   → 收货批次自动追踪
  warehouse.IoTMonitor    → 到货温度验证
  data_engine.SupplierScorer → 供应商评分
"""

# ---- 数据模型 ----
from hotpot_platform.cloud.supply_chain.models import (  # noqa: F401
    SupplierInfo, SupplierCollabData,
    ReceivingRecord, ReceivingItem, QualityCheckResult,
    PurchaseOrder, PurchaseOrderItem,
    SupplierScoreUpdate,
)

# ---- 核心管理器 ----
from hotpot_platform.cloud.supply_chain.manager import SupplyChainManager  # noqa: F401


__all__ = [
    # 数据模型
    "SupplierInfo", "SupplierCollabData",
    "ReceivingRecord", "ReceivingItem", "QualityCheckResult",
    "PurchaseOrder", "PurchaseOrderItem",
    "SupplierScoreUpdate",
    # 管理器
    "SupplyChainManager",
]
