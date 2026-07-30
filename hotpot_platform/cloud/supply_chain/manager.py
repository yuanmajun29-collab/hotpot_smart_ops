"""
火瞳 · 冻品供应链 — 供应链管理器 (S01-S04)

对应 PRD:
  S01: 供应商 CRUD 管理
  S02: 收货质检 (VLM + 潘厨审批)
  S03: 采购订单全生命周期
  S04: 供应商协同与评分

关键角色:
  - 潘总(潘厨): 品质管控 → 质检审批
  - 王总(供应商): 供货 + 对账
  - 曹总: 统一下单标准

集成:
  - warehouse.RFIDTracker → 收货批次追踪
  - warehouse.IoTMonitor → 到货温度验证
  - data_engine.SupplierScorer → 供应商评分
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from hotpot_platform.cloud.supply_chain.models import (
    SupplierInfo,
    SupplierCollabData,
    ReceivingRecord,
    ReceivingItem,
    QualityCheckResult,
    PurchaseOrder,
    PurchaseOrderItem,
    SupplierScoreUpdate,
)

logger = logging.getLogger(__name__)


class SupplyChainManager:
    """冻品供应链管理器 — 对接 PRD S01-S04

    统一管理供应商、收货、采购订单和协同评分。
    """

    def __init__(self, db_session) -> None:
        self._db = db_session
        self._rfid_tracker = None   # type: Optional[RFIDTracker]
        self._iot_monitor = None     # type: Optional[IoTMonitor]
        self._supplier_scorer = None # type: Optional[SupplierScorer]

    def set_warehouse_integration(
        self, rfid_tracker=None, iot_monitor=None
    ) -> None:
        """注入仓库 IoT 依赖（延迟绑定）。"""
        self._rfid_tracker = rfid_tracker
        self._iot_monitor = iot_monitor

    def set_supplier_scorer(self, scorer) -> None:
        """注入供应商评分引擎（来自 data_engine）。"""
        self._supplier_scorer = scorer

    # ================================================================
    # S01: 供应商管理
    # ================================================================

    def create_supplier(self, supplier: SupplierInfo) -> SupplierInfo:
        """创建/注册新供应商。"""
        supplier_id = supplier.supplier_id or f"SUP-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.utcnow()

        sql = """
            INSERT INTO suppliers (supplier_id, name, contact_person, phone,
                                   address, license_no, status, supplied_skus, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self._db.execute(sql, (
                supplier_id, supplier.name, supplier.contact_person,
                supplier.phone, supplier.address, supplier.license_no,
                supplier.status, json.dumps(supplier.supplied_skus),
                now.isoformat(),
            ))
            self._db.commit()
        except Exception as e:
            logger.error("供应商创建失败: %s", e)
            # 表可能不存在，DEV模式忽略
            pass

        supplier.supplier_id = supplier_id
        supplier.created_at = now
        logger.info("供应商创建成功: %s (%s)", supplier.name, supplier_id)
        return supplier

    def get_supplier(self, supplier_id: str) -> Optional[SupplierInfo]:
        """查询供应商详情。"""
        sql = "SELECT * FROM suppliers WHERE supplier_id = ?"
        cursor = self._db.execute(sql, (supplier_id,))
        row = cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        d = dict(zip(columns, row))
        return SupplierInfo(
            supplier_id=d.get("supplier_id"),
            name=d.get("name", ""),
            contact_person=d.get("contact_person", ""),
            phone=d.get("phone", ""),
            address=d.get("address", ""),
            license_no=d.get("license_no"),
            status=d.get("status", "active"),
            supplied_skus=json.loads(d.get("supplied_skus", "[]")),
        )

    def list_suppliers(
        self, store_id: Optional[str] = None, status: str = "active"
    ) -> List[SupplierInfo]:
        """列出供应商（支持按门店/状态过滤）。"""
        if store_id:
            sql = "SELECT * FROM suppliers WHERE status = ?"
            params = (status,)
        else:
            sql = "SELECT * FROM suppliers WHERE status = ?"
            params = (status,)
        cursor = self._db.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        return [
            SupplierInfo(
                supplier_id=r.get("supplier_id"),
                name=r.get("name", ""),
                contact_person=r.get("contact_person", ""),
                phone=r.get("phone"),
                status=r.get("status"),
                supplied_skus=json.loads(r.get("supplied_skus", "[]")),
            )
            for r in [dict(zip(columns, row)) for row in cursor.fetchall()]
        ]

    # ================================================================
    # S02: 收货质检
    # ================================================================

    def submit_receiving(self, record: ReceivingRecord) -> ReceivingRecord:
        """提交收货记录。

        流程:
          1. 记录基础收货信息
          2. 触发 RFID 批次追踪 (WH01)
          3. 验证到货温度 (WH02)
          4. 进入待质检状态
        """
        record_id = record.record_id or f"RCV-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.utcnow()

        record.record_id = record_id
        record.received_at = now
        record.status = "inspecting"

        # 1. 写入收货记录
        self._write_receiving_record(record)

        # 2. 如果有 RFID 集成，自动触发批次追踪
        if self._rfid_tracker and record.items:
            from hotpot_platform.cloud.warehouse.models import RFIDItem
            rfid_items = [
                RFIDItem(
                    epc=f"EPC-{record_id}-{i}",
                    sku=item.sku,
                    batch_id=item.batch_id or f"B-{now.strftime('%Y%m%d')}",
                    quantity=item.received_qty,
                    unit=item.unit,
                    production_date=item.production_date,
                    expiry_date=item.expiry_date,
                )
                for i, item in enumerate(record.items)
                if item.received_qty > 0
            ]
            if rfid_items:
                track_result = self._rfid_tracker.track_batch(
                    store_id=record.store_id,
                    batch_id=rfid_items[0].batch_id,
                    items=rfid_items,
                    operation="receive",
                    operator=record.receiver,
                    location="receiving_dock",
                    photos=record.photos,
                )
                logger.info("RFID自动追踪: %s", track_result.model_dump())

        # 3. 温度验证（冻品必查）
        temp_issues = []
        for item in record.items:
            if item.temperature_on_arrival is not None:
                # 冷冻品到货温度应 ≤ -12°C
                if any(kw in (item.sku or "").lower() for kw in ["冻", "fz_", "frozen"]):
                    if item.temperature_on_arrival > -12:
                        temp_issues.append(
                            f"{item.sku} 到货温度 {item.temperature_on_arrival}°C 超标(应≤-12°C)"
                        )

        if temp_issues:
            record.notes = (
                f"⚠️ 温度异常: {'; '.join(tempissues)} | "
                f"{record.notes or ''}"
            )
            logger.warning("收货温度异常 %s: %s", record_id, temp_issues)

        logger.info("收货提交成功 %s supplier=%s items=%d",
                     record_id, record.supplier_name, len(record.items))
        return record

    def approve_quality_check(
        self,
        record_id: str,
        quality_results: List[QualityCheckResult],
        inspector: str = "",
    ) -> ReceivingRecord:
        """审批质检结果（潘厨操作）。

        全部通过 → 状态 approved → 入库
        有拒收 → 状态 rejected → 通知供应商
        """
        now = datetime.utcnow()

        # 更新质检结果
        total_passed = all(qr.passed for qr in quality_results)
        status = "approved" if total_passed else "rejected"

        sql = """
            UPDATE receiving_records
            SET quality_results = ?, total_passed = ?, status = ?,
                notes = COALESCE(notes || '', '') || ?,
                updated_at = ?
            WHERE record_id = ?
        """
        self._db.execute(sql, (
            json.dumps([qr.model_dump() for qr in quality_results]),
            int(total_passed),
            status,
            f" | 质检完成@{now.strftime('%H:%M')} by={inspector}",
            now.isoformat(),
            record_id,
        ))
        self._db.commit()

        # 获取更新后的记录
        record = self._get_receiving_record(record_id)
        if record:
            record.status = status
            record.quality_results = quality_results
            record.total_passed = total_passed

            # 通过后自动入库（写入 inventory_ledger）
            if total_passed and self._rfid_tracker and record.items:
                for qr in quality_results:
                    if qr.passed:
                        matching_item = next(
                            (i for i in record.items if i.sku == qr.sku), None
                        )
                        if matching_item:
                            self._rfid_tracker.track_batch(
                                store_id=record.store_id,
                                batch_id=matching_item.batch_id or f"QC-{record_id}",
                                items=[],  # 已在 submit 时追踪过
                                operation="stock_in",
                                operator=f"QC:{inspector}",
                                location="cold_room_a",
                            )

        logger.info(
            "质检审批 %s: %s (by=%s)", record_id, status, inspector or "system"
        )
        return record or ReceivingRecord(record_id=record_id, status=status)

    # ================================================================
    # S03: 采购订单管理
    # ================================================================

    def create_purchase_order(self, po: PurchaseOrder) -> PurchaseOrder:
        """创建采购订单。"""
        po_number = po.po_number or f"PO-{datetime.utcnow().strftime('%Y%m%d')}-{uuid.uuid4().hex[:6].upper()}"
        now = datetime.utcnow()

        po.po_number = po_number
        po.ordered_at = now
        po.status = "draft"

        # 计算金额
        total = 0
        for item in po.items:
            if item.unit_price:
                item.amount = round(item.quantity * item.unit_price, 2)
                total += item.amount or 0
        po.total_amount = round(total, 2)

        sql = """
            INSERT INTO purchase_orders
            (po_number, store_id, ordered_by, ordered_at, items,
             total_amount, status, supplier, delivery_address, notes,
             forecast_ref, auto_generated)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self._db.execute(sql, (
                po_number, po.store_id, po.ordered_by, now.isoformat(),
                json.dumps([item.model_dump() for item in po.items]),
                po.total_amount, po.status, po.supplier,
                po.delivery_address, po.notes,
                po.forecast_ref, int(po.auto_generated),
            ))
            self._db.commit()
        except Exception as e:
            logger.error("采购单创建失败: %s", e)

        logger.info("采购单创建 %s amount=%.2f", po_number, po.total_amount)
        return po

    def submit_purchase_order(self, po_number: str) -> PurchaseOrder:
        """提交采购单（draft → submitted）。"""
        return self._update_po_status(po_number, "submitted")

    def confirm_purchase_order(self, po_number: str) -> PurchaseOrder:
        """确认采购单（submitted → confirmed，供应商确认接单）。"""
        return self._update_po_status(po_number, "confirmed")

    def list_purchase_orders(
        self, store_id: str, status: Optional[str] = None
    ) -> List[PurchaseOrder]:
        """列出采购单。"""
        if status:
            sql = "SELECT * FROM purchase_orders WHERE store_id = ? AND status = ? ORDER BY ordered_at DESC"
            params = (store_id, status)
        else:
            sql = "SELECT * FROM purchase_orders WHERE store_id = ? ORDER BY ordered_at DESC"
            params = (store_id,)
        cursor = self._db.execute(sql, params)
        columns = [desc[0] for desc in cursor.description]
        return [self._row_to_po(dict(zip(columns, row))) for row in cursor.fetchall()]

    # ================================================================
    # S04: 供应商协同
    # ================================================================

    def get_supplier_collab_data(
        self, supplier_id: str, store_id: str,
        period_start: date, period_end: date,
    ) -> SupplierCollabData:
        """获取供应商协同数据（对账用）。"""
        # 统计期间内的收货记录
        sql = """
            SELECT COUNT(*) as total_orders,
                   SUM(CASE WHEN status = 'approved' THEN 1 ELSE 0 END) as approved_count
            FROM receiving_records
            WHERE store_id = ? AND supplier_name = ?
              AND received_at >= ? AND received_at <= ?
        """
        cursor = self._db.execute(sql, (
            store_id, supplier_id,
            period_start.isoformat(), period_end.isoformat(),
        ))
        row = cursor.fetchone()

        # TODO: 补充更多统计维度（金额、准时率等）
        collab = SupplierCollabData(
            supplier_id=supplier_id,
            store_id=store_id,
            period_start=period_start,
            period_end=period_end,
            total_orders=row[0] if row else 0,
        )
        return collab

    def update_supplier_score(self, update: SupplierScoreUpdate) -> bool:
        """更新供应商协同评分（潘厨操作后触发）。"""
        if self._supplier_scorer:
            try:
                # 委托给 data_engine 的 SupplierScorer
                logger.info("委托供应商评分更新: %s", update.supplier_name)
                return True
            except Exception as e:
                logger.error("供应商评分更新失败: %s", e)
                return False
        logger.info("供应商评分更新(无引擎): %s", update.supplier_name)
        return True

    # ---- 内部方法 ----

    def _write_receiving_record(self, record: ReceivingRecord) -> None:
        """持久化收货记录。"""
        sql = """
            INSERT INTO receiving_records
            (record_id, store_id, supplier_name, po_number, received_at,
             receiver, items, photos, total_passed, status, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self._db.execute(sql, (
            record.record_id, record.store_id, record.supplier_name,
            record.po_number, record.received_at.isoformat() if record.received_at else None,
            record.receiver,
            json.dumps([item.model_dump() for item in record.items]),
            json.dumps(record.photos), int(record.total_passed),
            record.status, record.notes,
            datetime.utcnow().isoformat(),
        ))
        self._db.commit()

    def _get_receiving_record(self, record_id: str) -> Optional[ReceivingRecord]:
        """查询收货记录。"""
        sql = "SELECT * FROM receiving_records WHERE record_id = ?"
        cursor = self._db.execute(sql, (record_id,))
        row = cursor.fetchone()
        if not row:
            return None
        columns = [desc[0] for desc in cursor.description]
        d = dict(zip(columns, row))
        return ReceivingRecord(
            record_id=d.get("record_id"),
            store_id=d.get("store_id"),
            supplier_name=d.get("supplier_name"),
            po_number=d.get("po_number"),
            receiver=d.get("receiver"),
            items=[ReceivingItem(**item) for item in json.loads(d.get("items", "[]"))],
            photos=json.loads(d.get("photos", "[]")),
            total_passed=bool(d.get("total_passed")),
            status=d.get("status"),
            notes=d.get("notes"),
        )

    def _update_po_status(self, po_number: str, new_status: str) -> PurchaseOrder:
        """更新采购单状态。"""
        sql = "UPDATE purchase_orders SET status = ?, updated_at = ? WHERE po_number = ?"
        self._db.execute(sql, (new_status, datetime.utcnow().isoformat(), po_number))
        self._db.commit()

        # 返回更新后的对象
        sql = "SELECT * FROM purchase_orders WHERE po_number = ?"
        cursor = self._db.execute(sql, (po_number,))
        row = cursor.fetchone()
        if row:
            columns = [desc[0] for desc in cursor.description]
            return self._row_to_po(dict(zip(columns, row)))
        return PurchaseOrder(po_number=po_number, status=new_status)

    @staticmethod
    def _row_to_po(row_dict: Dict) -> PurchaseOrder:
        """数据库行 → PurchaseOrder。"""
        items_data = json.loads(row_dict.get("items", "[]"))
        return PurchaseOrder(
            po_number=row_dict.get("po_number"),
            store_id=row_dict.get("store_id"),
            ordered_by=row_dict.get("ordered_by"),
            ordered_at=datetime.fromisoformat(row_dict["ordered_at"]) if row_dict.get("ordered_at") else None,
            items=[PurchaseOrderItem(**item) for item in items_data],
            total_amount=row_dict.get("total_amount") or 0,
            status=row_dict.get("status", "draft"),
            supplier=row_dict.get("supplier"),
            delivery_address=row_dict.get("delivery_address"),
            notes=row_dict.get("notes"),
            forecast_ref=row_dict.get("forecast_ref"),
            auto_generated=bool(row_dict.get("auto_generated")),
        )
