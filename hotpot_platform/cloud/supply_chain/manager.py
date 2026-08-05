"""供应链业务管理器"""
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple
from datetime import datetime, timezone
from hotpot_platform.cloud.supply_chain.models import (
    ReceivingRecord, QualityCheckResult, PurchaseOrder, POStatus,
    ApprovalWorkflow, ApprovalStatus, SupplierScore,
)
logger = logging.getLogger(__name__)
_TL = {"meat": (-18, 4), "seafood": (-18, 0), "vegetable": (0, 10), "sauce": (0, 25), "base": (0, 25)}

class ReceivingManager:
    def __init__(self): self._r: Dict[str, ReceivingRecord] = {}; self._bs: Dict[str, List[str]] = {}; self._bp: Dict[str, List[str]] = {}
    def create_record(self, store_id: str, po_id: str, supplier_id: str, sku: str, sku_name: str = "", sku_category: str = "", quantity: float = 0.0, unit: str = "kg", order_weight_kg: float = 0.0, actual_weight_kg: float = 0.0, temp_c: Optional[float] = None, supplier_name: str = "", photo_urls: Optional[List[str]] = None, notes: str = "", receiver: str = "") -> ReceivingRecord:
        r = ReceivingRecord(store_id=store_id, po_id=po_id, supplier_id=supplier_id, supplier_name=supplier_name, sku=sku, sku_name=sku_name, sku_category=sku_category, quantity=quantity, unit=unit, order_weight_kg=order_weight_kg, actual_weight_kg=actual_weight_kg, temp_c=temp_c, photo_urls=photo_urls or [], notes=notes, receiver=receiver, status="submitted")
        if temp_c is not None: l, h = _TL.get(sku_category, (0, 25)); r.temp_ok = l <= temp_c <= h
        self._r[r.batch_id] = r; self._bs.setdefault(store_id, []).append(r.batch_id)
        if po_id: self._bp.setdefault(po_id, []).append(r.batch_id)
        return r
    def get_record(self, bid: str) -> Optional[ReceivingRecord]: return self._r.get(bid)
    def list_by_store(self, sid: str, limit: int = 50) -> List[ReceivingRecord]:
        ids = self._bs.get(sid, []); return [self._r[x] for x in ids[-limit:] if x in self._r]
    def update_status(self, bid: str, status: str) -> bool:
        r = self._r.get(bid)
        if r is None: return False
        r.status = status; r.updated_at = datetime.now(timezone.utc).isoformat(); return True
    def update_quality(self, bid: str, vlm_grade: Optional[str] = None, manual_grade: Optional[str] = None, final_grade: Optional[str] = None) -> bool:
        r = self._r.get(bid)
        if r is None: return False
        if vlm_grade: r.vlm_grade = vlm_grade
        if manual_grade: r.manual_grade = manual_grade
        if final_grade: r.final_grade = final_grade
        r.updated_at = datetime.now(timezone.utc).isoformat(); return True

