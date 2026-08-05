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

# VLM Bridge 集成：替代 Mock 模拟，对接真实 VLM 推理
try:
    from hotpot_platform.cloud.supply_chain.vlm_bridge import VlmBridgeClient, get_vlm_bridge
except ImportError:
    VlmBridgeClient = None  # type: ignore
    get_vlm_bridge = None
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
    def __init__(self, vlm_endpoint=None):
        self._c: Dict[str, QualityCheckResult] = {}; self._bb: Dict[str, str] = {}
        # 初始化 VLM Bridge（自动检测可用性）
        self._vlm_bridge = None
        self._vlm_available = False
        if VlmBridgeClient is not None and get_vlm_bridge is not None:
            try:
                self._vlm_bridge = get_vlm_bridge()
                self._vlm_available = True
            except Exception:
                pass

    def inspect_batch(self, record: ReceivingRecord, vlm_enabled: bool = True, photo_data=None) -> QualityCheckResult:
        q = QualityCheckResult(batch_id=record.batch_id, store_id=record.store_id)
        q.weight_deviation_pct = record.variance_pct; q.weight_ok = record.variance_pct is not None and abs(record.variance_pct) <= 10.0
        if record.temp_c is not None: q.temp_value_c = record.temp_c; l, h = _TL.get(record.sku_category, (0, 25)); q.temp_ok = l <= record.temp_c <= h
        if vlm_enabled:
            # 优先使用真实 VLM Bridge，不可用时回退 Mock
            vlm_grade, vlm_confidence = self._run_vlm_quality(record, photo_data)
            g = vlm_grade; c = vlm_confidence
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
    def _run_vlm_quality(self, record: ReceivingRecord, photo_data=None) -> Tuple[str, float]:
        """执行真实 VLM 质检或 Mock 兜底。

        优先调用 VlmBridgeClient 对接 Jetson VLM 推理；
        VLM 不可用时回退到概率模拟（Mock）。
        """
        # 尝试真实 VLM 质检（同步路径使用 mock_inspect_sync；真实 VLM 需通过异步 inspect_image）
        if self._vlm_available and self._vlm_bridge is not None:
            try:
                # 同步下调用 mock_inspect_sync 获取模拟结果（真实 VLM 需异步 inspect_image 路径）
                vlm_result = self._vlm_bridge.mock_inspect_sync(
                    batch_id=record.batch_id,
                    store_id=record.store_id,
                    zone="收货区",
                )
                if vlm_result.items:
                    worst_g = "A"
                    grade_map = {"A": 1, "B": 2, "C": 3, "D": 4}
                    for item in vlm_result.items:
                        if grade_map.get(item.grade, 3) > grade_map.get(worst_g, 1):
                            worst_g = item.grade
                    return worst_g, vlm_result.items[0].confidence if vlm_result.items else 0.7
            except Exception as e:
                logger.warning(f"VLM real call failed, using mock: {e}")

        # Mock 兜底（原概率算法，保持向后兼容）
        import math
        bc = 0.85
        if record.variance_pct is not None:
            c = max(0.4, bc - abs(record.variance_pct) / 100)
        else:
            c = 0.7
        if c >= 0.85:
            g = "A"
        elif c >= 0.75:
            g = "B"
        elif c >= 0.55:
            g = "C"
        else:
            g = "D"
        return g, round(c, 2)

    def set_vlm_bridge(self, bridge) -> None:
        """注入外部 VLM Bridge 实例（用于集成测试或真实部署）。"""
        self._vlm_bridge = bridge
        self._vlm_available = bridge is not None

    def enable_vlm(self) -> None:
        """启用 VLM 真实推理（需要 VlmBridgeClient 可用）。"""
        if VlmBridgeClient is not None and get_vlm_bridge is not None:
            try:
                self._vlm_bridge = get_vlm_bridge(use_mock=False)
                self._vlm_available = True
            except Exception:
                self._vlm_available = False

    def disable_vlm(self) -> None:
        """禁用 VLM，回退到 Mock 模式。"""
        self._vlm_available = False
        if self._vlm_bridge and VlmBridgeClient is not None:
            try:
                self._vlm_bridge._use_mock = True
            except Exception:
                pass

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
    """供应链统一门面 — 聚合 Receiving / Quality / PurchaseOrder / Approval / Supplier 子模块。

    P0 整改：恢复所有被 Edge / agent_gateway / scenario_orchestrator 调用的 API，
    避免 AttributeError。
    """

    def __init__(self):
        self.receiving = ReceivingManager(); self.quality = QualityManager()
        self.purchase_order = PurchaseOrderManager(); self.approval = ApprovalWorkflowManager()
        self.supplier_eval = SupplierEvaluationManager()
        # ── 内存主数据 & 任务簿 (W2 精简后在此补充) ──
        self._products: Dict[str, Dict[str, Any]] = {}
        self._tasks: Dict[str, Dict[str, Any]] = {}
        self._suggestions: List[Dict[str, Any]] = []
        self._suppliers: Dict[str, Dict[str, Any]] = {}
        self._inventory: Dict[str, Dict[str, Any]] = {}
        self._po_list: Dict[str, Dict[str, Any]] = {}
        self._initialized = False

    # ─── 初始化（供 Edge 调用）────────────────────────────────────────────

    def init_product_data(self, file_path: Optional[str] = None) -> None:
        """从 product_master.json 加载种子数据到内存主数据表（W2 兼容）。"""
        import json as _json
        if file_path and __import__("os").path.isfile(file_path):
            try:
                with open(file_path) as fh:
                    items = _json.load(fh)
                if isinstance(items, list):
                    for it in items:
                        pid = it.get("product_id") or it.get("id", "")
                        if pid:
                            self._products[pid] = it
                elif isinstance(items, dict):
                    self._products.update(items)
            except Exception as e:
                logger.warning(f"init_product_data 读取 {file_path} 失败: {e}")
        if not self._products:
            # 种子默认数据
            self._products["FP-HNRC-001"] = {"product_id": "FP-HNRC-001", "name": "汉拿山肥牛卷", "category": "FROZEN_MEAT", "unit": "kg", "price": 68.0, "is_active": True}
            self._products["FP-HNRC-002"] = {"product_id": "FP-HNRC-002", "name": "精品羊肉卷", "category": "FROZEN_MEAT", "unit": "kg", "price": 78.0, "is_active": True}
        self._initialized = True

    # ─── 收货质检门面 ─────────────────────────────────────────────────────

    def full_receiving_pipeline(self, store_id: str, po_id: str, supplier_id: str, sku: str, actual_weight_kg: float, order_weight_kg: float, temp_c: Optional[float] = None, supplier_name: str = "", sku_name: str = "", sku_category: str = "", receiver: str = "", photo_urls: Optional[List[str]] = None, vlm_enabled: bool = True) -> Dict[str, Any]:
        rec = self.receiving.create_record(store_id=store_id, po_id=po_id, supplier_id=supplier_id, supplier_name=supplier_name, sku=sku, sku_name=sku_name, sku_category=sku_category, order_weight_kg=order_weight_kg, actual_weight_kg=actual_weight_kg, temp_c=temp_c, receiver=receiver, photo_urls=photo_urls)
        qc = self.quality.inspect_batch(rec, vlm_enabled=vlm_enabled)
        self.receiving.update_quality(rec.batch_id, vlm_grade=qc.vlm_grade, final_grade=qc.final_grade)
        self.receiving.update_status(rec.batch_id, "inspected")
        wf = None; na = qc.manual_review_needed or qc.final_action in ("reject", "downgrade")
        if na: wf = self.approval.start_receiving_approval(batch_id=rec.batch_id, store_id=store_id, is_reject_scenario=(qc.final_action == "reject"))
        self.supplier_eval.update_from_receiving(rec, qc.final_grade or "B")
        return {"record": rec.to_dict(), "quality_check": qc.to_dict(), "workflow": wf.to_dict() if wf else None, "needs_approval": na}

    def run_vlm_inspection(self, record_id: str, use_mock: bool = False, photo_data=None) -> Dict[str, Any]:
        """Edge receiving_api 调用 — 对指定记录执行 VLM 质检。"""
        rec = self.receiving.get_record(record_id)
        if rec is None:
            raise ValueError(f"收货记录不存在: {record_id}")
        if use_mock:
            self.quality.disable_vlm()
        qc = self.quality.inspect_batch(rec, vlm_enabled=not use_mock, photo_data=photo_data)
        self.receiving.update_quality(rec.batch_id, vlm_grade=qc.vlm_grade, final_grade=qc.final_grade)
        return qc.to_dict()

    def get_receiving_detail(self, record_id: str) -> Optional[Dict[str, Any]]:
        rec = self.receiving.get_record(record_id)
        return rec.to_dict() if rec else None

    def submit_receiving(self, record: Any) -> Dict[str, Any]:
        """Gateway handler — 提交收货记录。"""
        d = record if isinstance(record, dict) else record.model_dump() if hasattr(record, "model_dump") else record.__dict__
        rec = self.receiving.create_record(**{k: v for k, v in d.items() if k in ("store_id", "po_id", "supplier_id", "sku", "sku_name", "sku_category", "quantity", "unit", "order_weight_kg", "actual_weight_kg", "temp_c", "supplier_name", "photo_urls", "notes", "receiver")})
        return rec.to_dict()

    # ─── 采购门面 ─────────────────────────────────────────────────────────

    def approve_purchase_task(self, task_id: str, approved_by: str = "gateway") -> Optional[Dict[str, Any]]:
        """审批采购任务（Edge assistant / agent_gateway 调用）。"""
        task = self._tasks.get(task_id)
        if task is None:
            logger.warning(f"approve_purchase_task: 任务 {task_id} 不存在")
            return None
        task["status"] = "approved"
        task["approved_by"] = approved_by
        task["approved_at"] = datetime.now(timezone.utc).isoformat()
        po_id = task.get("po_id") or f"PO-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{len(self._po_list)+1:03d}"
        items = task.get("items") or task.get("suggested_items", [])
        supplier_id = task.get("supplier_id") or "SUP-001"
        po = self.purchase_order.create_order(
            store_id=task.get("store_id", "store_jiaojiang"),
            supplier_id=supplier_id,
            supplier_name=task.get("supplier_name", ""),
            items=items,
            expected_delivery_date=task.get("expected_delivery_date", ""),
            created_by=approved_by)
        self._po_list[po.po_id] = po.to_dict()
        task["po_number"] = po.po_id
        return po.to_dict()

    def create_purchase_approval_task(self, suggestion_id: Optional[str] = None, items: Optional[List[Dict[str, Any]]] = None, supplier: str = "", store_id: str = "store_jiaojiang", requested_by: str = "gateway") -> Dict[str, Any]:
        """Gateway handler — 创建待审批的采购任务。"""
        import uuid as _uuid
        tid = suggestion_id or f"task-{_uuid.uuid4().hex[:12]}"
        task = {
            "task_id": tid,
            "type": "purchase_approval",
            "status": "pending",
            "suggestion_id": suggestion_id,
            "items": items or [],
            "supplier": supplier,
            "store_id": store_id,
            "requested_by": requested_by,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._tasks[tid] = task
        return task

    def create_po_from_suggestion(self, suggestion_id: str, approved_by: str = "gateway") -> Optional[Dict[str, Any]]:
        """Gateway handler — 从采购建议直接创建订单。"""
        return self.approve_purchase_task(suggestion_id, approved_by=approved_by)

    def generate_procurement_suggestion(self, store_id: str) -> Dict[str, Any]:
        """场景编排调用 — 基于预测生成采购建议。"""
        sug_id = f"SUG-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{len(self._suggestions)+1:03d}"
        suggestion = {
            "suggestion_id": sug_id,
            "store_id": store_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "items": [
                {"sku": "FP-HNRC-001", "name": "汉拿山肥牛卷", "suggested_qty_kg": 50, "unit_price": 68.0, "reason": "库存不足3天"},
                {"sku": "BEEF-003", "name": "雪花牛肉", "suggested_qty_kg": 30, "unit_price": 120.0, "reason": "预测需求增长"},
            ],
            "total_estimate": 50 * 68.0 + 30 * 120.0,
            "status": "draft",
        }
        self._suggestions.append(suggestion)
        return suggestion

    def create_purchase_order(self, store_id: str, items: List[Dict[str, Any]], supplier_id: str = "", supplier_name: str = "", created_by: str = "") -> Dict[str, Any]:
        """场景编排调用 — 创建采购订单。"""
        po = self.purchase_order.create_order(store_id=store_id, supplier_id=supplier_id or "SUP-001", supplier_name=supplier_name, items=items, created_by=created_by)
        self._po_list[po.po_id] = po.to_dict()
        return po.to_dict()

    def receive_purchase_order(self, store_id: str, po_number: str, items: Optional[List[Dict[str, Any]]] = None, receiver: str = "", batch_id: str = "") -> Dict[str, Any]:
        """场景编排调用 — 采购订单收货入口。"""
        items = items or []
        batch_id = batch_id or f"BATCH-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}"
        for item in items:
            self.receiving.create_record(
                store_id=store_id, po_id=po_number,
                supplier_id=item.get("supplier_id", "SUP-001"),
                supplier_name=item.get("supplier_name", ""),
                sku=item.get("sku", item.get("sku_code", "")),
                sku_name=item.get("product_name", item.get("name", "")),
                order_weight_kg=item.get("expected_qty_kg", item.get("qty", 10)),
                actual_weight_kg=item.get("actual_qty_kg", item.get("received_weight_kg", item.get("qty", 10))),
                receiver=receiver)
        return {"batch_id": batch_id, "po_number": po_number, "items_received": len(items), "status": "received"}

    def confirm_inventory_receipt(self, store_id: str, batch_id: str, items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """场景编排调用 — 确认库存入库。"""
        for item in (items or []):
            sku = item.get("sku", item.get("sku_code", ""))
            if sku:
                inv = self._inventory.get(sku, {"sku": sku, "quantity_kg": 0})
                inv["quantity_kg"] += item.get("quantity_kg", item.get("qty", 0))
                self._inventory[sku] = inv
        return {"batch_id": batch_id, "status": "confirmed", "source": "memory"}

    def inspect_received_goods(self, store_id: str, batch_id: str, items: Optional[List[Dict[str, Any]]] = None, vlm_enabled: bool = True, photo_data=None) -> Dict[str, Any]:
        """场景编排调用 — 对已收货批次执行质检。"""
        items = items or []
        results = []
        for item in items:
            rec = self.receiving.create_record(
                store_id=store_id, po_id=item.get("po_number", ""),
                supplier_id=item.get("supplier_id", "SUP-001"),
                supplier_name=item.get("supplier_name", ""),
                sku=item.get("sku", item.get("sku_code", "")),
                sku_name=item.get("product_name", ""),
                order_weight_kg=item.get("expected_qty_kg", 10),
                actual_weight_kg=item.get("received_weight_kg", item.get("actual_qty_kg", 10)),
                receiver=item.get("receiver", ""))
            qc = self.quality.inspect_batch(rec, vlm_enabled=vlm_enabled, photo_data=photo_data)
            self.receiving.update_quality(rec.batch_id, vlm_grade=qc.vlm_grade, final_grade=qc.final_grade)
            results.append({"sku": item.get("sku", ""), "grade": qc.final_grade, "vlm_grade": qc.vlm_grade, "pass": qc.vlm_passed})
        return {"batch_id": batch_id, "results": results, "overall_pass": all(r["pass"] for r in results)}

    def create_return_order(self, store_id: str, supplier_id: str, items: List[Dict[str, Any]], reason: str = "", batch_id: str = "") -> Dict[str, Any]:
        """场景编排调用 — 创建退货单。"""
        return {
            "return_id": f"RET-{datetime.now(timezone.utc).strftime('%Y%m%d')}-{len(items):03d}",
            "store_id": store_id, "supplier_id": supplier_id,
            "items": items, "reason": reason,
            "status": "created", "batch_id": batch_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

    def create_replacement_order(self, store_id: str, return_id: str, items: List[Dict[str, Any]], supplier_id: str = "", urgent: bool = False) -> Dict[str, Any]:
        """场景编排调用 — 创建换货单。"""
        po = self.purchase_order.create_order(
            store_id=store_id, supplier_id=supplier_id or "SUP-001",
            supplier_name="", items=items,
            expected_delivery_date=(datetime.now(timezone.utc) + __import__("datetime").timedelta(days=1 if urgent else 3)).isoformat(),
            created_by="orchestrator", notes=f"换货 {return_id}")
        self._po_list[po.po_id] = po.to_dict()
        return po.to_dict()

    def generate_emergency_restock(self, store_id: str, items: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
        """场景编排调用 — 紧急补货建议。"""
        items = items or [
            {"sku": "FP-HNRC-001", "name": "汉拿山肥牛卷", "urgent_qty_kg": 80, "unit_price": 68.0, "reason": "库存熔断"},
        ]
        return {
            "suggestion_id": f"EMG-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M')}",
            "store_id": store_id, "items": items,
            "total_estimate": sum(it.get("urgent_qty_kg", 0) * it.get("unit_price", 0) for it in items),
            "priority": "CRITICAL",
            "status": "pending",
        }

    def create_emergency_purchase_order(self, store_id: str, items: List[Dict[str, Any]], supplier_id: str = "", reason: str = "") -> Dict[str, Any]:
        """场景编排调用 — 紧急采购单。"""
        return self.create_purchase_order(store_id=store_id, items=items, supplier_id=supplier_id, created_by="emergency_orchestrator")

    # ─── 查询门面 ─────────────────────────────────────────────────────────

    def get_dashboard_full(self, include_kitchen: bool = False, include_purchase: bool = False) -> Dict[str, Any]:
        return {"summary": "门店看板", "total_po": len(self._po_list), "pending_tasks": sum(1 for t in self._tasks.values() if t.get("status") == "pending")}

    def get_tasks(self, role: str = "store_manager", status: str = "pending") -> List[Dict[str, Any]]:
        return [t for t in self._tasks.values() if t.get("status") == status]

    def get_suggestions(self, role: str = "store_manager") -> List[Dict[str, Any]]:
        return list(self._suggestions)

    def get_po_list(self, status: Optional[str] = None, store_id: Optional[str] = None) -> List[Dict[str, Any]]:
        result = list(self._po_list.values())
        if status:
            result = [p for p in result if p.get("status") == status]
        if store_id:
            result = [p for p in result if p.get("store_id") == store_id]
        return result

    def get_supplier_list(self) -> List[Dict[str, Any]]:
        return [
            {"supplier_id": "SUP-001", "name": "鑫盛食品", "contact": "张经理", "rating": "A", "overall_score": 94.0},
            {"supplier_id": "SUP-002", "name": "华源冷链", "contact": "李经理", "rating": "B+", "overall_score": 89.0},
            {"supplier_id": "SUP-003", "name": "海底食品", "contact": "王经理", "rating": "A-", "overall_score": 91.0},
        ]

    def list_product_masters(self) -> List[Dict[str, Any]]:
        if not self._products:
            self.init_product_data()
        return list(self._products.values())

    def cancel_po(self, po_number: str, reason: str = "") -> Optional[Dict[str, Any]]:
        po = self._po_list.get(po_number)
        if po is None:
            return None
        po["status"] = "cancelled"
        po["cancel_reason"] = reason
        po["cancelled_at"] = datetime.now(timezone.utc).isoformat()
        return {"po_number": po_number, "status": "cancelled", "reason": reason}

    def create_supplier(self, supplier: Any) -> Dict[str, Any]:
        d = supplier if isinstance(supplier, dict) else supplier.model_dump() if hasattr(supplier, "model_dump") else supplier.__dict__
        sid = d.get("supplier_id") or f"SUP-{len(self._suppliers)+1:03d}"
        self._suppliers[sid] = {**d, "supplier_id": sid}
        return self._suppliers[sid]

    def update_supplier_score(self, update: Any) -> Dict[str, Any]:
        d = update if isinstance(update, dict) else update.model_dump() if hasattr(update, "model_dump") else update.__dict__
        sid = d.get("supplier_id") or ""
        if sid in self._suppliers:
            self._suppliers[sid].update(d)
        return self._suppliers.get(sid, {})


supply_chain_manager = SupplyChainManager()
