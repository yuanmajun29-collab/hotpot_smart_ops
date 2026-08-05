"""供应链数据模型 — dataclass 版本"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional

class QualityGrade(str, Enum): A="A"; B="B"; C="C"; D="D"; PENDING="PENDING"

class POStatus(str, Enum):
    DRAFT="draft"; SUBMITTED="submitted"; APPROVED="approved"; ORDERED="ordered"; SHIPPED="shipped"
    RECEIVING="receiving"; RECEIVED="received"; INSPECTING="inspecting"; COMPLETED="completed"
    REJECTED="rejected"; CANCELLED="cancelled"
    @classmethod
    def transitions(cls) -> Dict[str, List[str]]:
        return {cls.DRAFT:[cls.SUBMITTED,cls.CANCELLED],cls.SUBMITTED:[cls.APPROVED,cls.REJECTED,cls.CANCELLED],cls.APPROVED:[cls.ORDERED,cls.CANCELLED],cls.ORDERED:[cls.SHIPPED,cls.CANCELLED],cls.SHIPPED:[cls.RECEIVING,cls.CANCELLED],cls.RECEIVING:[cls.RECEIVED,cls.REJECTED],cls.RECEIVED:[cls.INSPECTING],cls.INSPECTING:[cls.COMPLETED,cls.REJECTED]}

class ApprovalStatus(str, Enum): PENDING="pending"; APPROVED="approved"; REJECTED="rejected"; SKIPPED="skipped"; RECALLED="recalled"

@dataclass
class ReceivingRecord:
    batch_id: str=""; store_id: str=""; po_id: str=""; supplier_id: str=""; supplier_name: str=""
    sku: str=""; sku_name: str=""; sku_category: str=""
    quantity: float=0.0; unit: str="kg"; order_weight_kg: float=0.0; actual_weight_kg: float=0.0
    variance_pct: Optional[float]=None; temp_c: Optional[float]=None; temp_ok: Optional[bool]=None
    vlm_grade: Optional[str]=None; manual_grade: Optional[str]=None; final_grade: Optional[str]=None
    status: str="submitted"; photo_urls: List[str]=field(default_factory=list)
    notes: str=""; receiver: str=""; chef: str=""
    signatures: List[Dict[str,Any]]=field(default_factory=list)
    created_at: str=field(default_factory=lambda: datetime.now(timezone.utc).isoformat()); updated_at: str=""
    def __post_init__(self):
        if not self.batch_id: self.batch_id=f"RCV-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        if self.actual_weight_kg and self.order_weight_kg: self.variance_pct=round((self.actual_weight_kg-self.order_weight_kg)/self.order_weight_kg*100,2)
    def to_dict(self)->Dict[str,Any]: return asdict(self)

@dataclass
class QualityCheckResult:
    check_id: str=""; batch_id: str=""; store_id: str=""
    vlm_passed: Optional[bool]=None; vlm_grade: Optional[str]=None; vlm_confidence: float=0.0
    vlm_issues: List[str]=field(default_factory=list)
    color_ok: Optional[bool]=None; freshness_ok: Optional[bool]=None; texture_ok: Optional[bool]=None
    damage_detected: bool=False; foreign_object: bool=False
    weight_ok: Optional[bool]=None; weight_deviation_pct: Optional[float]=None
    temp_ok: Optional[bool]=None; temp_value_c: Optional[float]=None
    manual_review_needed: bool=False; manual_grade: Optional[str]=None; manual_notes: str=""; reviewer_id: str=""
    final_grade: Optional[str]=None; final_action: str=""; reason: str=""
    checked_at: str=field(default_factory=lambda: datetime.now(timezone.utc).isoformat()); reviewed_at: str=""
    def __post_init__(self):
        if not self.check_id: self.check_id=f"QC-{uuid.uuid4().hex[:8].upper()}"
    def determine_action(self)->str:
        if self.final_grade=="D": self.final_action="reject"; self.reason="质检不合格拒收"
        elif self.weight_deviation_pct and abs(self.weight_deviation_pct)>10: self.final_action="reject"; self.reason=f"重量偏差{self.weight_deviation_pct}%超10%"
        elif self.final_grade=="C": self.final_action="downgrade"; self.reason="降级处理"
        else: self.final_action="accept"; self.reason="质检通过"
        return self.final_action
    def to_dict(self)->Dict[str,Any]: return asdict(self)

@dataclass
class PurchaseOrder:
    po_id: str=""; store_id: str=""; supplier_id: str=""; supplier_name: str=""
    status: POStatus=POStatus.DRAFT; items: List[Dict[str,Any]]=field(default_factory=list)
    total_amount: float=0.0; currency: str="CNY"
    expected_delivery_date: str=""; actual_delivery_date: str=""; delivery_address: str=""
    receiving_batches: List[str]=field(default_factory=list)
    approver_id: str=""; approved_at: str=""; approval_notes: str=""
    created_by: str=""; created_at: str=field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str=""; notes: str=""
    def __post_init__(self):
        if not self.po_id: self.po_id=f"PO-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{uuid.uuid4().hex[:5].upper()}"
    def transition(self, new_status: POStatus)->bool:
        allowed=POStatus.transitions().get(self.status,[])
        if new_status.value in [s.value for s in allowed]: self.status=new_status; self.updated_at=datetime.now(timezone.utc).isoformat(); return True
        return False
    def add_receiving_batch(self, batch_id: str)->None:
        if batch_id not in self.receiving_batches: self.receiving_batches.append(batch_id)
    def to_dict(self)->Dict[str,Any]: d=asdict(self); d["status"]=self.status.value; return d

@dataclass
class ApprovalNode:
    node_id: str; role: str; approver_id: str=""; approver_name: str=""
    status: ApprovalStatus=ApprovalStatus.PENDING; comments: str=""; decided_at: str=""; sequence: int=0
    def to_dict(self)->Dict[str,Any]: return asdict(self)

@dataclass
class ApprovalWorkflow:
    workflow_id: str=""; document_type: str=""; document_id: str=""
    nodes: List[ApprovalNode]=field(default_factory=list); current_node_index: int=0
    overall_status: ApprovalStatus=ApprovalStatus.PENDING; created_by: str=""
    created_at: str=field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    def __post_init__(self):
        if not self.workflow_id: self.workflow_id=f"WF-{uuid.uuid4().hex[:8].upper()}"
    @property
    def current_node(self)->Optional[ApprovalNode]:
        if 0<=self.current_node_index<len(self.nodes): return self.nodes[self.current_node_index]
        return None
    def approve(self, approver_id: str, comments: str="")->bool:
        node=self.current_node
        if node is None: return False
        node.status=ApprovalStatus.APPROVED; node.approver_id=approver_id; node.comments=comments
        node.decided_at=datetime.now(timezone.utc).isoformat(); self.current_node_index+=1
        if self.current_node_index>=len(self.nodes): self.overall_status=ApprovalStatus.APPROVED
        return True
    def reject(self, approver_id: str, comments: str="")->bool:
        node=self.current_node
        if node is None: return False
        node.status=ApprovalStatus.REJECTED; node.approver_id=approver_id; node.comments=comments
        node.decided_at=datetime.now(timezone.utc).isoformat(); self.overall_status=ApprovalStatus.REJECTED
        return True
    @classmethod
    def create_receiving_workflow(cls, document_type: str, document_id: str, created_by: str,
                                   chef_name: str="潘厨", store_manager: str="", area_manager: str="",
                                   is_reject_scenario: bool=False)->"ApprovalWorkflow":
        nodes=[ApprovalNode(node_id=f"N-{uuid.uuid4().hex[:6].upper()}",role="chef",approver_name=chef_name,sequence=0),
               ApprovalNode(node_id=f"N-{uuid.uuid4().hex[:6].upper()}",role="chef_final",approver_name=chef_name,sequence=1)]
        if store_manager: nodes.append(ApprovalNode(node_id=f"N-{uuid.uuid4().hex[:6].upper()}",role="store_manager",approver_name=store_manager,sequence=len(nodes)))
        if area_manager and is_reject_scenario: nodes.append(ApprovalNode(node_id=f"N-{uuid.uuid4().hex[:6].upper()}",role="area_manager",approver_name=area_manager,sequence=len(nodes)))
        return cls(document_type=document_type,document_id=document_id,created_by=created_by,nodes=nodes)
    def to_dict(self)->Dict[str,Any]: d=asdict(self); d["overall_status"]=self.overall_status.value; return d

@dataclass
class SupplierScore:
    supplier_id: str; supplier_name: str=""; overall_score: float=0.0
    quality_score: float=0.0; delivery_score: float=0.0; price_score: float=0.0; service_score: float=0.0
    total_batches: int=0; pass_batches: int=0; reject_batches: int=0; avg_variance_pct: float=0.0
    last_updated: str=field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    def to_dict(self)->Dict[str,Any]: return asdict(self)
