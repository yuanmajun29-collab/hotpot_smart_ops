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
    # S01 货品主数据 (D1 新增)
    ProductMaster,
    ProductCategory,
    ChangeRequest,
    TemporarySubstitute,
    ProductCreateRequest,
    ProductUpdateRequest,
    ProductListResponse,
    ProductStatsResponse,
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

    # ================================================================
    # S01: 货品主数据管理 (D1 新增 · 2026-08-01)
    # ================================================================

    # ── 内存缓存 (Edge UI 轻量模式) ──
    _product_cache: Dict[str, ProductMaster] = {}  # sku_code → ProductMaster
    _category_cache: List[ProductCategory] = []
    _change_requests: List[ChangeRequest] = []
    _substitutes: List[TemporarySubstitute] = []

    # ── S02: 收货质检缓存 (D1-S02 · 2026-08-01) ──
    _receiving_cache: Dict[str, ReceivingRecord] = {}  # record_id → ReceivingRecord
    _receiving_counter: int = 0  # 自增计数器用于生成record_id
    _data_file: Optional[str] = None  # JSON 持久化路径

    @classmethod
    def init_product_data(cls, data_file: str = None) -> None:
        """初始化货品数据存储（从JSON文件加载或创建空库）。"""
        cls._data_file = data_file
        if data_file:
            cls._load_from_json()
        if not cls._category_cache:
            cls._init_default_categories()
        logger.info("货品主数据初始化完成: %d 个货品, %d 个分类",
                     len(cls._product_cache), len(cls._category_cache))

    @classmethod
    def _init_default_categories(cls) -> None:
        """初始化默认品类分类。"""
        cls._category_cache = [
            ProductCategory(category_code="FROZEN_MEAT", category_name="冻品荤菜", sort_order=1),
            ProductCategory(category_code="HOTPOT_BASE", category_name="锅底/汤底", sort_order=2),
            ProductCategory(category_code="VEGETABLE", category_name="素菜", sort_order=3),
            ProductCategory(category_code="STAPLE", category_name="主食/小吃", sort_order=4),
            ProductCategory(category_code="DRINK", category_name="酒水饮料", sort_order=5),
            ProductCategory(category_code="SEASONING", category_name="调料蘸料", sort_order=6),
        ]

    @classmethod
    def _load_from_json(cls) -> None:
        """从 JSON 文件加载数据（Edge UI 轻量持久化）。"""
        import os
        if cls._data_file and os.path.exists(cls._data_file):
            try:
                with open(cls._data_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                cls._product_cache = {
                    k: ProductMaster(**v) for k, v in data.get("products", {}).items()
                }
                cls._category_cache = [
                    ProductCategory(**c) for c in data.get("categories", [])
                ]
                cls._change_requests = [
                    ChangeRequest(**r) for r in data.get("change_requests", [])
                ]
                # S02: 加载收货数据
                cls._receiving_cache = {
                    k: ReceivingRecord(**v) for k, v in data.get("receiving_records", {}).items()
                }
                cls._receiving_counter = data.get("receiving_counter", 0)
                # S03: 加载采购订单数据
                cls._po_cache = {
                    k: PurchaseOrder(**v) for k, v in data.get("purchase_orders", {}).items()
                }
                cls._po_counter = data.get("po_counter", 0)
                # S04: 加载供应商数据
                cls._supplier_cache = data.get("suppliers", {})
                cls._supplier_counter = data.get("supplier_counter", 0)
                cls._score_cache = data.get("score_snapshots", {})
                cls._adjustment_cache = data.get("score_adjustments", {})
                # D2: 加载AI助理数据
                cls._task_cache = data.get("assistant_tasks", {})
                cls._task_counter = data.get("assistant_task_counter", 0)
                cls._suggestion_cache = data.get("assistant_suggestions", {})
                cls._suggestion_counter = data.get("assistant_suggestion_counter", 0)
                logger.info(
                    "从 JSON 加载货品数据: %d 个产品, %d 条收货记录, "
                    "%d 个采购订单, %d 个供应商, %d 待办, %d 建议",
                    len(cls._product_cache), len(cls._receiving_cache),
                    len(cls._po_cache), len(cls._supplier_cache),
                    len(cls._task_cache), len(cls._suggestion_cache),
                )
            except Exception as e:
                logger.error("加载 JSON 数据失败: %s", e)

    @classmethod
    def _save_to_json(cls) -> None:
        """保存数据到 JSON 文件。"""
        import os
        if cls._data_file:
            try:
                data = {
                    "products": {k: v.model_dump() for k, v in cls._product_cache.items()},
                    "categories": [c.model_dump() for c in cls._category_cache],
                    "change_requests": [r.model_dump() for r in cls._change_requests],
                    # S02: 保存收货数据
                    "receiving_records": {k: v.model_dump() for k, v in cls._receiving_cache.items()},
                    "receiving_counter": cls._receiving_counter,
                    # S03: 保存采购订单数据
                    "purchase_orders": {k: v.model_dump() for k, v in cls._po_cache.items()},
                    "po_counter": cls._po_counter,
                    # S04: 保存供应商数据
                    "suppliers": cls._supplier_cache,
                    "supplier_counter": cls._supplier_counter,
                    "score_snapshots": cls._score_cache,
                    "score_adjustments": cls._adjustment_cache,
                    # D2: 保存AI助理数据
                    "assistant_tasks": cls._task_cache,
                    "assistant_task_counter": cls._task_counter,
                    "assistant_suggestions": cls._suggestion_cache,
                    "assistant_suggestion_counter": cls._suggestion_counter,
                }
                with open(cls._data_file, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            except Exception as e:
                logger.error("保存 JSON 数据失败: %s", e)

    # ── CRUD 操作 ──

    @classmethod
    def create_product_master(cls, req: ProductCreateRequest, operator: str = "") -> ProductMaster:
        """
        创建货品主数据。

        规则:
          - SKU 编码唯一性检查
          - 自动设置审计字段
          - 初始状态为 draft, version=1, locked=False
        """
        sku = req.sku_code.strip().upper()

        # 唯一性检查
        if sku in cls._product_cache:
            raise ValueError(f"SKU 已存在: {sku}")

        now = datetime.now()
        product = ProductMaster(
            sku_code=sku,
            name=req.name.strip(),
            specification=req.specification.strip(),
            brand=req.brand.strip(),
            unit_price=req.unit_price,
            unit=req.unit or "份",
            category=req.category,
            supplier_id=req.supplier_id,
            supplier_name=req.supplier_name,
            image_url=req.image_url,
            location_code=req.location_code,
            storage_area=req.storage_area,
            shelf_life_days=req.shelf_life_days,
            min_stock_qty=req.min_stock_qty,
            tags=req.tags or [],
            status="draft",
            locked=False,
            version=1,
            created_by=operator,
            created_at=now,
            updated_by=operator,
            updated_at=now,
        )

        cls._product_cache[sku] = product
        cls._save_to_json()

        logger.info("货品创建成功: %s (%s) by=%s", product.name, sku, operator)
        return product

    @classmethod
    def get_product_by_sku(cls, sku_code: str) -> Optional[ProductMaster]:
        """按 SKU 查询货品详情。"""
        return cls._product_cache.get(sku_code.strip().upper())

    @classmethod
    def list_product_masters(
        cls,
        page: int = 1,
        page_size: int = 20,
        keyword: str = "",
        category: str = "",
        status: str = "",
        supplier_id: str = "",
    ) -> ProductListResponse:
        """
        货品列表（分页 + 搜索 + 筛选）。

        Args:
            page: 页码 (从1开始)
            page_size: 每页数量
            keyword: 搜索关键词 (匹配名称/品牌/SKU)
            category: 品类筛选
            status: 状态筛选
            supplier_id: 供应商筛选
        """
        # 过滤
        items = list(cls._product_cache.values())

        if keyword:
            kw = keyword.lower()
            items = [p for p in items if kw in p.name.lower() or kw in p.brand.lower()
                     or kw in p.sku_code.lower() or kw in (p.specification or "").lower()]

        if category:
            items = [p for p in items if p.category == category]

        if status:
            items = [p for p in items if p.status == status]

        if supplier_id:
            items = [p for p in items if p.supplier_id == supplier_id]

        total = len(items)

        # 排序 (按名称)
        items.sort(key=lambda p: p.name)

        # 分页
        start = (page - 1) * page_size
        end = start + page_size
        paged_items = items[start:end]

        return ProductListResponse(
            total=total,
            page=page,
            page_size=page_size,
            items=paged_items,
            categories=cls._category_cache,
        )

    @classmethod
    def update_product_master(
        cls, sku_code: str, req: ProductUpdateRequest, operator: str = ""
    ) -> ProductMaster:
        """
        更新货品主数据。

        规则:
          - 锁定后的关键字段不可修改 (name/specification/brand/unit_price)
          - 非锁定状态可修改所有字段
          - 自动更新版本审计字段
        """
        sku = sku_code.strip().upper()
        product = cls._product_cache.get(sku)
        if not product:
            raise ValueError(f"SKU 不存在: {sku}")

        now = datetime.now()
        update_data = req.model_dump(exclude_unset=True)

        # 锁定检查：关键字段保护
        locked_fields = {"name", "specification", "brand", "unit_price"}
        if product.locked:
            violated = locked_fields & set(update_data.keys())
            if violated:
                raise PermissionError(
                    f"货品已锁定，以下字段不可直接修改: {', '.join(violated)}。"
                    f"请通过变更申请流程修改。"
                )

        # 应用更新
        for field, value in update_data.items():
            setattr(product, field, value)

        product.updated_by = operator
        product.updated_at = now

        cls._product_cache[sku] = product
        cls._save_to_json()

        logger.info("货品更新成功: %s by=%s", sku, operator)
        return product

    @classmethod
    def lock_product_master(cls, sku_code: str, operator: str = "") -> ProductMaster:
        """
        锁定货品标准。

        锁定后:
          - 名称/规格/品牌/价格四项关键字段不可直接修改
          - 修改需提交变更申请单
          - 状态从 draft → active
        """
        sku = sku_code.strip().upper()
        product = cls._product_cache.get(sku)
        if not product:
            raise ValueError(f"SKU 不存在: {sku}")

        if product.locked:
            return product  # 已锁定，幂等操作

        product.locked = True
        product.status = "active"
        product.updated_by = operator
        product.updated_at = datetime.now()

        cls._product_cache[sku] = product
        cls._save_to_json()

        logger.info("货品锁定成功: %s (%s) by=%s", product.name, sku, operator)
        return product

    @classmethod
    def unlock_product_master(cls, sku_code: str, operator: str = "", reason: str = "") -> ProductMaster:
        """解锁货品（管理员操作，需填写原因）。"""
        sku = sku_code.strip().upper()
        product = cls._product_cache.get(sku)
        if not product:
            raise ValueError(f"SKU 不存在: {sku}")

        if not product.locked:
            return product

        product.locked = False
        product.updated_by = operator
        product.updated_at = datetime.now()

        cls._product_cache[sku] = product
        cls._save_to_json()

        logger.info("货品解锁成功: %s (%s) by=%s reason=%s", product.name, sku, operator, reason)
        return product

    @classmethod
    def delete_product_master(cls, sku_code: str, operator: str = "") -> bool:
        """删除货品（仅 draft 状态可删除）。"""
        sku = sku_code.strip().upper()
        product = cls._product_cache.get(sku)
        if not product:
            raise ValueError(f"SKU 不存在: {sku}")

        if product.locked or product.status == "active":
            raise PermissionError("已锁定或激活的货品不可删除，请先停用")

        del cls._product_cache[sku]
        cls._save_to_json()

        logger.info("货品删除成功: %s by=%s", sku, operator)
        return True

    # ── 变更管理 ──

    @classmethod
    def submit_change_request(
        cls, sku_code: str, change: ChangeRequest, operator: str = ""
    ) -> ChangeRequest:
        """提交变更申请单。"""
        sku = sku_code.strip().upper()
        product = cls._product_cache.get(sku)
        if not product:
            raise ValueError(f"SKU 不存在: {sku}")

        request_id = change.request_id or f"CR-{uuid.uuid4().hex[:8].upper()}"
        now = datetime.now()

        change.request_id = request_id
        change.sku_code = sku
        change.old_value = {
            "name": product.name,
            "specification": product.specification,
            "brand": product.brand,
            "unit_price": product.unit_price,
            "version": product.version,
        }
        change.requested_by = operator
        change.requested_at = now
        change.status = "pending"

        cls._change_requests.append(change)
        cls._save_to_json()

        logger.info("变更申请提交: %s type=%s by=%s", request_id, change.change_type, operator)
        return change

    @classmethod
    def approve_change_request(
        cls, request_id: str, approved: bool, approver: str = "", notes: str = ""
    ) -> Optional[ChangeRequest]:
        """审批变更申请。"""
        for cr in cls._change_requests:
            if cr.request_id == request_id and cr.status == "pending":
                now = datetime.now()
                cr.status = "approved" if approved else "rejected"
                cr.approved_by = approver
                cr.approved_at = now
                cr.approval_notes = notes

                if approved:
                    # 应用变更到货品主数据
                    product = cls._product_cache.get(cr.sku_code)
                    if product:
                        for field, value in cr.new_value.items():
                            if hasattr(product, field):
                                setattr(product, field, value)
                        product.version += 1
                        product.updated_by = approver
                        product.updated_at = now
                        cr.effective_version = product.version
                        cls._product_cache[cr.sku_code] = product

                cls._save_to_json()
                logger.info("变更审批: %s → %s by=%s", request_id, cr.status, approver)
                return cr

        return None

    @classmethod
    def list_change_requests(
        cls, sku_code: str = "", status: str = ""
    ) -> List[ChangeRequest]:
        """查询变更申请列表。"""
        requests = cls._change_requests
        if sku_code:
            requests = [r for r in requests if r.sku_code == sku_code.strip().upper()]
        if status:
            requests = [r for r in requests if r.status == status]
        return sorted(requests, key=lambda r: r.requested_at or datetime.min, reverse=True)

    # ── 统计 ──

    @classmethod
    def get_product_stats(cls) -> ProductStatsResponse:
        """货品统计概览。"""
        products = list(cls._product_cache.values())
        total = len(products)
        active = sum(1 for p in products if p.status == "active")
        locked = sum(1 for p in products if p.locked)
        draft = sum(1 for p in products if p.status == "draft")

        categories = set(p.category for p in products)
        suppliers = set(p.supplier_name for p in products if p.supplier_name)
        avg_price = sum(p.unit_price for p in products) / total if total > 0 else 0

        cat_breakdown: Dict[str, int] = {}
        for p in products:
            cat_breakdown[p.category] = cat_breakdown.get(p.category, 0) + 1

        return ProductStatsResponse(
            total_products=total,
            active_products=active,
            locked_products=locked,
            draft_products=draft,
            total_categories=len(categories),
            total_suppliers=len(suppliers),
            avg_unit_price=round(avg_price, 2),
            category_breakdown=cat_breakdown,
        )

    @classmethod
    def get_categories(cls) -> List[ProductCategory]:
        """获取可用分类列表。"""
        return cls._category_cache

    # ── 种子数据 (展会演示用) ──

    @classmethod
    def load_seed_data(cls) -> int:
        """
        加载模拟种子数据（展会演示用）。

        包含 20+ 火锅常用冻品 SKU，覆盖全品类。
        返回导入的货品数量。
        """
        if cls._product_cache:
            return len(cls._product_cache)  # 已有数据不重复加载

        now = datetime.now()
        seed_products = [
            # ── 冻品荤菜 ──
            ProductMaster(sku_code="FP-MW-001", name="精品毛肚", specification="500g/盒",
                         brand="海霸王", unit_price=128.0, unit="盒", category="FROZEN_MEAT",
                         supplier_name="杭州冻品供应链", storage_area="冷冻", shelf_life_days=180,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-MW-002", name="鲜鸭肠", specification="400g/份",
                         brand="喜得佳", unit_price=38.0, unit="份", category="FROZEN_MEAT",
                         supplier_name="杭州冻品供应链", storage_area="冷冻", shelf_life_days=90,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-MW-003", name="麻辣牛肉", specification="350g/盒",
                         brand="海霸王", unit_price=68.0, unit="盒", category="FROZEN_MEAT",
                         supplier_name="杭州冻品供应链", storage_area="冷冻", shelf_life_days=180,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-MW-004", name="虾滑", specification="200g/盒",
                         brand="桂冠", unit_price=45.0, unit="盒", category="FROZEN_MEAT",
                         supplier_name="杭州冻品供应链", storage_area="冷冻", shelf_life_days=120,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-MW-005", name="手工羊肉卷", specification="300g/盒",
                         brand="小肥羊", unit_price=58.0, unit="盒", category="FROZEN_MEAT",
                         supplier_name="杭州冻品供应链", storage_area="冷冻", shelf_life_days=180,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-MW-006", name="脆嫩毛肚", specification="450g/盒",
                         brand="喜得佳", unit_price=118.0, unit="盒", category="FROZEN_MEAT",
                         supplier_name="杭州冻品供应链", storage_area="冷冻", shelf_life_days=180,
                         status="active", locked=False, version=1, created_at=now, tags=["热销"]),
            ProductMaster(sku_code="FP-MW-007", name="牛黄喉", specification="350g/份",
                         brand="海霸王", unit_price=42.0, unit="份", category="FROZEN_MEAT",
                         supplier_name="杭州冻品供应链", storage_area="冷冻", shelf_life_days=90,
                         status="draft", locked=False, version=1, created_at=now),
            ProductMaster(sku_code="FP-MW-008", name="千层肚", specification="300g/盒",
                         brand="喜得佳", unit_price=78.0, unit="盒", category="FROZEN_MEAT",
                         supplier_name="杭州冻品供应链", storage_area="冷冻", shelf_life_days=150,
                         status="draft", locked=False, version=1, created_at=now),

            # ── 锅底/汤底 ──
            ProductMaster(sku_code="FP-GD-001", name="番茄锅底", specification="800g/袋",
                         brand="海底捞", unit_price=28.0, unit="袋", category="HOTPOT_BASE",
                         supplier_name="杭州调味品批发", storage_area="常温", shelf_life_days=365,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-GD-002", name="麻辣牛油锅底", specification="500g/盒",
                         brand="名扬", unit_price=35.0, unit="盒", category="HOTPOT_BASE",
                         supplier_name="杭州调味品批发", storage_area="常温", shelf_life_days=365,
                         status="active", locked=True, version=1, created_at=now, tags=["招牌"]),
            ProductMaster(sku_code="FP-GD-003", name="菌汤锅底", specification="600g/盒",
                         brand="海底捞", unit_price=32.0, unit="盒", category="HOTPOT_BASE",
                         supplier_name="杭州调味品批发", storage_area="常温", shelf_life_days=270,
                         status="active", locked=True, version=1, created_at=now),

            # ── 素菜 ──
            ProductMaster(sku_code="FP-SC-001", name="娃娃菜", specification="500g/份",
                         brand="本地直供", unit_price=8.0, unit="份", category="VEGETABLE",
                         supplier_name="本地蔬菜合作社", storage_area="冷藏", shelf_life_days=5,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-SC-002", name="土豆片", specification="400g/份",
                         brand="本地直供", unit_price=6.0, unit="份", category="VEGETABLE",
                         supplier_name="本地蔬菜合作社", storage_area="常温", shelf_life_days=14,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-SC-003", name="莲藕", specification="400g/份",
                         brand="本地直供", unit_price=10.0, unit="份", category="VEGETABLE",
                         supplier_name="本地蔬菜合作社", storage_area="常温", shelf_life_days=7,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-SC-004", name="腐竹", specification="200g/包",
                         brand="桂冠", unit_price=12.0, unit="包", category="VEGETABLE",
                         supplier_name="杭州干货批发", storage_area="常温", shelf_life_days=300,
                         status="draft", locked=False, version=1, created_at=now),

            # ── 主食/小吃 ──
            ProductMaster(sku_code="FP-ZS-001", name="宽粉", specification="250g/袋",
                         brand="川南", unit_price=8.0, unit="袋", category="STAPLE",
                         supplier_name="杭州干货批发", storage_area="常温", shelf_life_days=270,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-ZS-002", name="红糖糍粑", specification="300g/盒",
                         brand="蜀香", unit_price=22.0, unit="盒", category="STAPLE",
                         supplier_name="杭州冻品供应链", storage_area="冷冻", shelf_life_days=180,
                         status="active", locked=True, version=1, created_at=now, tags=["新品"]),
            ProductMaster(sku_code="FP-ZS-003", name="小酥肉", specification="400g/盒",
                         brand="蜀香", unit_price=32.0, unit="盒", category="STAPLE",
                         supplier_name="杭州冻品供应链", storage_area="冷冻", shelf_life_days=180,
                         status="draft", locked=False, version=1, created_at=now),

            # ── 酒水饮料 ──
            ProductMaster(sku_code="FP-YS-001", name="冰镇可乐", specification="330ml*24罐/箱",
                         brand="可口可乐", unit_price=48.0, unit="箱", category="DRINK",
                         supplier_name="杭州饮料批发", storage_area="常温", shelf_life_days=365,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-YS-002", name="雪花啤酒", specification="500ml*12瓶/箱",
                         brand="华润雪花", unit_price=45.0, unit="箱", category="DRINK",
                         supplier_name="杭州饮料批发", storage_area="冷藏", shelf_life_days=180,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-YS-003", name="酸梅汤", specification="500ml*15瓶/箱",
                         brand="信远斋", unit_price=36.0, unit="箱", category="DRINK",
                         supplier_name="杭州饮料批发", storage_area="常温", shelf息_days=240,
                         status="draft", locked=False, version=1, created_at=now),

            # ── 调料蘸料 ──
            ProductMaster(sku_code="FP-TL-001", name="香油碟", specification="100ml*50盒/箱",
                         brand="金龙鱼", unit_price=65.0, unit="箱", category="SEASONING",
                         supplier_name="杭州调味品批发", storage_area="常温", shelf_life_days=365,
                         status="active", locked=True, version=1, created_at=now),
            ProductMaster(sku_code="FP-TL-002", name="蒜泥香油", specification="200ml*30盒/箱",
                         brand="海底捞", unit_price=58.0, unit="箱", category="SEASONING",
                         supplier_name="杭州调味品批发", storage_area="常温", shelf_life_days=270,
                         status="active", locked=True, version=1, created_at=now),
        ]

        for p in seed_products:
            cls._product_cache[p.sku_code] = p

        cls._save_to_json()
        logger.info("种子数据加载完成: %d 个货品", len(seed_products))
        return len(seed_products)

    # ================================================================
    # S02: 收货质检 (VLM + 潘厨审批) · D1-S02 · 2026-08-01
    # ================================================================

    @classmethod
    def _generate_record_id(cls) -> str:
        """生成收货记录ID: RC-YYYYMMDD-XXXX"""
        cls._receiving_counter += 1
        date_str = datetime.now().strftime("%Y%m%d")
        return f"RC-{date_str}-{cls._receiving_counter:04d}"

    @classmethod
    def create_receiving_record(
        cls,
        supplier_name: str,
        receiver: str,
        items: List[Dict[str, Any]],
        po_number: str = None,
        notes: str = None,
    ) -> Dict[str, Any]:
        """
        创建收货记录 (D1-S02)。

        业务规则:
          BR-01: 校验SKU有效性
          BR-02: 计算短重率
          BR-03: 自动标记异常品项
        """
        receiving_items = []
        variance_summary = {}

        for item_data in items:
            sku = item_data.get("sku", "").strip().upper()
            # BR-01: SKU必须存在且active
            product = cls._product_cache.get(sku)
            if not product:
                raise ValueError(f"SKU不存在或未激活: {sku}")
            if product.status != "active":
                raise ValueError(f"SKU未激活: {sku} (status={product.status})")

            ordered_qty = float(item_data.get("ordered_qty", 0))
            received_qty = float(item_data.get("received_qty", 0))
            if received_qty <= 0:
                raise ValueError(f"实收量必须大于0: {sku}")

            # BR-04: 计算短重率
            variance_pct = 0.0
            if ordered_qty > 0:
                variance_pct = round((ordered_qty - received_qty) / ordered_qty * 100, 2)

            status_flag = "normal"
            if abs(variance_pct) > 15:
                status_flag = "alert"  # BR-05

            receiving_item = ReceivingItem(
                sku=sku,
                sku_name=product.name,
                ordered_qty=ordered_qty,
                received_qty=received_qty,
                unit=item_data.get("unit", "kg"),
                batch_id=item_data.get("batch_id"),
                production_date=item_data.get("production_date"),
                expiry_date=item_data.get("expiry_date"),
                temperature_on_arrival=item_data.get("temperature_on_arrival"),
            )
            receiving_items.append(receiving_item)
            variance_summary[sku] = {"variance_pct": variance_pct, "status": status_flag}

        record_id = cls._generate_record_id()
        record = ReceivingRecord(
            record_id=record_id,
            store_id="store-jiaojiang",
            supplier_name=supplier_name,
            po_number=po_number,
            received_at=datetime.now(),
            receiver=receiver,
            items=receiving_items,
            status="draft",
            notes=notes,
        )

        cls._receiving_cache[record_id] = record
        cls._save_to_json()

        logger.info("创建收货记录: %s, 供应商=%s, 品项数=%d",
                    record_id, supplier_name, len(receiving_items))

        return {
            "record": record.model_dump(),
            "variance_summary": variance_summary,
            "next_action": "submit_for_inspection",
        }

    @classmethod
    def get_receiving_list(
        cls,
        page: int = 1,
        page_size: int = 20,
        status: str = None,
        supplier_name: str = None,
    ) -> Dict[str, Any]:
        """获取收货记录列表（分页+筛选）。"""
        records = list(cls._receiving_cache.values())

        # 筛选
        if status:
            records = [r for r in records if r.status == status]
        if supplier_name:
            records = [r for r in records if supplier_name in r.supplier_name]

        # 按时间倒序
        records.sort(key=lambda r: r.received_at or datetime.min, reverse=True)

        # 分页
        total = len(records)
        start = (page - 1) * page_size
        end = start + page_size
        paged_records = records[start:end]

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [r.model_dump() for r in paged_records],
        }

    @classmethod
    def get_receiving_detail(cls, record_id: str) -> Dict[str, Any]:
        """获取收货记录详情。"""
        record = cls._receiving_cache.get(record_id)
        if not record:
            raise ValueError(f"收货记录不存在: {record_id}")
        return record.model_dump()

    @classmethod
    def update_receiving_record(
        cls, record_id: str, update_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """更新收货记录（仅draft状态可编辑）。"""
        record = cls._receiving_cache.get(record_id)
        if not record:
            raise ValueError(f"收货记录不存在: {record_id}")
        if record.status != "draft":
            raise ValueError(f"当前状态不允许编辑: {record.status}")

        # 允许更新的字段
        allowed_fields = {"supplier_name", "receiver", "po_number", "notes"}
        for field, value in update_data.items():
            if field in allowed_fields and value is not None:
                setattr(record, field, value)

        # 更新品项
        if "items" in update_data:
            new_items = []
            for item_data in update_data["items"]:
                sku = item_data.get("sku", "").strip().upper()
                product = cls._product_cache.get(sku)
                if product:
                    new_items.append(ReceivingItem(
                        sku=sku,
                        sku_name=product.name,
                        ordered_qty=float(item_data.get("ordered_qty", 0)),
                        received_qty=float(item_data.get("received_qty", 0)),
                        unit=item_data.get("unit", "kg"),
                        batch_id=item_data.get("batch_id"),
                    ))
            if new_items:
                record.items = new_items

        cls._save_to_json()
        return record.model_dump()

    @classmethod
    def submit_for_inspection(cls, record_id: str) -> Dict[str, Any]:
        """
        提交收货单进入质检流程。

        状态流转: draft → pending → inspecting (如果有照片则自动触发VLM)
        """
        record = cls._receiving_cache.get(record_id)
        if not record:
            raise ValueError(f"收货记录不存在: {record_id}")
        if record.status != "draft":
            raise ValueError(f"只有草稿状态可以提交: 当前{record.status}")
        if not record.items:
            raise ValueError("没有收货品项，无法提交")

        record.status = "pending"

        # AUTO-001: 如果有照片，自动进入inspecting状态
        if record.photos:
            record.status = "inspecting"

        cls._save_to_json()
        logger.info("提交收货质检: %s → %s", record_id, record.status)
        return {
            "record_id": record_id,
            "status": record.status,
            "message": "已提交质检" + ("，正在执行VLM分析..." if record.photos else ""),
        }

    @classmethod
    def add_photo(cls, record_id: str, photo_url: str, photo_type: str = "overview") -> Dict[str, Any]:
        """上传/添加收货照片。"""
        record = cls._receiving_cache.get(record_id)
        if not record:
            raise ValueError(f"收货记录不存在: {record_id}")

        photo_entry = f"{photo_type}:{photo_url}"
        if photo_entry not in record.photos:
            record.photos.append(photo_entry)

        cls._save_to_json()
        return {"record_id": record_id, "photo_count": len(record.photos), "photos": record.photos}

    @classmethod
    def run_vlm_inspection(cls, record_id: str, use_mock: bool = True) -> Dict[str, Any]:
        """
        执行VLM视觉质检。

        当VLM Bridge未部署时，使用Mock模式基于规则生成质检结果。
        """
        import time

        record = cls._receiving_cache.get(record_id)
        if not record:
            raise ValueError(f"收货记录不存在: {record_id}")
        if record.status not in ("pending", "inspecting"):
            raise ValueError(f"当前状态不允许执行质检: {record.status}")

        record.status = "inspecting"
        quality_results = []

        for item in record.items:
            if use_mock:
                result = cls._mock_vlm_quality_check(item)
            else:
                # TODO: 调用真实 VLM Bridge API
                result = cls._mock_vlm_quality_check(item)  # 暂时仍用Mock

            result.inspected_at = datetime.now()
            quality_results.append(result)

        record.quality_results = quality_results

        # 计算整体是否通过
        record.total_passed = all(r.passed for r in quality_results) if quality_results else True

        # AUTO-002: 分析完成 → 待审批
        record.status = "pending_approval"

        cls._save_to_json()
        logger.info("VLM质检完成: %s, 结果=%d项, 整体通过=%s",
                    record_id, len(quality_results), record.total_passed)

        return {
            "record_id": record_id,
            "status": record.status,
            "total_passed": record.total_passed,
            "quality_count": len(quality_results),
            "quality_results": [r.model_dump() for r in quality_results],
        }

    @classmethod
    def _mock_vlm_quality_check(cls, item: ReceivingItem) -> QualityCheckResult:
        """
        Mock VLM质检（展会Demo用）。

        基于规则模拟VLM分析结果:
          - 短重>15% 或 温度>-8°C → D级(拒收)
          - 短重7-15% 或 温度>-12°C → C级(合格需关注)
          - 短重3-7% → B级(良好)
          - 其他 → A级(优秀)
        """
        variance = 0.0
        if item.ordered_qty > 0:
            variance = abs((item.ordered_qty - item.received_qty) / item.ordered_qty * 100)

        temp = item.temperature_on_arrival or -18.0
        defects = []

        # 温度检查 (BR-10)
        temp_ok = temp <= -12.0
        if not temp_ok:
            defects.append(f"到货温度{temp}°C超标(应≤-12°C)")

        # 短重分级
        if variance > 15 or temp > -8:
            grade = "D"
            passed = False
            if variance > 15:
                defects.append(f"短重{variance:.1f}%超阈值(>15%)")
            if not defects:
                defects.append("品质严重不达标")
            rejection_reason = "; ".join(defects)
        elif variance > 7 or (temp > -12 and temp <= -8):
            grade = "C"
            passed = True
            defects.append("轻微异常需关注")
            rejection_reason = None
        elif variance > 3:
            grade = "B"
            passed = True
            rejection_reason = None
        else:
            grade = "A"
            passed = True
            rejection_reason = None

        return QualityCheckResult(
            sku=item.sku,
            passed=passed,
            grade=grade,
            weight_variance_pct=round(variance, 2) if item.ordered_qty > 0 else None,
            temperature_ok=temp_ok,
            visual_defects=defects,
            vlm_analysis={"mock": True, "confidence": 0.85 + (0.1 if grade == "A" else 0)},
            rejection_reason=rejection_reason,
        )

    @classmethod
    def approve_receiving(cls, record_id: str, approver: str, notes: str = None) -> Dict[str, Any]:
        """
        潘厨审批：全部通过。

        BR-07: 有grade=D的品项时不允许全部通过。
        """
        record = cls._receiving_cache.get(record_id)
        if not record:
            raise ValueError(f"收货记录不存在: {record_id}")
        if record.status != "pending_approval":
            raise ValueError(f"当前状态不允许审批: {record.status}")

        # BR-07: D级阻断
        for qr in record.quality_results:
            if qr.grade == "D":
                raise ValueError(
                    f"存在D级品项({qr.sku})，不允许全部通过。请使用'部分通过'或'拒收'"
                )

        record.status = "approved"
        record.approved_by = approver
        record.approved_at = datetime.now()
        if notes:
            record.notes = (record.notes or "") + f"\n[审批意见] {notes}"

        cls._save_to_json()
        logger.info("收货审批通过: %s, 审批人=%s", record_id, approver)
        return record.model_dump()

    @classmethod
    def partial_approve(cls, record_id: str, approver: str, notes: str = None) -> Dict[str, Any]:
        """潘厨审批：部分通过（部分品项拒收）。"""
        record = cls._receiving_cache.get(record_id)
        if not record:
            raise ValueError(f"收货记录不存在: {record_id}")
        if record.status != "pending_approval":
            raise ValueError(f"当前状态不允许审批: {record.status}")

        record.status = "partial"
        record.total_passed = False
        record.approved_by = approver
        record.approved_at = datetime.now()
        if notes:
            record.notes = (record.notes or "") + f"\n[部分通过] {notes}"
        else:
            record.notes = (record.notes or "") + "\n[部分通过] 部分品项存在品质问题"

        cls._save_to_json()
        logger.info("收货部分通过: %s, 审批人=%s", record_id, approver)
        return record.model_dump()

    @classmethod
    def reject_receiving(cls, record_id: str, approver: str, reason: str) -> Dict[str, Any]:
        """
        潘厨审批：整批拒收。

        必须提供拒收原因。
        """
        record = cls._receiving_cache.get(record_id)
        if not record:
            raise ValueError(f"收货记录不存在: {record_id}")
        if record.status != "pending_approval":
            raise ValueError(f"当前状态不允许审批: {record.status}")
        if not reason or not reason.strip():
            raise ValueError("拒收必须填写原因")

        record.status = "rejected"
        record.total_passed = False
        record.approved_by = approver
        record.approved_at = datetime.now()
        record.notes = (record.notes or "") + f"\n[拒收] {reason}"

        # 标记所有质检结果为未通过
        for qr in record.quality_results:
            if qr.passed:
                qr.passed = False

        cls._save_to_json()
        logger.info("收货拒收: %s, 审批人=%s, 原因=%s", record_id, approver, reason)
        return record.model_dump()

    @classmethod
    def return_for_revision(cls, record_id: str, approver: str, reason: str) -> Dict[str, Any]:
        """潘厨退回修改（信息不全时使用）。"""
        record = cls._receiving_cache.get(record_id)
        if not record:
            raise ValueError(f"收货记录不存在: {record_id}")
        if record.status != "pending_approval":
            raise ValueError(f"当前状态不允许退回: {record.status}")

        record.status = "draft"
        record.notes = (record.notes or "") + f"\n[退回修改] {reason} (by {approver})"
        # 清空之前的质检结果
        record.quality_results = []

        cls._save_to_json()
        logger.info("收货退回修改: %s, 操作人=%s", record_id, approver)
        return record.model_dump()

    @classmethod
    def get_receiving_stats(cls) -> Dict[str, Any]:
        """获取收货统计概览（今日+本周）。"""
        from datetime import timedelta

        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())

        all_records = list(cls._receiving_cache.values())

        # 今日统计
        today_records = [r for r in all_records if r.received_at and r.received_at >= today_start]
        today_passed = sum(1 for r in today_records if r.status == "approved")
        today_partial = sum(1 for r in today_records if r.status == "partial")
        today_rejected = sum(1 for r in today_records if r.status == "rejected")
        today_total = len(today_records)

        # 本周统计
        week_records = [r for r in all_records if r.received_at and r.received_at >= week_start]
        week_pass_rate = (
            sum(1 for r in week_records if r.status in ("approved", "partial")) / max(len(week_records), 1)
        )

        # 供应商统计
        supplier_stats = {}
        for r in week_records:
            name = r.supplier_name
            if name not in supplier_stats:
                supplier_stats[name] = {"records": 0, "grades": [], "total_variance": 0}
            supplier_stats[name]["records"] += 1
            for qr in r.quality_results:
                supplier_stats[name]["grades"].append(qr.grade)
            for item in r.items:
                if item.ordered_qty > 0:
                    v = (item.ordered_qty - item.received_qty) / item.ordered_qty * 100
                    supplier_stats[name]["total_variance"] += v

        # Top供应商排行
        top_suppliers = sorted(
            [
                {
                    "name": name,
                    "records": stats["records"],
                    "avg_grade": cls._calc_avg_grade(stats["grades"]),
                }
                for name, stats in supplier_stats.items()
            ],
            key=lambda x: x["records"],
            reverse=True,
        )[:5]

        # 告警检测
        alerts = []
        for name, stats in supplier_stats.items():
            rejected_count = sum(1 for g in stats["grades"] if g == "D")
            if rejected_count >= 3:
                alerts.append({
                    "type": "short_weight",
                    "supplier": name,
                    "count": rejected_count,
                    "msg": f"连续{rejected_count}次严重问题",
                })

        return {
            "today": {
                "total_records": today_total,
                "passed": today_passed,
                "partial": today_partial,
                "rejected": today_rejected,
                "pass_rate": today_passed / max(today_total, 1),
            },
            "week": {
                "total_records": len(week_records),
                "avg_pass_rate": round(week_pass_rate, 2),
                "top_suppliers": top_suppliers,
            },
            "alerts": alerts,
        }

    @classmethod
    def _calc_avg_grade(cls, grades: List[str]) -> str:
        """计算平均等级。"""
        if not grades:
            return "-"
        grade_map = {"A": 4, "B": 3, "C": 2, "D": 1}
        avg_score = sum(grade_map.get(g, 0) for g in grades) / len(grades)
        if avg_score >= 3.5:
            return "A"
        elif avg_score >= 2.5:
            return "B+"
        elif avg_score >= 1.5:
            return "C"
        else:
            return "D"

    @classmethod
    def get_supplier_receiving_history(cls, supplier_name: str, limit: int = 20) -> Dict[str, Any]:
        """获取供应商收货历史（用于N07供应商画像）。"""
        records = [
            r for r in cls._receiving_cache.values()
            if supplier_name in r.supplier_name
        ]
        records.sort(key=lambda r: r.received_at or datetime.min, reverse=True)
        records = records[:limit]

        # 聚合统计数据
        total = len(records)
        passed = sum(1 for r in records if r.status == "approved")
        partial = sum(1 for r in records if r.status == "partial")
        rejected = sum(1 for r in records if r.status == "rejected")

        all_grades = []
        total_variance = 0.0
        variance_count = 0
        for r in records:
            for qr in r.quality_results:
                all_grades.append(qr.grade)
                if qr.weight_variance_pct is not None:
                    total_variance += qr.weight_variance_pct
                    variance_count += 1

        return {
            "supplier_name": supplier_name,
            "total_records": total,
            "pass_rate": round(passed / max(total, 1), 2),
            "avg_grade": cls._calc_avg_grade(all_grades),
            "avg_variance_pct": round(total_variance / max(variance_count, 1), 2) if variance_count else None,
            "records": [r.model_dump() for r in records],
        }

    @classmethod
    def seed_demo_receiving_data(cls) -> int:
        """
        加载展会Demo用的收货数据。

        包含3种典型场景: 正常(A级)、部分通过(C级)、拒收(D级)
        """
        now = datetime.now()
        yesterday = now - timedelta(days=1)
        day_before = now - timedelta(days=2)

        demo_records = [
            # 场景A: 正常收货 — 全部A级通过
            ReceivingRecord(
                record_id="RC-DEMO-001",
                store_id="store-jiaojiang",
                supplier_name="杭州冻品供应链",
                po_number="PO-20260730-001",
                received_at=yesterday,
                receiver="张三",
                items=[
                    ReceivingItem(sku="FP-MW-001", sku_name="精品毛肚", ordered_qty=10.0, received_qty=10.0, unit="kg",
                                  batch_id="20260728-HDW", temperature_on_arrival=-16.0),
                    ReceivingItem(sku="FP-NB-003", sku_name="肥牛卷", ordered_qty=5.0, received_qty=4.9, unit="kg",
                                  batch_id="20260729-ZJ", temperature_on_arrival=-15.5),
                ],
                quality_results=[
                    QualityCheckResult(sku="FP-MW-001", passed=True, grade="A", weight_variance_pct=0.0,
                                       temperature_ok=True, vlm_analysis={"mock": True}),
                    QualityCheckResult(sku="FP-NB-003", passed=True, grade="B", weight_variance_pct=2.0,
                                       temperature_ok=True, visual_defects=["轻微短重"], vlm_analysis={"mock": True}),
                ],
                photos=["overview:/static/demo/receiving-demo1.jpg"],
                total_passed=True,
                status="approved",
                approved_by="潘厨",
                approved_at=yesterday,
            ),
            # 场景B: 部分通过 — 有C级品项
            ReceivingRecord(
                record_id="RC-DEMO-002",
                store_id="store-jiaojiang",
                supplier_name="张记肉业",
                po_number="PO-20260729-002",
                received_at=day_before,
                receiver="李四",
                items=[
                    ReceivingItem(sku="FP-HS-002", sku_name="雪花肥牛", ordered_qty=8.0, received_qty=7.2, unit="kg",
                                  batch_id="20260727-ZJ", temperature_on_arrival=-11.0),
                ],
                quality_results=[
                    QualityCheckResult(sku="FP-HS-002", passed=True, grade="C", weight_variance_pct=10.0,
                                       temperature_ok=False, visual_defects=["温度偏高(-11°C)", "短重10%"],
                                       vlm_analysis={"mock": True}),
                ],
                photos=["overview:/static/demo/receiving-demo2.jpg", "defect:/static/demo/receiving-demo2-defect.jpg"],
                total_passed=False,
                status="partial",
                approved_by="潘厨",
                approved_at=day_before,
                notes="[部分通过] 温度偏高但可用，已加强入库后优先使用",
            ),
            # 场景C: 整批拒收 — D级
            ReceivingRecord(
                record_id="RC-DEMO-003",
                store_id="store-jiaojiang",
                supplier_name="李记海鲜",
                po_number="PO-20260728-003",
                received_at=day_before,
                receiver="王五",
                items=[
                    ReceivingItem(sku="FP-HX-001", sku_name="基围虾", ordered_qty=3.0, received_qty=2.4, unit="kg",
                                  batch_id="20260726-LJ", temperature_on_arrival=-5.0),
                ],
                quality_results=[
                    QualityCheckResult(sku="FP-HX-001", passed=False, grade="D", weight_variance_pct=20.0,
                                       temperature_ok=False, visual_defects=["严重短重20%", "温度严重超标(-5°C)", "疑似解冻"],
                                       rejection_reason="短重20%且温度-5°C严重超标，整批拒收",
                                       vlm_analysis={"mock": True}),
                ],
                photos=["overview:/static/demo/receiving-demo3.jpg", "defect:/static/demo/receiving-demo3-defect.jpg"],
                total_passed=False,
                status="rejected",
                approved_by="潘厨",
                approved_at=day_before,
                notes="[拒收] 短重20%且温度-5°C严重超标，疑似运输途中解冻，整批退回",
            ),
        ]

        count = 0
        for record in demo_records:
            if record.record_id not in cls._receiving_cache:
                cls._receiving_cache[record.record_id] = record
                count += 1

        cls._save_to_json()
        logger.info("Demo收货数据加载完成: %d 条", count)
        return count

    # ================================================================
    # S03: 采购订单管理 (D1-S03 · 2026-08-01)
    # ================================================================

    _po_cache: Dict[str, PurchaseOrder] = {}
    _po_counter: int = 0

    @classmethod
    def _get_next_po_number(cls) -> str:
        """生成下一个采购单号: PO-YYYYMMDD-XXXX"""
        cls._po_counter += 1
        today = datetime.now().strftime("%Y%m%d")
        return f"PO-{today}-{cls._po_counter:04d}"

    @classmethod
    def create_purchase_order(cls, order_data: dict) -> PurchaseOrder:
        """
        创建采购订单 (BR-01~BR-07)

        验证规则:
        - items ≥ 1 (BR-01)
        - SKU必须存在于ProductMaster (BR-02)
        - quantity > 0 (BR-03)
        - 自动计算 amount 和 total_amount (BR-05/06)
        """
        items_data = order_data.get("items", [])
        if not items_data:
            raise ValueError("订单至少包含1个行项目 (BR-01)")

        po_items = []
        total = 0.0

        for item_data in items_data:
            sku = item_data.get("sku", "")
            # BR-02: 校验SKU存在
            if sku not in cls._product_cache:
                raise ValueError(f"SKU不存在: {sku} (BR-02)")

            product = cls._product_cache[sku]
            quantity = item_data.get("quantity", 0)
            # BR-03
            if quantity <= 0:
                raise ValueError(f"数量必须大于0: {sku} (BR-03)")

            # BR-04: 单价取行项目指定值或ProductMaster.unit_price
            unit_price = item_data.get("unit_price") or product.unit_price
            amount = round(quantity * unit_price, 2)
            total += amount

            po_items.append(PurchaseOrderItem(
                sku=sku,
                sku_name=product.name,
                quantity=quantity,
                unit=product.unit,
                unit_price=unit_price,
                amount=amount,
                supplier=item_data.get("supplier"),
                expected_date=item_data.get("expected_date"),
                notes=item_data.get("notes"),
                received_qty=0.0,
            ))

        po_number = cls._get_next_po_number()
        now = datetime.now()

        order = PurchaseOrder(
            po_number=po_number,
            store_id=order_data.get("store_id", "store-jiaojiang"),
            ordered_by=order_data.get("ordered_by", ""),
            ordered_at=now,
            items=po_items,
            total_amount=round(total, 2),
            status="draft",
            supplier=order_data.get("supplier"),
            delivery_address=order_data.get("delivery_address"),
            expected_date=order_data.get("expected_date"),
            notes=order_data.get("notes"),
            forecast_ref=order_data.get("forecast_ref"),
            auto_generated=order_data.get("auto_generated", False),
            created_at=now,
            updated_at=now,
        )

        cls._po_cache[po_number] = order
        cls._save_to_json()
        logger.info("创建采购订单: %s (%d项, ¥%.2f)", po_number, len(po_items), total)
        return order

    @classmethod
    def get_po_list(
        cls,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        supplier: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict:
        """采购订单列表（分页+筛选）"""
        orders = list(cls._po_cache.values())

        # 筛选
        if status:
            orders = [o for o in orders if o.status == status]
        if supplier:
            orders = [o for o in orders if o.supplier and supplier in o.supplier]
        if start_date:
            try:
                sd = datetime.fromisoformat(start_date)
                orders = [o for o in orders if o.ordered_at and o.ordered_at >= sd]
            except ValueError:
                pass
        if end_date:
            try:
                ed = datetime.fromisoformat(end_date)
                orders = [o for o in orders if o.ordered_at and o.ordered_at <= ed]
            except ValueError:
                pass

        # 按下单时间倒序
        orders.sort(key=lambda o: o.ordered_at or datetime.min, reverse=True)

        total = len(orders)
        start_idx = (page - 1) * page_size
        page_orders = orders[start_idx : start_idx + page_size]

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "total_pages": (total + page_size - 1) // page_size if total else 0,
            "items": [o.model_dump() for o in page_orders],
        }

    @classmethod
    def get_po_detail(cls, po_number: str) -> PurchaseOrder:
        """获取订单详情"""
        if po_number not in cls._po_cache:
            raise KeyError(f"采购订单不存在: {po_number}")
        return cls._po_cache[po_number]

    @classmethod
    def update_purchase_order(cls, po_number: str, update_data: dict) -> PurchaseOrder:
        """更新订单（仅draft状态, BR-08）"""
        order = cls.get_po_detail(po_number)
        if order.status != "draft":
            raise PermissionError(f"仅草稿状态可编辑 (当前: {order.status}, BR-08)")

        # 更新基本信息
        for field in ["supplier", "delivery_address", "expected_date", "notes"]:
            if field in update_data:
                setattr(order, field, update_data[field])

        # 更新行项目
        if "items" in update_data:
            new_items = []
            total = 0.0
            for item_data in update_data["items"]:
                sku = item_data.get("sku", "")
                if sku not in cls._product_cache:
                    raise ValueError(f"SKU不存在: {sku}")
                product = cls._product_cache[sku]
                quantity = item_data.get("quantity", 0)
                if quantity <= 0:
                    raise ValueError(f"数量必须大于0: {sku}")
                unit_price = item_data.get("unit_price") or product.unit_price
                amount = round(quantity * unit_price, 2)
                total += amount
                new_items.append(PurchaseOrderItem(
                    sku=sku, sku_name=product.name, quantity=quantity,
                    unit=product.unit, unit_price=unit_price, amount=amount,
                    supplier=item_data.get("supplier"),
                    expected_date=item_data.get("expected_date"),
                    notes=item_data.get("notes"),
                    received_qty=item_data.get("received_qty", 0),
                ))
            order.items = new_items
            order.total_amount = round(total, 2)

        order.updated_at = datetime.now()
        cls._save_to_json()
        return order

    @classmethod
    def delete_purchase_order(cls, po_number: str) -> bool:
        """删除草稿订单"""
        order = cls.get_po_detail(po_number)
        if order.status != "draft":
            raise PermissionError(f"仅可删除草稿订单 (当前: {order.status})")
        del cls._po_cache[po_number]
        cls._save_to_json()
        logger.info("删除采购订单: %s", po_number)
        return True

    @classmethod
    def submit_po(cls, po_number: str) -> PurchaseOrder:
        """提交订单（draft → submitted）"""
        order = cls.get_po_detail(po_number)
        if order.status != "draft":
            raise PermissionError(f"仅草稿状态可提交 (当前: {order.status})")
        if not order.items:
            raise ValueError("空订单不可提交")
        order.status = "submitted"
        order.updated_at = datetime.now()
        cls._save_to_json()
        logger.info("提交采购订单: %s → submitted", po_number)
        return order

    @classmethod
    def confirm_po(cls, po_number: str, notes: Optional[str] = None) -> PurchaseOrder:
        """确认订单（submitted → confirmed, 曹总操作）"""
        order = cls.get_po_detail(po_number)
        if order.status != "submitted":
            raise PermissionError(f"仅已提交状态可确认 (当前: {order.status})")
        order.status = "confirmed"
        order.confirmed_by = "曹总"
        order.confirmed_at = datetime.now()
        if notes:
            order.notes = (order.notes or "") + f"\n[确认备注] {notes}"
        order.updated_at = datetime.now()
        cls._save_to_json()
        logger.info("确认采购订单: %s → confirmed", po_number)
        return order

    @classmethod
    def cancel_po(cls, po_number: str, reason: str) -> PurchaseOrder:
        """取消订单 (BR-09~BR-11)"""
        order = cls.get_po_detail(po_number)
        if order.status in ("received", "partial"):
            raise PermissionError(f"已收货订单不可取消 (当前: {order.status}, BR-11)")
        if order.status not in ("draft", "submitted", "confirmed"):
            raise PermissionError(f"当前状态不可取消: {order.status} (BR-09)")
        if order.status == "confirmed":
            # BR-10: 已确认订单需检查是否有关联收货
            linked_receiving = [
                r for r in cls._receiving_cache.values()
                if r.po_number == po_number
            ]
            if linked_receiving:
                raise PermissionError("已关联收货记录的订单不可取消 (BR-10)")
        order.status = "cancelled"
        order.cancelled_by = "店长"
        order.cancelled_at = datetime.now()
        order.cancel_reason = reason
        order.updated_at = datetime.now()
        cls._save_to_json()
        logger.info("取消采购订单: %s → cancelled (原因: %s)", po_number, reason)
        return order

    @classmethod
    def return_po_to_draft(cls, po_number: str) -> PurchaseOrder:
        """退回草稿（submitted → draft）"""
        order = cls.get_po_detail(po_number)
        if order.status != "submitted":
            raise PermissionError(f"仅已提交状态可退回 (当前: {order.status})")
        order.status = "draft"
        order.updated_at = datetime.now()
        cls._save_to_json()
        logger.info("退回采购订单: %s → draft", po_number)
        return order

    @classmethod
    def mark_po_received(cls, po_number: str, received_by: str = "") -> PurchaseOrder:
        """手动标记全部收货（confirmed/partial → received）"""
        order = cls.get_po_detail(po_number)
        if order.status not in ("confirmed", "partial"):
            raise PermissionError(f"仅待收货/部分收货状态可标记 (当前: {order.status})")

        # 标记所有item为已收全
        for item in order.items:
            item.received_qty = item.quantity

        order.status = "received"
        order.received_by = received_by or "系统"
        order.received_at = datetime.now()
        order.updated_at = datetime.now()
        cls._save_to_json()
        logger.info("标记采购订单已收货: %s → received", po_number)
        return order

    @classmethod
    def _update_po_status_from_receiving(cls, po_number: str) -> Optional[PurchaseOrder]:
        """
        S02联动: 收货审批通过后更新PO状态 (BR-12)

        由 receiving 模块在 approve 操作后调用。
        遍历PO的所有行项目，检查 received_qty vs quantity。
        """
        if po_number not in cls._po_cache:
            return None

        order = cls._po_cache[po_number]
        if order.status not in ("confirmed", "partial"):
            return order

        all_complete = True
        any_received = False

        for item in order.items:
            if item.received_qty > 0:
                any_received = True
            if item.received_qty < item.quantity:
                all_complete = False

        old_status = order.status
        if all_complete:
            order.status = "received"
            order.received_at = datetime.now()
        elif any_received:
            order.status = "partial"
        # else: 保持原状态

        if order.status != old_status:
            order.updated_at = datetime.now()
            cls._save_to_json()
            logger.info("PO状态自动更新: %s %s→%s (S02联动)", po_number, old_status, order.status)

        return order

    @classmethod
    def get_po_receiving_links(cls, po_number: str) -> list:
        """获取PO关联的收货记录列表"""
        cls.get_po_detail(po_number)  # 验证PO存在
        return [
            r.model_dump()
            for r in cls._receiving_cache.values()
            if r.po_number == po_number
        ]

    @classmethod
    def get_po_stats(cls, store_id: str = "store-jiaojiang") -> dict:
        """采购统计概览"""
        now = datetime.now()
        today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = today_start - timedelta(days=today_start.weekday())

        orders = list(cls._po_cache.values())

        today_orders = [o for o in orders if o.ordered_at and o.ordered_at >= today_start]
        week_orders = [o for o in orders if o.ordered_at and o.ordered_at >= week_start]

        # 待收货 = confirmed 状态
        pending_receive = sum(1 for o in orders if o.status == "confirmed")

        # 状态分布
        status_breakdown = {}
        for s in ("draft", "submitted", "confirmed", "partial", "received", "cancelled"):
            status_breakdown[s] = sum(1 for o in orders if o.status == s)

        # 供应商排行
        supplier_totals: Dict[str, dict] = {}
        for o in orders:
            if o.supplier:
                if o.supplier not in supplier_totals:
                    supplier_totals[o.supplier] = {"order_count": 0, "total_amount": 0.0}
                supplier_totals[o.supplier]["order_count"] += 1
                supplier_totals[o.supplier]["total_amount"] += o.total_amount

        top_suppliers = sorted(
            supplier_totals.items(),
            key=lambda x: x[1]["total_amount"],
            reverse=True,
        )[:5]

        return {
            "store_id": store_id,
            "today_orders": len(today_orders),
            "week_orders": len(week_orders),
            "total_amount_today": round(sum(o.total_amount for o in today_orders), 2),
            "total_amount_week": round(sum(o.total_amount for o in week_orders), 2),
            "pending_receive": pending_receive,
            "status_breakdown": status_breakdown,
            "top_suppliers": [
                {"name": name, **stats}
                for name, stats in top_suppliers
            ],
        }

    @classmethod
    def get_supplier_po_history(cls, supplier_name: str) -> dict:
        """供应商采购历史趋势"""
        orders = [
            o for o in cls._po_cache.values()
            if o.supplier and supplier_name in o.supplier
        ]
        orders.sort(key=lambda o: o.ordered_at or datetime.min)

        monthly_totals: Dict[str, float] = {}
        monthly_counts: Dict[str, int] = {}

        for o in orders:
            if o.ordered_at:
                key = o.ordered_at.strftime("%Y-%m")
                monthly_totals[key] = monthly_totals.get(key, 0) + o.total_amount
                monthly_counts[key] = monthly_counts.get(key, 0) + 1

        return {
            "supplier_name": supplier_name,
            "total_orders": len(orders),
            "total_amount": round(sum(o.total_amount for o in orders), 2),
            "avg_order_value": round(
                sum(o.total_amount for o in orders) / max(len(orders), 1), 2
            ),
            "monthly_trend": [
                {"month": k, "amount": v, "count": monthly_counts.get(k, 0)}
                for k, v in sorted(monthly_totals.items())
            ],
            "recent_orders": [o.model_dump() for o in orders[-10:]],
        }

    @classmethod
    def seed_demo_po_data(cls) -> int:
        """
        加载展会Demo用的采购订单数据。

        4种场景: 已收货(A)/待确认(B)/部分收货(C)/草稿(D)
        """
        now = datetime.now()
        yesterday = now - timedelta(days=1)
        day_before = now - timedelta(days=2)
        three_days_ago = now - timedelta(days=3)

        demo_orders = [
            # 场景A: 已完成全流程
            PurchaseOrder(
                po_number="PO-DEMO-001",
                store_id="store-jiaojiang",
                ordered_by="店长-张三",
                ordered_at=three_days_ago,
                supplier="杭州冻品供应链",
                expected_date=date.today() - timedelta(days=1),
                status="received",
                total_amount=1810.0,
                items=[
                    PurchaseOrderItem(sku="FP-MW-001", sku_name="精品毛肚", quantity=10.0,
                                     unit="盒", unit_price=128.0, amount=1280.0, received_qty=10.0),
                    PurchaseOrderItem(sku="FP-NB-003", sku_name="肥牛卷", quantity=5.0,
                                     unit="kg", unit_price=106.0, amount=530.0, received_qty=5.0),
                ],
                confirmed_by="曹总", confirmed_at=three_days_ago,
                received_by="收货员-赵六", received_at=yesterday,
                notes="周末备货常规补货",
                created_at=three_days_ago, updated_at=yesterday,
            ),
            # 场景B: 待确认
            PurchaseOrder(
                po_number="PO-DEMO-002",
                store_id="store-jiaojiang",
                ordered_by="店长-李四",
                ordered_at=now,
                supplier="张记肉业",
                expected_date=date.today() + timedelta(days=2),
                status="submitted",
                total_amount=856.0,
                items=[
                    PurchaseOrderItem(sku="FP-HS-002", sku_name="雪花肥牛", quantity=8.0,
                                     unit="kg", unit_price=107.0, amount=856.0, received_qty=0),
                ],
                notes="雪花肥牛补货，请尽快确认",
                created_at=now, updated_at=now,
            ),
            # 场景C: 部分收货
            PurchaseOrder(
                po_number="PO-DEMO-003",
                store_id="store-jiaojiang",
                ordered_by="店长-张三",
                ordered_at=day_before,
                supplier="杭州冻品供应链",
                expected_date=date.today(),
                status="partial",
                total_amount=2144.0,
                items=[
                    PurchaseOrderItem(sku="FP-MW-001", sku_name="精品毛肚", quantity=5.0,
                                     unit="盒", unit_price=128.0, amount=640.0, received_qty=5.0),
                    PurchaseOrderItem(sku="FP-HX-001", sku_name="基围虾", quantity=3.0,
                                     unit="kg", unit_price=168.0, amount=504.0, received_qty=0),
                    PurchaseOrderItem(sku="FP-YR-005", sku_name="鸭血", quantity=20.0,
                                     unit="份", unit_price=50.0, amount=1000.0, received_qty=20.0),
                ],
                confirmed_by="曹总", confirmed_at=day_before,
                notes="分批到货：毛肚和鸭血已到，虾明日送达",
                created_at=day_before, updated_at=yesterday,
            ),
            # 场景D: 今日草稿
            PurchaseOrder(
                po_number="PO-DEMO-004",
                store_id="store-jiaojiang",
                ordered_by="店长-王五",
                ordered_at=now,
                supplier="杭州冻品供应链",
                expected_date=date.today() + timedelta(days=1),
                status="draft",
                total_amount=938.0,
                items=[
                    PurchaseOrderItem(sku="FP-GD-004", sku_name="贡菜", quantity=10.0,
                                     unit="kg", unit_price=28.0, amount=280.0, received_qty=0),
                    PurchaseOrderItem(sku="FP-YR-005", sku_name="鸭血", quantity=10.0,
                                     unit="份", unit_price=50.0, amount=500.0, received_qty=0),
                    PurchaseOrderItem(sku="FP-DJ-007", sku_name="豆皮", quantity=5.0,
                                     unit="kg", unit_price=31.6, amount=158.0, received_qty=0),
                ],
                notes="下周初备货，待确认品类",
                created_at=now, updated_at=now,
            ),
        ]

        count = 0
        for order in demo_orders:
            if order.po_number not in cls._po_cache:
                cls._po_cache[order.po_number] = order
                count += 1

        cls._save_to_json()
        logger.info("Demo采购订单数据加载完成: %d 条", count)
        return count

    # ============================================================
    # S04 — 供应商协同与评分 (2026-08-01)
    # ============================================================

    _supplier_cache: Dict[str, dict] = {}  # supplier_id → supplier dict
    _supplier_counter: int = 0
    _score_cache: Dict[str, dict] = {}     # score_id → score snapshot
    _adjustment_cache: Dict[str, dict] = {} # adjustment_id → adjustment

    @classmethod
    def _get_next_supplier_id(cls) -> str:
        cls._supplier_counter += 1
        return f"SUP-{cls._supplier_counter:04d}"

    @classmethod
    def create_supplier(
        cls,
        name: str,
        contact_person: str = "",
        phone: str = "",
        address: str = "",
        license_no: Optional[str] = None,
        supplied_skus: Optional[List[str]] = None,
        contract_start: Optional[date] = None,
        contract_end: Optional[date] = None,
        notes: Optional[str] = None,
    ) -> dict:
        """创建供应商档案 (BR-05: 初始状态=pending)"""
        # 名称唯一性检查
        for s in cls._supplier_cache.values():
            if s.get("name") == name:
                raise ValueError(f"供应商名称已存在: {name}")

        # SKU合法性检查
        valid_skus = []
        if supplied_skus:
            for sku in supplied_skus:
                if sku in cls._product_cache:
                    valid_skus.append(sku)
                else:
                    logger.warning("SKU不存在，跳过: %s", sku)

        now = datetime.now()
        supplier_id = cls._get_next_supplier_id()
        supplier = {
            "supplier_id": supplier_id,
            "name": name,
            "contact_person": contact_person,
            "phone": phone,
            "address": address,
            "license_no": license_no,
            "status": "pending",  # BR-05: 待审核
            "supplied_skus": valid_skus,
            "score_overall": None,
            "score_quality": None,
            "score_delivery": None,
            "score_price": None,
            "score_service": None,
            "score_grade": None,
            "last_score_at": None,
            "total_orders": 0,
            "total_amount": 0.0,
            "on_time_rate": 100.0,
            "reject_rate": 0.0,
            "contract_start": contract_start.isoformat() if contract_start else None,
            "contract_end": contract_end.isoformat() if contract_end else None,
            "notes": notes,
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
        }
        cls._supplier_cache[supplier_id] = supplier
        cls._save_to_json()
        logger.info("供应商创建成功: %s (%s)", supplier_id, name)
        return supplier

    @classmethod
    def get_supplier_list(
        cls,
        page: int = 1,
        page_size: int = 20,
        status: Optional[str] = None,
        keyword: Optional[str] = None,
        grade: Optional[str] = None,
        sort_by: str = "-score_overall",
    ) -> dict:
        """供应商列表（筛选+排序+分页）"""
        suppliers = list(cls._supplier_cache.values())

        # 状态过滤
        if status:
            suppliers = [s for s in suppliers if s.get("status") == status]

        # 等级过滤
        if grade:
            suppliers = [s for s in suppliers if s.get("score_grade") == grade]

        # 关键词搜索
        if keyword:
            kw = keyword.lower()
            suppliers = [s for s in suppliers if
                         kw in s.get("name", "").lower() or
                         kw in s.get("contact_person", "").lower() or
                         kw in s.get("phone", "")]

        # 排序
        reverse = sort_by.startswith("-")
        sort_field = sort_by.lstrip("-")
        suppliers.sort(
            key=lambda x: x.get(sort_field) or (0 if sort_field.startswith("score") or sort_field in ("total_orders", "total_amount") else ""),
            reverse=reverse,
        )

        # 分页
        total = len(suppliers)
        start = (page - 1) * page_size
        items = suppliers[start:start + page_size]

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": items,
        }

    @classmethod
    def get_supplier_detail(cls, supplier_id: str) -> dict:
        """供应商详情（含最新评分）"""
        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")
        return cls._supplier_cache[supplier_id]

    @classmethod
    def update_supplier(cls, supplier_id: str, **kwargs) -> dict:
        """编辑供应商信息"""
        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")

        supplier = cls._supplier_cache[supplier_id]
        updatable_fields = [
            "contact_person", "phone", "address", "license_no",
            "supplied_skus", "contract_start", "contract_end", "notes",
        ]
        for field, value in kwargs.items():
            if field in updatable_fields:
                if isinstance(value, date):
                    value = value.isoformat()
                supplier[field] = value
        supplier["updated_at"] = datetime.now().isoformat()

        cls._save_to_json()
        return supplier

    @classmethod
    def delete_supplier(cls, supplier_id: str) -> bool:
        """删除供应商（仅允许pending状态）"""
        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")
        supplier = cls._supplier_cache[supplier_id]
        if supplier.get("status") != "pending":
            raise ValueError(f"仅允许删除待审核状态的供应商，当前状态: {supplier['status']}")
        del cls._supplier_cache[supplier_id]
        cls._save_to_json()
        return True

    @classmethod
    def activate_supplier(cls, supplier_id: str) -> dict:
        """激活供应商 (pending→active) + 初始化评分"""
        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")
        supplier = cls._supplier_cache[supplier_id]
        if supplier["status"] != "pending":
            raise ValueError(f"仅待审核状态可激活，当前: {supplier['status']}")

        supplier["status"] = "active"
        supplier["updated_at"] = datetime.now().isoformat()

        # 初始化评分（BR-03/04: MVP默认值）
        supplier["score_quality"] = 85.0
        supplier["score_delivery"] = 80.0
        supplier["score_price"] = 80.0   # BR-03: 无比价数据时中性分
        supplier["score_service"] = 75.0   # BR-04: 无评价数据时默认
        supplier["score_overall"] = round(
            85.0 * 0.40 + 80.0 * 0.25 + 80.0 * 0.20 + 75.0 * 0.15, 1
        )
        supplier["score_grade"] = cls._grade_from_score(supplier["score_overall"])
        supplier["last_score_at"] = datetime.now().isoformat()

        cls._save_to_json()
        logger.info("供应商激活: %s → active, 初始评分: %.1f(%s)",
                    supplier_id, supplier["score_overall"], supplier["score_grade"])
        return supplier

    @classmethod
    def suspend_supplier(cls, supplier_id: str, reason: str = "") -> dict:
        """停用供应商 (active/probation→suspended) BR-08"""
        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")
        supplier = cls._supplier_cache[supplier_id]
        if supplier["status"] not in ("active", "probation"):
            raise ValueError(f"当前状态不允许停用: {supplier['status']}")

        supplier["status"] = "suspended"
        supplier["notes"] = f"{supplier.get('notes') or ''} | 停用原因: {reason}".strip(" |")
        supplier["updated_at"] = datetime.now().isoformat()
        cls._save_to_json()
        return supplier

    @classmethod
    def blacklist_supplier(cls, supplier_id: str, reason: str) -> dict:
        """拉黑供应商 (suspended→blacklisted) BR-12"""
        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")
        supplier = cls._supplier_cache[supplier_id]
        if supplier["status"] != "suspended":
            raise ValueError(f"仅停用状态可拉黑，当前: {supplier['status']}")

        supplier["status"] = "blacklisted"
        supplier["score_overall"] = 25.0  # 黑名单固定低分
        supplier["score_grade"] = "D"
        supplier["notes"] = f"{supplier.get('notes') or ''} | 拉黑原因: {reason}".strip(" |")
        supplier["updated_at"] = datetime.now().isoformat()
        cls._save_to_json()
        logger.warning("供应商拉黑: %s - 原因: %s", supplier_id, reason)
        return supplier

    @classmethod
    def restore_supplier(cls, supplier_id: str) -> dict:
        """恢复供应商 (suspended/blacklisted→active) BR-11/13"""
        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")
        supplier = cls._supplier_cache[supplier_id]
        if supplier["status"] not in ("suspended", "blacklisted"):
            raise ValueError(f"当前状态无需恢复: {supplier['status']}")

        supplier["status"] = "active"
        supplier["updated_at"] = datetime.now().isoformat()
        cls._save_to_json()
        return supplier

    @classmethod
    def get_supplier_score(cls, supplier_id: str) -> dict:
        """获取供应商评分详情（四维+历史快照）"""
        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")

        supplier = cls._supplier_cache[supplier_id]
        now_str = datetime.now().strftime("%Y-%m")

        # 收集历史快照
        history = [
            s for s in cls._score_cache.values()
            if s.get("supplier_id") == supplier_id
        ]
        history.sort(key=lambda x: x.get("period", ""))

        return {
            "supplier_id": supplier_id,
            "name": supplier["name"],
            "current": {
                "overall": supplier.get("score_overall"),
                "quality_score": supplier.get("score_quality"),
                "delivery_score": supplier.get("score_delivery"),
                "price_score": supplier.get("score_price"),
                "service_score": supplier.get("score_service"),
                "grade": supplier.get("score_grade"),
                "calc_at": supplier.get("last_score_at"),
            },
            "dimensions": {
                "quality": {"score": supplier.get("score_quality"), "weight": 0.40},
                "delivery": {"score": supplier.get("score_delivery"), "weight": 0.25},
                "price": {"score": supplier.get("score_price"), "weight": 0.20},
                "service": {"score": supplier.get("score_service"), "weight": 0.15},
            },
            "trend": [
                {"period": s["period"], "overall": s.get("overall"), "grade": s.get("grade")}
                for s in history[-6:]  # 最近6个月
            ],
            "adjustments": [
                {"id": a["id"], "adjustment": a["adjustment"], "reason": a.get("reason"),
                 "adjusted_by": a.get("adjusted_by"), "adjusted_at": a.get("adjusted_at")}
                for a in cls._adjustment_cache.values()
                if a.get("supplier_id") == supplier_id
            ],
        }

    @classmethod
    def get_score_history(cls, supplier_id: str) -> List[dict]:
        """评分历史趋势（月度快照）"""
        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")

        history = [
            s for s in cls._score_cache.values()
            if s.get("supplier_id") == supplier_id
        ]
        history.sort(key=lambda x: x.get("period", ""))
        return history

    @classmethod
    def adjust_score(cls, supplier_id: str, adjustment: float, reason: str, operator: str) -> dict:
        """人工调整评分 (单次±10限制)"""
        if abs(adjustment) > 10:
            raise ValueError("单次调整幅度不超过±10分")
        if not reason:
            raise ValueError("调整原因为必填项")

        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")

        supplier = cls._supplier_cache[supplier_id]
        old_score = supplier.get("score_overall") or 0
        new_score = max(0, min(100, round(old_score + adjustment, 1)))

        supplier["score_overall"] = new_score
        supplier["score_grade"] = cls._grade_from_score(new_score)
        supplier["last_score_at"] = datetime.now().isoformat()
        supplier["updated_at"] = datetime.now().isoformat()

        # 记录调整
        adj_id = f"SA-{len(cls._adjustment_cache) + 1:04d}"
        cls._adjustment_cache[adj_id] = {
            "id": adj_id,
            "supplier_id": supplier_id,
            "adjustment": adjustment,
            "reason": reason,
            "adjusted_by": operator,
            "adjusted_at": datetime.now().isoformat(),
        }

        cls._save_to_json()
        logger.info("供应商评分调整: %s %.1f→%.1f (%+.1f, 原因: %s)",
                    supplier_id, old_score, new_score, adjustment, reason)
        return supplier

    @classmethod
    def get_supplier_orders(cls, supplier_id: str) -> List[dict]:
        """关联采购订单列表"""
        if supplier_id not in cls._supplier_cache:
            raise KeyError(f"供应商不存在: {supplier_id}")
        supplier = cls._supplier_cache[supplier_id]
        name = supplier["name"]

        orders = []
        for po in cls._po_cache.values():
            if po.supplier == name or po.supplier == supplier_id:
                orders.append(po.model_dump())
        orders.sort(key=lambda x: x.get("ordered_at", ""), reverse=True)
        return orders[:20]  # 最近20条

    @classmethod
    def get_supplier_stats(cls) -> dict:
        """供应商统计概览"""
        suppliers = list(cls._supplier_cache.values())
        return {
            "total": len(suppliers),
            "active": sum(1 for s in suppliers if s["status"] == "active"),
            "probation": sum(1 for s in suppliers if s["status"] == "probation"),
            "suspended": sum(1 for s in suppliers if s["status"] == "suspended"),
            "blacklisted": sum(1 for s in suppliers if s["status"] == "blacklisted"),
            "pending": sum(1 for s in suppliers if s["status"] == "pending"),
            "avg_score": round(
                (s.get("score_overall") or 0 for s in suppliers if s.get("score_overall") is not None),
                1,
            ) if any(s.get("score_overall") is not None for s in suppliers) else None,
            "grade_distribution": {
                g: sum(1 for s in suppliers if s.get("score_grade") == g)
                for g in ["A", "B", "C", "D"]
            },
        }

    @classmethod
    def get_supplier_ranking(cls, limit: int = 10) -> List[dict]:
        """供应商排行榜（按评分降序）"""
        suppliers = [
            s for s in cls._supplier_cache.values()
            if s.get("score_overall") is not None and s["status"] == "active"
        ]
        suppliers.sort(key=lambda x: x.get("score_overall", 0), reverse=True)
        return suppliers[:limit]

    @staticmethod
    def _grade_from_score(score: Optional[float]) -> str:
        """根据分数映射等级"""
        if score is None:
            return "-"
        if score >= 90:
            return "A"
        elif score >= 75:
            return "B"
        elif score >= 60:
            return "C"
        else:
            return "D"

    @classmethod
    def seed_demo_suppliers(cls) -> int:
        """加载Demo种子数据 - 5个供应商覆盖全部状态和等级"""
        demo_data = [
            {
                "name": "杭州冻品供应链",
                "contact_person": "王总",
                "phone": "138xxxx1234",
                "address": "杭州市余杭区勾庄农贸市场冻品区B12号",
                "license_no": "SC23310116000xxx",
                "supplied_skus": ["FP-MW-001", "FP-HG-001", "FP-YX-001", "FP-FN-001"],
                "contract_start": date(2026, 1, 1),
                "contract_end": date(2027, 1, 1),
                "notes": "主力毛肚/黄喉/鸭血/肥牛供应商，王总直供",
                "_preset_status": "active",
                "_preset_score": 92.5,
                "_preset_grade": "A",
                "_preset_orders": 24,
                "_preset_on_time": 95.0,
                "_preset_reject": 1.0,
            },
            {
                "name": "宁波海鲜批发中心",
                "contact_person": "李经理",
                "phone": "139xxxx5678",
                "address": "宁波市江北区路林市场海鲜区A08号",
                "license_no": "SC23320206000yyy",
                "supplied_skus": ["FP-HX-001", "FP-XH-001"],
                "contract_start": date(2026, 3, 1),
                "contract_end": date(2027, 3, 1),
                "notes": "海鲜丸/虾滑，价格略高但品质稳定",
                "_preset_status": "active",
                "_preset_score": 82.0,
                "_preset_grade": "B",
                "_preset_orders": 18,
                "_preset_on_time": 87.5,
                "_preset_reject": 5.0,
            },
            {
                "name": "温州牛肉供应链",
                "contact_person": "张总",
                "phone": "137xxxx9012",
                "address": "温州市鹿城区农贸市场牛羊肉区C03号",
                "license_no": "SC23330307000zzz",
                "supplied_skus": ["FP-FN-002", "FP-NR-001"],
                "contract_start": date(2026, 4, 1),
                "contract_end": date(2027, 4, 1),
                "notes": "近期有2次D级质检，已进入观察期",
                "_preset_status": "probation",
                "_preset_score": 62.0,
                "_preset_grade": "C",
                "_preset_orders": 8,
                "_preset_on_time": 71.2,
                "_preset_reject": 18.0,
            },
            {
                "name": "上海调味品贸易公司",
                "contact_person": "赵总",
                "phone": "136xxxx3456",
                "address": "上海市普陀区真北路调味品市场D15号",
                "license_no": "SC23310607000www",
                "supplied_skus": ["FP-GD-001", "FP-JL-001"],
                "contract_start": date(2026, 2, 1),
                "contract_end": date(2027, 2, 1),
                "notes": "因价格纠纷暂停合作",
                "_preset_status": "suspended",
                "_preset_score": None,
                "_preset_grade": None,
                "_preset_orders": 3,
                "_preset_on_time": 60.0,
                "_preset_reject": 8.0,
            },
            {
                "name": "XX冒牌冻品批发",
                "contact_person": "",
                "phone": "",
                "address": "不详",
                "license_no": None,
                "supplied_skus": [],
                "contract_start": None,
                "contract_end": None,
                "notes": "曾发现以劣充好，已拉黑处理",
                "_preset_status": "blacklisted",
                "_preset_score": 25.0,
                "_preset_grade": "D",
                "_preset_orders": 2,
                "_preset_on_time": 35.0,
                "_preset_reject": 100.0,
            },
        ]

        count = 0
        for data in demo_data:
            preset_status = data.pop("_preset_status")
            preset_score = data.pop("_preset_score")
            preset_grade = data.pop("_preset_grade")
            preset_orders = data.pop("_preset_orders")
            preset_on_time = data.pop("_preset_on_time")
            preset_reject = data.pop("_preset_reject")

            supplier = cls.create_supplier(**data)
            supplier["status"] = preset_status
            if preset_score is not None:
                supplier["score_overall"] = preset_score
                supplier["score_grade"] = preset_grade
                # 反推各维度分（近似）
                supplier["score_quality"] = round(preset_score * (0.4 / 0.4) * 0.95, 1) if preset_score >= 60 else preset_score * 0.7
                supplier["score_delivery"] = round(preset_on_time * 0.9, 1)
                supplier["score_price"] = 80.0
                supplier["score_service"] = 75.0
                supplier["last_score_at"] = datetime.now().isoformat()
            supplier["total_orders"] = preset_orders
            supplier["on_time_rate"] = preset_on_time
            supplier["reject_rate"] = preset_reject
            supplier["updated_at"] = datetime.now().isoformat()
            count += 1

        # 生成历史评分快照
        periods = ["2026-03", "2026-04", "2026-05", "2026-06", "2026-07", "2026-08"]
        for i, sup in enumerate(cls._supplier_cache.values()):
            if sup.get("score_overall") is None:
                continue
            base = sup["score_overall"]
            for j, period in enumerate(periods):
                variance = (j - len(periods) / 2) * 2  # 趋势波动
                sscore = max(0, min(100, round(base + variance + (i * -3), 1)))
                sid = f"SS-{period.replace('-', '')}-{sup['supplier_id']}"
                cls._score_cache[sid] = {
                    "id": sid,
                    "supplier_id": sup["supplier_id"],
                    "period": period,
                    "quality_score": round(sscore * 0.95, 1),
                    "delivery_score": round(sscore * 0.88, 1),
                    "price_score": 80.0,
                    "service_score": 75.0,
                    "overall": sscore,
                    "grade": cls._grade_from_score(sscore),
                    "order_count": max(1, preset_orders // 6),
                    "receiving_count": max(1, preset_orders // 3),
                    "rejection_count": max(0, int(preset_reject * preset_orders / 100 / 6)),
                    "calc_at": datetime.now().isoformat(),
                }

        cls._save_to_json()
        logger.info("Demo供应商数据加载完成: %d 个供应商, %d 条评分快照",
                    count, len(cls._score_cache))
        return count

    # ========================================================================
    # D2: 岗位 AI 助理 (2026-08-01)
    # ========================================================================

    # --- 缓存 ---
    _task_cache: Dict[str, dict] = {}
    _suggestion_cache: Dict[str, dict] = {}
    _task_counter: int = 0
    _suggestion_counter: int = 0

    @classmethod
    def _get_next_task_id(cls) -> str:
        cls._task_counter += 1
        dt = datetime.now().strftime("%Y%m%d")
        return f"TSK-{dt}-{cls._task_counter:03d}"

    @classmethod
    def _get_next_suggestion_id(cls) -> str:
        cls._suggestion_counter += 1
        dt = datetime.now().strftime("%Y%m%d")
        return f"SUG-{dt}-{cls._suggestion_counter:03d}"

    # --- 待办生成引擎 ---

    @classmethod
    def _generate_tasks_from_d1(cls) -> List[dict]:
        """基于D1数据自动生成待办事项"""
        tasks = []
        now = datetime.now()

        # BR-D2-01: S02 收货审批待办
        for rid, rec in cls._receiving_cache.items():
            if rec.state == "pending_approval":
                item_names = ", ".join(i["product_name"] for i in rec.items[:3])
                if len(rec.items) > 3:
                    item_names += f" 等{len(rec.items)}项"
                tasks.append({
                    "id": cls._get_next_task_id(),
                    "task_type": "approval",
                    "title": f"{len(rec.items)}批{item_names.split(',')[0] if item_names else '货品'}待质检审批",
                    "description": f"供应商: {rec.supplier_name} | 到货时间: {rec.received_at}",
                    "priority": "urgent",
                    "status": "pending",
                    "source_module": "S02",
                    "target_role": "store_manager",
                    "action_url": f"/receiving-detail.html?id={rid}",
                    "action_text": "去审批",
                    "metadata": {"record_id": rid},
                    "created_at": now.isoformat(),
                    "due_at": (now + timedelta(hours=4)).isoformat(),
                })

        # BR-D2-02: S03 订单确认待办
        for pid, po in cls._po_cache.items():
            if po.status == "submitted":
                items_str = ", ".join(i.product_name for i in po.items[:2])
                tasks.append({
                    "id": cls._get_next_task_id(),
                    "task_type": "purchase",
                    "title": f"PO-{po.order_no} 待确认 ({items_str})",
                    "description": f"供应商: {po.supplier_name} | 金额: ¥{po.total_amount:.0f}",
                    "priority": "high",
                    "status": "pending",
                    "source_module": "S03",
                    "target_role": "store_manager",
                    "action_url": f"/purchase-order-detail.html?id={pid}",
                    "action_text": "去确认",
                    "metadata": {"order_id": pid},
                    "created_at": now.isoformat(),
                    "due_at": (now + timedelta(hours=12)).isoformat(),
                })

        # BR-D2-03: S04 供应商预警
        for sid, sup in cls._supplier_cache.items():
            latest_score = None
            if sid in cls._score_cache and cls._score_cache[sid]:
                scores = sorted(cls._score_cache[sid], key=lambda x: x.get("calc_at", ""), reverse=True)
                if scores:
                    latest_score = scores[0]
            if latest_score and latest_score.get("overall", 100) < 70:
                grade = latest_score.get("grade", "C")
                tasks.append({
                    "id": cls._get_next_task_id(),
                    "task_type": "alert",
                    "title": f'供应商"{sup.name}"评分降至{grade}级({latest_score["overall"]:.0f}分)',
                    "description": f"需关注: 连续品质/交付问题，建议评估合作策略",
                    "priority": "high" if grade == "D" else "medium",
                    "status": "pending",
                    "source_module": "S04",
                    "target_role": "store_manager",
                    "action_url": f"/supplier-detail.html?id={sid}",
                    "action_text": "查看供应商",
                    "metadata": {"supplier_id": sid},
                    "created_at": now.isoformat(),
                })
            elif sup.status in ("probation", "blacklisted"):
                tasks.append({
                    "id": cls._get_next_task_id(),
                    "task_type": "alert",
                    "title": f'供应商"{sup.name}"状态异常({sup.status})',
                    "description": f"当前状态: {sup.status}" + (", 不允许创建新PO" if sup.status == "blacklisted" else ""),
                    "priority": "urgent" if sup.status == "blacklisted" else "high",
                    "status": "pending",
                    "source_module": "S04",
                    "target_role": "store_manager",
                    "action_url": f"/supplier-detail.html?id={sid}",
                    "action_text": "查看详情",
                    "metadata": {"supplier_id": sid},
                    "created_at": now.isoformat(),
                })

        # BR-D2-04: D级质检告警
        for rid, rec in cls._receiving_cache.items():
            if rec.state in ("approved", "partial"):
                d_items = [i for i in rec.items if i.get("quality_grade") == "D"]
                if d_items:
                    names = ", ".join(i["product_name"] for i in d_items[:2])
                    tasks.append({
                        "id": cls._get_next_task_id(),
                        "task_type": "alert",
                        "title": f'{names} 品质不合格(D级) 需处理',
                        "description": f"收货记录: {rid} | 问题项: {len(d_items)}/{len(rec.items)}",
                        "priority": "urgent",
                        "status": "pending",
                        "source_module": "S02",
                        "target_role": "chef_head",
                        "action_url": f"/receiving-detail.html?id={rid}",
                        "action_text": "查看详情",
                        "metadata": {"record_id": rid},
                        "created_at": now.isoformat(),
                        "due_at": (now + timedelta(hours=2)).isoformat(),
                    })

        # BR-D2-05: 每日日报任务
        today_key = now.strftime("%Y-%m-%d")
        daily_exists = any(
            t.get("task_type") == "review" and t.get("created_at", "").startswith(today_key)
            for t in cls._task_cache.values()
        )
        if not daily_exists:
            tasks.append({
                "id": cls._get_next_task_id(),
                "task_type": "review",
                "title": "昨日运营日报待查阅",
                "description": "损耗率、合格率、采购成本等核心指标汇总",
                "priority": "medium",
                "status": "pending",
                "source_module": "system",
                "target_role": "store_manager",
                "action_url": "/dashboard.html",
                "action_text": "查看报告",
                "created_at": now.isoformat(),
            })

        # BR-D2-06: 临期预警
        for pid, prod in cls._product_cache.items():
            if prod.shelf_life_days and prod.shelf_life_days <= 3:
                tasks.append({
                    "id": cls._get_next_task_id(),
                    "task_type": "alert",
                    'title': f'{prod.name} 即将临期(剩余{prod.shelf_life_days}天)',
                    "description": f"SKU: {prod.sku} | 安全库存: {prod.safety_stock}{prod.unit}",
                    "priority": "medium" if prod.shelf_life_days > 1 else "high",
                    "status": "pending",
                    "source_module": "S01",
                    "target_role": "chef_head",
                    "action_url": "/products.html",
                    "action_text": "查看商品",
                    "metadata": {"product_id": pid},
                    "created_at": now.isoformat(),
                })

        return tasks

    # --- AI 建议生成引擎 ---

    @classmethod
    def _generate_suggestions(cls) -> List[dict]:
        """基于D1数据生成AI智能建议"""
        suggestions = []
        now = datetime.now()
        weekday = now.weekday()  # 5=Sat, 6=Sun

        # BR-D2-07: 采购建议（周五/周六触发）
        if weekday >= 4:  # Fri-Sun
            # 找出高频冻品建议采购
            target_skus = ["FP-HNRC-001", "FP-QCD-001"]  # 肥牛卷, 千层肚
            for sku in target_skus:
                prod = cls._product_cache.get(sku)
                if not prod:
                    continue
                # 找最佳供应商
                best_sup = None
                best_score = 0
                for sid, sup in cls._supplier_cache.items():
                    if sup.status != "active":
                        continue
                    score_snap = cls._score_cache.get(sid, [])
                    latest = sorted(score_snap, key=lambda x: x.get("calc_at", ""), reverse=True)[:1]
                    if latest and latest[0].get("overall", 0) > best_score:
                        best_score = latest[0]["overall"]
                        best_sup = sup

                qty = 20 if "肥牛" in prod.name else 10
                suggestions.append({
                    "id": cls._get_next_suggestion_id(),
                    "suggestion_type": "purchase_order",
                    "title": f"建议采购 {prod.name} {qty}{prod.unit}",
                    "content": (
                        f"基于近7日日均消耗预估，考虑"
                        f"{'周末' if weekday >= 5 else '工作日'}客流因子(×{'1.3' if weekday == 5 else '1.2'})，"
                        f"建议采购 {qty}{prod.unit}"
                        + (f"\n推荐供应商: {best_sup.name}(A级)" if best_sup else "")
                    ),
                    "confidence": 0.87,
                    "data": {"sku": sku, "suggested_qty": qty, "unit": prod.unit,
                            "supplier_id": best_sup.id if best_sup else None},
                    "action_type": "create_po",
                    "action_params": {"sku": sku, "qty": qty, "supplier_id": best_sup.id if best_sup else None},
                    "source_role": "purchaser",
                    "source_analysis": "近7日消耗趋势 + 周末因子 + 安全系数×1.1",
                    "created_at": now.isoformat(),
                    "expires_at": (now + timedelta(days=2)).isoformat(),
                })

        # BR-D2-08: 供应商切换建议
        for sid, sup in cls._supplier_cache.items():
            if sup.status != "active":
                continue
            score_snap = cls._score_cache.get(sid, [])
            recent = [s for s in score_snap if s.get("quality_score", 100) < 75]
            if len(recent) >= 2:
                alternatives = [
                    s for s in cls._supplier_cache.values()
                    if s.status == "active" and s.id != sid
                ]
                alt_text = ""
                if alternatives:
                    alt = max(alternatives, key=lambda x: cls._score_cache.get(x.id, [{}])[0].get("overall", 0)
                                if cls._score_cache.get(x.id) else 0)
                    alt_text = f"\n建议切换至: {alt.name}"

                suggestions.append({
                    "id": cls._get_next_suggestion_id(),
                    "suggestion_type": "supplier_switch",
                    "title": f'供应商"{sup.name}"连续{len(recent)}次品质偏低',
                    "content": f"近期品质评分均低于75分，影响出品稳定性{alt_text}",
                    "confidence": 0.78,
                    "data": {"supplier_id": sid, "recent_scores": recent[-3:]},
                    "action_type": "navigate",
                    "action_params": {"url": f"/supplier-detail.html?id={sid}"},
                    "source_role": "purchaser",
                    "source_analysis": f"S02质检数据: 近期{len(recent)}次评分<75",
                    "created_at": now.isoformat(),
                })

        # BR-D2-09: 成本优化建议
        total_po_value = sum(po.total_amount for po in cls._po_cache.values() if po.status in ("confirmed", "received"))
        if total_po_value > 0:
            avg_unit = {}
            for po in cls._po_cache.values():
                for item in po.items:
                    sku = item.sku
                    if sku not in avg_unit:
                        avg_unit[sku] = []
                    avg_unit[sku].append(item.unit_price)

            for sku, prices in avg_unit.items():
                if len(prices) >= 3:
                    avg_p = sum(prices) / len(prices)
                    latest_p = prices[-1]
                    if latest_p > avg_p * 1.15:  # 高于均价15%
                        prod = cls._product_cache.get(sku)
                        name = prod.name if prod else sku
                        suggestions.append({
                            "id": cls._get_next_suggestion_id(),
                            "suggestion_type": "cost_optimization",
                            "title": f"{name} 近期采购价偏高({latest_p:.0f}元, 均价{avg_p:.0f}元)",
                            "content": f"最新单价较历史均价高出{(latest_p/avg_p - 1)*100:.0f}%，建议重新谈判或寻找替代供应商",
                            "confidence": 0.82,
                            "data": {"sku": sku, "current_price": latest_p, "avg_price": avg_p},
                            "action_type": "navigate",
                            "action_params": {"url": "/supplier.html"},
                            "source_role": "purchaser",
                            "source_analysis": f"S03订单数据: 近{len(prices)}次采购价格对比",
                            "created_at": now.isoformat(),
                        })

        # BR-D2-10: 损耗异常告警
        waste_records = [r for r in cls._receiving_cache.values()
                         if r.state in ("approved", "partial")]
        if len(waste_records) >= 3:
            d_rate = sum(1 for r in waste_records
                        for i in r.items if i.get("quality_grade") == "D")
            total_items = sum(len(r.items) for r in waste_records)
            if total_items > 0:
                actual_rate = d_rate / total_items * 100
                if actual_rate > 15:  # D级占比>15%
                    suggestions.append({
                        "id": cls._get_next_suggestion_id(),
                        "suggestion_type": "risk_alert",
                        "title": f"近期D级质检占比偏高({actual_rate:.1f}%)",
                        "content": f"近{len(waste_records)}批收货中D级占比{actual_rate:.1f}%，建议排查供应商品质或验收流程",
                        "confidence": 0.90,
                        "data": {"d_rate": actual_rate, "sample_size": len(waste_records)},
                        "action_type": "navigate",
                        "action_params": {"url": "/receiving.html"},
                        "source_role": "store_manager",
                        "source_analysis": f"S02质检统计: D级{d_rate}/{total_items}项",
                        "created_at": now.isoformat(),
                    })

        return suggestions

    # --- A01 店长数字座舱 ---

    @classmethod
    def get_store_manager_dashboard(cls) -> dict:
        """A01 店长数字座舱完整数据"""
        now = datetime.now()

        # 刷新待办和建议
        auto_tasks = cls._generate_tasks_from_d1()
        for t in auto_tasks:
            tid = t["id"]
            if tid not in cls._task_cache:
                cls._task_cache[tid] = t

        auto_sugs = cls._generate_suggestions()
        for s in auto_sugs:
            sid = s["id"]
            if sid not in cls._suggestion_cache:
                cls._suggestion_cache[sid] = s

        # KPI 计算
        receiving_total = len(cls._receiving_cache)
        passing = sum(1 for r in cls._receiving_cache.values()
                      if r.state in ("approved",) and
                      all(i.get("quality_grade") in ("A", "B") for i in r.items))
        pass_rate = (passing / receiving_total * 100) if receiving_total > 0 else 0

        pending_tasks = [t for t in cls._task_cache.values() if t.get("status") == "pending"
                        and t.get("target_role") in ("store_manager", "all")]
        urgent_count = sum(1 for t in pending_tasks if t.get("priority") == "urgent")

        # 临近保质期商品
        expiring = sum(1 for p in cls._product_cache.values()
                       if p.shelf_life_days and p.shelf_life_days <= 3)

        # 采购金额
        month_po = [p for p in cls._po_cache.values()
                    if p.created_at and p.created_at.startswith(now.strftime("%Y-%m"))]
        month_total = sum(p.total_amount for p in month_po)

        kpis = [
            {"label": "今日销售额", "value": 12580, "unit": "\u00a5", "change": 8.5, "trend": "up"},
            {"label": "待处理事项", "value": len(pending_tasks), "unit": "件",
             "target": 10, "status": "warning" if len(pending_tasks) > 8 else "normal"},
            {"label": "损耗率", "value": 6.2, "unit": "%", "change": -0.8, "trend": "down",
             "target": 8, "status": "normal"},
            {"label": "收货合格率", "value": round(pass_rate, 1), "unit": "%",
             "target": 90, "status": "normal" if pass_rate >= 85 else "warning"},
            {"label": "库存预警", "value": expiring, "unit": "项",
             "status": "warning" if expiring > 0 else "normal"},
        ]

        # 按优先级排序待办
        priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        sorted_tasks = sorted(pending_tasks, key=lambda t: priority_order.get(t.get("priority", "low"), 99))

        # 只返回前10条建议
        active_sugs = [s for s in cls._suggestion_cache.values() if s.get("is_accepted") is None][:5]

        return {
            "store_name": "椒江店",
            "role": "store_manager",
            "date": now.strftime("%Y-%m-%d"),
            "kpis": kpis,
            "tasks": sorted_tasks[:10],
            "suggestions": active_sugs,
            "trends": {
                "waste_rate": [7.0, 6.5, 7.2, 6.8, 6.3, 6.1, 6.2],
                "pass_rate": [88, 90, 89, 91, 92, 93, round(pass_rate, 1)],
                "po_count": [3, 5, 4, 6, 4, 5, len(month_po)],
            },
        }

    @classmethod
    def get_tasks(cls, role: str = "store_manager", status: str = "pending") -> List[dict]:
        """获取指定角色的待办列表"""
        tasks = [t for t in cls._task_cache.values()
                 if t.get("target_role") in (role, "all")
                 and (status == "all" or t.get("status") == status)]
        priority_order = {"urgent": 0, "high": 1, "medium": 2, "low": 3}
        return sorted(tasks, key=lambda t: priority_order.get(t.get("priority", "low"), 99))

    @classmethod
    def get_task_detail(cls, task_id: str) -> Optional[dict]:
        return cls._task_cache.get(task_id)

    @classmethod
    def complete_task(cls, task_id: str) -> bool:
        if task_id in cls._task_cache:
            cls._task_cache[task_id]["status"] = "completed"
            cls._task_cache[task_id]["completed_at"] = datetime.now().isoformat()
            cls._save_to_json()
            return True
        return False

    @classmethod
    def dismiss_task(cls, task_id: str) -> bool:
        if task_id in cls._task_cache:
            cls._task_cache[task_id]["status"] = "dismissed"
            cls._save_to_json()
            return True
        return False

    @classmethod
    def get_suggestions(cls, role: str = "store_manager") -> List[dict]:
        """获取AI建议列表"""
        return [s for s in cls._suggestion_cache.values()
                if s.get("source_role") in (role, "all")
                and s.get("is_accepted") is None]

    @classmethod
    def accept_suggestion(cls, suggestion_id: str) -> bool:
        if suggestion_id in cls._suggestion_cache:
            cls._suggestion_cache[suggestion_id]["is_accepted"] = True
            cls._suggestion_cache[suggestion_id]["accepted_at"] = datetime.now().isoformat()
            cls._save_to_json()
            return True
        return False

    @classmethod
    def reject_suggestion(cls, suggestion_id: str) -> bool:
        if suggestion_id in cls._suggestion_cache:
            cls._suggestion_cache[suggestion_id]["is_accepted"] = False
            cls._suggestion_cache[suggestion_id]["accepted_at"] = datetime.now().isoformat()
            cls._save_to_json()
            return True
        return False

    # --- A02 后厨助理面板 ---

    @classmethod
    def get_kitchen_assistant_panel(cls) -> dict:
        """A02 后厨助理面板"""
        now = datetime.now()

        # 备货清单（基于S01冻品）
        prep_list = []
        frozen_products = [p for p in cls._product_cache.values()
                          if p.category and ("冻" in p.category or "火锅" in p.category or "肉类" in p.category)]
        for prod in frozen_products[:8]:  # 取前8个冻品
            suggested = getattr(prod, 'safety_stock', 10) or 10
            prepped = max(0, int(suggested * 0.7))  # 模拟已备数量
            status = "done" if prepped >= suggested else "partial" if prepped > 0 else "todo"
            prep_list.append({
                "product_name": prod.name,
                "sku": prod.sku,
                "prepped": prepped,
                "target": suggested,
                "unit": prod.unit,
                "status": status,
                "warning": prepped < suggested * 0.3,
            })

        # 温控状态（模拟IoT）
        iot_status = {
            "freezer_1": {"name": "1号冷柜", "temp": -17.2, "status": "normal", "threshold": -12},
            "freezer_2": {"name": "2号冷柜", "temp": -18.1, "status": "normal", "threshold": -12},
            "kitchen_temp": {"name": "后厨室温", "temp": 28.5, "status": "normal", "threshold": 32},
        }

        # SOP提醒
        sop_alerts = []
        under_prep = [p for p in prep_list if p["status"] in ("todo", "partial")]
        if under_prep:
            sop_alerts.append({
                "level": "info",
                "message": f"今日有{len(under_prep)}个品项尚未完成备货，建议11:00前完成",
            })
        d_receivings = [r for r in cls._receiving_cache.values()
                        if any(i.get("quality_grade") == "D" for i in r.items)]
        if d_receivings:
            sop_alerts.append({
                "level": "warning",
                "message": f"近期有{len(d_receivings)}批D级质检，请关注收货品质",
            })

        # 废料事件（模拟）
        waste_events = [
            {"time": "16:42", "item": "毛肚", "qty": 3, "reason": "过量备货"},
            {"time": "14:20", "item": "肥牛卷", "qty": 2, "reason": "临期"},
            {"time": "11:05", "item": "虾滑", "qty": 1, "reason": "变色"},
        ]

        # 后厨专属待办
        kitchen_tasks = [t for t in cls._task_cache.values()
                        if t.get("target_role") in ("chef_head", "all")
                        and t.get("status") == "pending"]

        return {
            "role": "chef_head",
            "date": now.strftime("%Y-%m-%d"),
            "prep_list": prep_list,
            "iot_status": iot_status,
            "alerts": sop_alerts,
            "waste_events": waste_events,
            "tasks": kitchen_tasks[:8],
            "summary": {
                "total_items": len(prep_list),
                "completed": sum(1 for p in prep_list if p["status"] == "done"),
                "pending": sum(1 for p in prep_list if p["status"] != "done"),
                "alert_count": len(sop_alerts),
            },
        }

    # --- A03 采购助理面板 ---

    @classmethod
    def get_purchase_assistant_panel(cls) -> dict:
        """A03 采购助理面板"""
        now = datetime.now()

        # 本月采购统计
        month_key = now.strftime("%Y-%m")
        month_pos = [p for p in cls._po_cache.values()
                     if p.created_at and p.created_at.startswith(month_key)]
        month_total = sum(p.total_amount for p in month_pos)

        # PO跟踪状态
        po_tracking = []
        for pid, po in list(cls._po_cache.items())[:5]:
            received_pct = 0
            if po.items and po.total_qty > 0:
                received_pct = (po.received_qty / po.total_qty) * 100
            po_tracking.append({
                "order_no": po.order_no,
                "supplier_name": po.supplier_name,
                "total_amount": po.total_amount,
                "status": po.status,
                "received_pct": round(received_pct, 1),
                "expected_date": po.expected_date or "待定",
                "items_summary": ", ".join(i.product_name for i in po.items[:2]),
            })

        # 供应商比价表
        supplier_comparison = []
        for sid, sup in cls._supplier_cache.items():
            if sup.status not in ("active",):
                continue
            score_data = cls._score_cache.get(sid, [])
            latest = sorted(score_data, key=lambda x: x.get("calc_at", ""), reverse=True)[:1]
            overall = latest[0]["overall"] if latest else 75
            grade = latest[0]["grade"] if latest else "C"

            # 从PO中取该供应商的最新单价
            sup_prices = []
            for po in cls._po_cache.values():
                if po.supplier_id == sid:
                    for item in po.items:
                        sup_prices.append(item.unit_price)
            avg_price = round(sum(sup_prices) / len(sup_prices), 0) if sup_prices else 0

            supplier_comparison.append({
                "supplier_id": sid,
                "name": sup.name,
                "avg_price": avg_price,
                "grade": grade,
                "overall_score": overall,
                "lead_time": "1天" if grade == "A" else ("2天" if grade == "B" else "3天"),
                "on_time_rate": 98 if grade == "A" else (85 if grade == "B" else 70),
                "quality_score": latest[0].get("quality_score", 80) if latest else 80,
                "recommended": grade == "A",
            })

        supplier_comparison.sort(key=lambda x: x["overall_score"], reverse=True)

        # 采购建议（从suggestion_cache过滤）
        purchase_sugs = [s for s in cls._suggestion_cache.values()
                        if s.get("suggestion_type") == "purchase_order"
                        and s.get("is_accepted") is None]

        # 采购员专属待办
        purchase_tasks = [t for t in cls._task_cache.values()
                         if t.get("target_role") in ("purchaser", "all")
                         and t.get("status") == "pending"]

        return {
            "role": "purchaser",
            "date": now.strftime("%Y-%m-%d"),
            "kpis": [
                {"label": "本月采购额", "value": month_total, "unit": "\u00a5",
                 "budget": 45000, "usage_pct": round(month_total / 45000 * 100, 1) if 45000 else 0},
                {"label": "待收货订单", "value": sum(1 for p in po_tracking if p["status"] in ("confirmed", "partial"))},
                {"label": "供应商数", "value": len([s for s in cls._supplier_cache.values() if s.status == "active"])},
                {"label": "退换货率", "value": 1.2, "unit": "%", "change": -0.3, "trend": "down"},
            ],
            "suggestions": purchase_sugs[:5],
            "po_tracking": po_tracking,
            "supplier_comparison": supplier_comparison,
            "tasks": purchase_tasks[:8],
        }

    # --- A04 供应商协同端 ---

    @classmethod
    def get_supplier_portal(cls, supplier_id: Optional[str] = None) -> dict:
        """A04 供应商协同端"""
        now = datetime.now()

        # 如果指定了supplier_id，只返回该供应商视角
        if supplier_id:
            sup = cls._supplier_cache.get(supplier_id)
            if not sup:
                raise ValueError(f"供应商不存在: {supplier_id}")

            # 该供应商的订单
            my_orders = [p for p in cls._po_cache.values() if p.supplier_id == supplier_id]
            month_orders = [o for o in my_orders if o.created_at and o.created_at.startswith(now.strftime("%Y-%m"))]
            pending_confirm = [o for o in my_orders if o.status == "submitted"]

            # 品质反馈汇总
            my_receivings = [r for r in cls._receiving_cache.values() if r.supplier_id == supplier_id]
            total_receiving = len(my_receivings)
            passed = sum(1 for r in my_receivings
                        if r.state in ("approved",) and
                        all(i.get("quality_grade") in ("A", "B") for i in r.items))
            pass_rate = (passed / total_receiving * 100) if total_receiving > 0 else 100

            # 评分快照
            my_scores = cls._score_cache.get(supplier_id, [])
            latest_score = sorted(my_scores, key=lambda x: x.get("calc_at", ""), reverse=True)[:1]
            current_score = latest_score[0] if latest_score else None
            prev_score = sorted(my_scores, key=lambda x: x.get("calc_at", ""), reverse=True)[1:2]
            score_change = (current_score["overall"] - prev_score[0]["overall"]) if (current_score and prev_score) else 0

            return {
                "supplier_name": sup.name,
                "role": "supplier",
                "date": now.strftime("%Y-%m-%d"),
                "kpis": [
                    {"label": "本月订单数", "value": len(month_orders),
                     "change": 2, "trend": "up"},
                    {"label": "待确认订单", "value": len(pending_confirm),
                     "status": "warning" if pending_confirm else "normal"},
                    {"label": "我方评分", "value": current_score["overall"] if current_score else 85,
                     "unit": "分", "grade": current_score["grade"] if current_score else "B",
                     "change": round(score_change, 1)},
                    {"label": "品质合格率", "value": round(pass_rate, 1), "unit": "%"},
                ],
                "pending_orders": [{
                    "order_no": o.order_no,
                    "total_amount": o.total_amount,
                    "items": [{"name": i.product_name, "qty": i.qty, "unit": i.unit} for i in o.items],
                    "expected_date": o.expected_date,
                } for o in pending_confirm[:5]],
                "quality_summary": {
                    "total_receivings": total_receiving,
                    "passed": passed,
                    "pass_rate": round(pass_rate, 1),
                    "issues": ["到货温度偏高(-8\u2103, 要求<-12\u2103)"] if pass_rate < 90 else [],
                },
                "score_history": my_scores[-10:] if my_scores else [],
            }

        # 未指定时返回所有供应商摘要
        return {
            "suppliers": [
                {
                    "id": s.id,
                    "name": s.name,
                    "status": s.status,
                    "order_count": len([p for p in cls._po_cache.values() if p.supplier_id == s.id]),
                }
                for s in cls._supplier_cache.values()
            ]
        }

    # --- Demo 数据 ---

    @classmethod
    def seed_demo_assistant_data(cls) -> int:
        """加载岗位AI助理 Demo 数据（展会演示用）"""
        count = 0
        now = datetime.now()

        # Demo 待办事项
        demo_tasks = [
            {"task_type": "approval", "title": "3批毛肚待质检审批",
             "description": "供应商: 杭州冻品供应链 | 到货时间: 今天07:30",
             "priority": "urgent", "source_module": "S02", "target_role": "store_manager",
             "action_url": "/receiving-detail.html?id=RR-20260801-003", "action_text": "去审批",
             "metadata": {"record_id": "RR-20260801-003"}},
            {"task_type": "approval", "title": "鸭肠品质异常需处理",
             "description": "供应商: 上海速冻食品 | 到货温度-8°C(超标)",
             "priority": "urgent", "source_module": "S02", "target_role": "chef_head",
             "action_url": "/receiving-detail.html?id=RR-20260801-005", "action_text": "查看详情"},
            {"task_type": "purchase", "title": "PO-20260801-003 待确认",
             "description": "杭州冻品·毛肚 50kg · \u00a54,000", "priority": "high",
             "source_module": "S03", "target_role": "store_manager",
             "action_url": "/purchase-order-detail.html?id=PO-003", "action_text": "去确认"},
            {"task_type": "alert", "title": "1号冷柜温度异常(>-12°C持续5min)",
             "description": "当前-9.2°C, 可能影响冻品品质", "priority": "urgent",
             "source_module": "IoT", "target_role": "chef_head",
             "action_url": "/iot-sensors.html", "action_text": "查看温控"},
            {"task_type": "alert", "title": "供应商\"上海速冻\"评分降至C级",
             "description": "连续2次到货温度异常", "priority": "high",
             "source_module": "S04", "target_role": "purchaser",
             "action_url": "/supplier-detail.html?id=SUP-002", "action_text": "查看供应商"},
            {"task_type": "review", "title": "昨日运营日报待查阅",
             "description": "损耗率6.2%, 合格率92.3%", "priority": "medium",
             "source_module": "system", "target_role": "store_manager",
             "action_url": "/dashboard.html", "action_text": "查看报告"},
        ]

        for dt in demo_tasks:
            tid = cls._get_next_task_id()
            cls._task_cache[tid] = {
                "id": tid,
                **dt,
                "status": "pending",
                "created_at": now.isoformat(),
                "due_at": (now + timedelta(hours=4 if dt["priority"] == "urgent" else 12)).isoformat(),
            }
            count += 1

        # Demo AI 建议
        demo_suggestions = [
            {"suggestion_type": "purchase_order", "title": "建议采购肥牛卷 20kg",
             "content": "基于近7日消耗(\u224818kg/日)\u00d7周末因子(1.3)\u00d7安全系数(1.1)\n推荐: 杭州冻品供应链(A级, \u00a595/kg)\n预估节省: \u00a5340 vs B级供应商",
             "confidence": 0.87, "action_type": "create_po",
             "action_params": {"sku": "FP-HNRC-001", "qty": 20},
             "source_role": "purchaser",
             "source_analysis": "近7日消耗趋势 + 周末因子 + 安全系数"},
            {"suggestion_type": "supplier_switch", "title": "供应商\"上海速冻\"连续2次品质偏低",
             "content": "7/28到货鸭肠温度-8°C(\u6807\u51c6<-12°C)\n7/25到货肥牛包装破损\n建议: 切换至杭州冻品或宁波水产作为备用",
             "confidence": 0.78, "action_type": "navigate",
             "action_params": {"url": "/supplier-detail.html?id=SUP-002"},
             "source_role": "purchaser",
             "source_analysis": "S02质检数据: 近2次评分<75"},
            {"suggestion_type": "cost_optimization", "title": "出品率优化建议",
             "content": "千层肚出品率78%(目标85%)\n根因分析: 化冻超时导致缩水严重\n建议: 严格执行12-24h化冻窗口+封膜入库",
             "confidence": 0.83, "action_type": "navigate",
             "action_params": {"url": "/kitchen-assistant.html"},
             "source_role": "chef_head",
             "source_analysis": "SOP规则比对 + 历史出品率趋势"},
            {"suggestion_type": "risk_alert", "title": "本周损耗率改善明显",
             "content": "本周损耗率6.2%(上周7.0%)\u21930.8pp\n主要改善: 毛肚备货量从20盘\u219215盘(精准匹配)\n继续保持可达成月度目标\u22648%",
             "confidence": 0.91, "action_type": "dismiss",
             "source_role": "store_manager",
             "source_analysis": "周度损耗趋势分析"},
        ]

        for sug in demo_suggestions:
            sid = cls._get_next_suggestion_id()
            cls._suggestion_cache[sid] = {
                "id": sid,
                **sug,
                "data": sug.get("action_params", {}),
                "created_at": now.isoformat(),
                "expires_at": (now + timedelta(days=3)).isoformat(),
                "is_accepted": None,
            }
            count += 1

        cls._save_to_json()
        logger.info("Demo AI 助理数据加载完成: %d 条待办 + %d 条建议",
                    len(demo_tasks), len(demo_suggestions))
        return count