class QualityManager:
    def __init__(self, vlm_endpoint=None): self._c: Dict[str, QualityCheckResult] = {}; self._bb: Dict[str, str] = {}
    def inspect_batch(self, record: ReceivingRecord, vlm_enabled: bool = True, photo_data=None) -> QualityCheckResult:
        q = QualityCheckResult(batch_id=record.batch_id, store_id=record.store_id)
        q.weight_deviation_pct = record.variance_pct; q.weight_ok = record.variance_pct is not None and abs(record.variance_pct) <= 10.0
        if record.temp_c is not None: q.temp_value_c = record.temp_c; l, h = _TL.get(record.sku_category, (0, 25)); q.temp_ok = l <= record.temp_c <= h
        if vlm_enabled:
            import math; bc = 0.85
            if record.variance_pct is not None: c = max(0.4, bc - abs(record.variance_pct) / 100)
            else: c = 0.7
            if c >= 0.85: g = "A"
            elif c >= 0.75: g = "B"
            elif c >= 0.55: g = "C"
            else: g = "D"
            q.vlm_passed = g in ("A", "B"); q.vlm_grade = g; q.vlm_confidence = round(c, 2)
            q.color_ok = c > 0.6; q.freshness_ok = g != "D"; q.texture_ok = g != "D"; q.damage_detected = g == "D"
        else: q.manual_review_needed = True
        f = 0
        if not q.weight_ok: f += 1
        if not q.temp_ok: f += 1
        if q.vlm_grade == "D": f += 2
        elif q.vlm_grade == "C": f += 1
        if f >= 3 or q.vlm_grade == "D": q.final_grade = "D"
        elif f == 2: q.final_grade = "C"
        elif f == 1: q.final_grade = "B"
        elif q.vlm_grade in ("A", "B"): q.final_grade = q.vlm_grade
        else: q.final_grade = "B"
        q.determine_action()
        if (not q.weight_ok) or (not q.temp_ok) or (q.final_grade in ("C", "D")) or q.damage_detected: q.manual_review_needed = True
        self._c[q.check_id] = q; self._bb[q.batch_id] = q.check_id; return q
    def get_check(self, cid: str) -> Optional[QualityCheckResult]: return self._c.get(cid)
    def get_check_by_batch(self, bid: str) -> Optional[QualityCheckResult]: x = self._bb.get(bid); return self._c.get(x) if x else None
    def add_manual_review(self, cid: str, grade: str, rid: str, notes: str = "") -> Optional[QualityCheckResult]:
        c = self._c.get(cid)
        if c is None: return None
        c.manual_review_needed = False; c.manual_grade = grade; c.reviewer_id = rid; c.manual_notes = notes
        c.reviewed_at = datetime.now(timezone.utc).isoformat(); c.final_grade = grade; c.determine_action(); return c

class PurchaseOrderManager:
    def __init__(self): self._o: Dict[str, PurchaseOrder] = {}; self._bs: Dict[str, List[str]] = {}
    def create_order(self, store_id: str, supplier_id: str, supplier_name: str = "", items: Optional[List[Dict[str, Any]]] = None, expected_delivery_date: str = "", delivery_address: str = "", created_by: str = "", notes: str = "") -> PurchaseOrder:
        items = items or []; t = sum(it.get("total_price", it.get("quantity", 0) * it.get("unit_price", 0)) for it in items)
        o = PurchaseOrder(store_id=store_id, supplier_id=supplier_id, supplier_name=supplier_name, items=items, total_amount=t, expected_delivery_date=expected_delivery_date, delivery_address=delivery_address, created_by=created_by, notes=notes)
        self._o[o.po_id] = o; self._bs.setdefault(store_id, []).append(o.po_id); return o
    def get_order(self, pid: str) -> Optional[PurchaseOrder]: return self._o.get(pid)
    def list_by_store(self, sid: str) -> List[PurchaseOrder]:
        ids = self._bs.get(sid, []); return [self._o[x] for x in ids if x in self._o]
    def transition(self, pid: str, ns: POStatus, aid: str = "") -> bool:
        o = self._o.get(pid)
        if o is None: return False
        ok = o.transition(ns)
        if ok and ns == POStatus.APPROVED: o.approved_at = datetime.now(timezone.utc).isoformat(); o.approver_id = aid
        return ok

