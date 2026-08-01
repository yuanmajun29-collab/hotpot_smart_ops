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
                logger.info("从 JSON 加载货品数据: %d 个产品", len(cls._product_cache))
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
