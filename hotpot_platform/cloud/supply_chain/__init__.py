"""供应链模块"""
from hotpot_platform.cloud.supply_chain.models import (
    ReceivingRecord, QualityCheckResult, QualityGrade,
    PurchaseOrder, POStatus, ApprovalWorkflow, ApprovalNode, ApprovalStatus, SupplierScore,
)
from hotpot_platform.cloud.supply_chain.manager import (
    ReceivingManager, QualityManager, PurchaseOrderManager,
    ApprovalWorkflowManager, SupplyChainManager, supply_chain_manager,
)