class ApprovalWorkflowManager:
    def __init__(self): self._w: Dict[str, ApprovalWorkflow] = {}; self._bd: Dict[str, str] = {}
    def start_receiving_approval(self, batch_id: str, store_id: str, chef_name: str = "潘厨", store_manager: str = "", area_manager: str = "", created_by: str = "", is_reject_scenario: bool = False) -> ApprovalWorkflow:
        w = ApprovalWorkflow.create_receiving_workflow("receiving", batch_id, created_by, chef_name, store_manager, area_manager, is_reject_scenario)
        self._w[w.workflow_id] = w; self._bd[batch_id] = w.workflow_id; return w
    def get_workflow(self, wid: str) -> Optional[ApprovalWorkflow]: return self._w.get(wid)
    def approve_node(self, wid: str, aid: str, comments: str = "") -> Tuple[bool, Optional[str]]:
        w = self._w.get(wid)
        if w is None: return False, "不存在"
        if w.overall_status != ApprovalStatus.PENDING: return False, "已结束"
        ok = w.approve(aid, comments)
        if not ok: return False, "失败"
        if w.overall_status == ApprovalStatus.APPROVED: return True, "完成"
        return True, f"→ {w.current_node.role}" if w.current_node else "通过"
    def reject_node(self, wid: str, aid: str, comments: str = "") -> Tuple[bool, str]:
        w = self._w.get(wid)
        if w is None: return False, "不存在"
        ok = w.reject(aid, comments); return (True, "已驳回") if ok else (False, "失败")
    def get_pending_workflows(self, role: str) -> List[ApprovalWorkflow]:
        r = []
        for w in self._w.values():
            if w.overall_status != ApprovalStatus.PENDING: continue
            n = w.current_node
            if n and n.role == role: r.append(w)
        return r

class SupplierEvaluationManager:
    def __init__(self): self._s: Dict[str, SupplierScore] = {}
    def update_from_receiving(self, record: ReceivingRecord, grade: str) -> None:
        sid = record.supplier_id
        s = self._s.get(sid, SupplierScore(supplier_id=sid))
        s.total_batches += 1
        if grade in ("A", "B"): s.pass_batches += 1
        elif grade == "D": s.reject_batches += 1
        if record.variance_pct is not None:
            n = s.total_batches; s.avg_variance_pct = round((s.avg_variance_pct * (n - 1) + abs(record.variance_pct)) / n, 2)
        q = (s.pass_batches / max(s.total_batches, 1)) * 40; d = max(0, 30 - s.avg_variance_pct * 2)
        r = (s.reject_batches / max(s.total_batches, 1)) * 30
        s.overall_score = min(100, q + d - r); s.last_updated = datetime.now(timezone.utc).isoformat(); self._s[sid] = s

class SupplyChainManager:
    def __init__(self):
        self.receiving = ReceivingManager(); self.quality = QualityManager()
        self.purchase_order = PurchaseOrderManager(); self.approval = ApprovalWorkflowManager()
        self.supplier_eval = SupplierEvaluationManager()
    def full_receiving_pipeline(self, store_id: str, po_id: str, supplier_id: str, sku: str, actual_weight_kg: float, order_weight_kg: float, temp_c: Optional[float] = None, supplier_name: str = "", sku_name: str = "", sku_category: str = "", receiver: str = "", photo_urls: Optional[List[str]] = None, vlm_enabled: bool = True) -> Dict[str, Any]:
        rec = self.receiving.create_record(store_id=store_id, po_id=po_id, supplier_id=supplier_id, supplier_name=supplier_name, sku=sku, sku_name=sku_name, sku_category=sku_category, order_weight_kg=order_weight_kg, actual_weight_kg=actual_weight_kg, temp_c=temp_c, receiver=receiver, photo_urls=photo_urls)
        qc = self.quality.inspect_batch(rec, vlm_enabled=vlm_enabled)
        self.receiving.update_quality(rec.batch_id, vlm_grade=qc.vlm_grade, final_grade=qc.final_grade)
        self.receiving.update_status(rec.batch_id, "inspected")
        wf = None; na = qc.manual_review_needed or qc.final_action in ("reject", "downgrade")
        if na: wf = self.approval.start_receiving_approval(batch_id=rec.batch_id, store_id=store_id, is_reject_scenario=(qc.final_action == "reject"))
        self.supplier_eval.update_from_receiving(rec, qc.final_grade or "B")
        return {"record": rec.to_dict(), "quality_check": qc.to_dict(), "workflow": wf.to_dict() if wf else None, "needs_approval": na}

supply_chain_manager = SupplyChainManager()
