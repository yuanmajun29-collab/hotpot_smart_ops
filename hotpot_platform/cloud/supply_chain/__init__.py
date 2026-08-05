"""供应链模块"""
from hotpot_platform.cloud.supply_chain.models import (
    ReceivingRecord, QualityCheckResult, QualityGrade,
    PurchaseOrder, POStatus, ApprovalWorkflow, ApprovalNode, ApprovalStatus, SupplierScore,
)
from hotpot_platform.cloud.supply_chain.manager import (
    ReceivingManager, QualityManager, PurchaseOrderManager,
    ApprovalWorkflowManager, SupplyChainManager, supply_chain_manager,
)
from hotpot_platform.cloud.supply_chain.vlm_bridge import (
    VlmBridgeClient, QualityItem, QualityInspectionResult, get_vlm_bridge,
)
from hotpot_platform.cloud.supply_chain.scenario_orchestrator import (
    SupplyChainScenarioOrchestrator, ScenarioRun, ScenarioStep,
    ScenarioStatus, ScenarioType,
)
from hotpot_platform.cloud.supply_chain.db import (
    SupplyChainDB, get_db, init_db,
)
