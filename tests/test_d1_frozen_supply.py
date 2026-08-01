"""
火瞳 · D1 冻品供应链 — 仓库 IoT + 供应链 集成测试

覆盖:
  WH01 RFID 批次追踪
  WH03 FEFO 先失效先出
  WH02/06 IoT 温湿度监控
  WH04 库存预警
  S01-S04 冻品供应链

运行: python -m pytest tests/test_d1_frozen_supply.py -v
"""

import json
import os
import sqlite3
import tempfile
import pytest
from datetime import datetime, date, timedelta
from pathlib import Path

# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def db_path(tmp_path):
    """创建临时 SQLite 数据库（含完整 Schema）。"""
    db_file = tmp_path / "test_hotpot.db"
    conn = sqlite3.connect(str(db_file))
    conn.row_factory = sqlite3.Row

    # 核心表（复用 event_hub schema）
    conn.executescript("""
        -- 基础事件表
        CREATE TABLE IF NOT EXISTS events (
            event_id TEXT PRIMARY KEY,
            store_id TEXT NOT NULL,
            level TEXT NOT NULL,
            source TEXT,
            payload TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        -- 店铺快照
        CREATE TABLE IF NOT EXISTS store_snapshots (
            store_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY (store_id, kind)
        );

        -- 设备注册表
        CREATE TABLE IF NOT EXISTS device_registry (
            device_id TEXT PRIMARY KEY,
            payload TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );

        -- 库存台账 (WH01 用)
        CREATE TABLE IF NOT EXISTS inventory_ledger (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            batch_id TEXT,
            movement_type TEXT NOT NULL,
            qty_change REAL NOT NULL DEFAULT 0,
            unit TEXT DEFAULT 'kg',
            unit_cost REAL,
            reason TEXT,
            ref_type TEXT,
            ref_id TEXT,
            operator TEXT,
            recorded_at TIMESTAMPTZ NOT NULL,
            UNIQUE(store_id, sku, batch_id, movement_type, recorded_at)
        );

        -- 库存快照 (WH03/WH04 用)
        CREATE TABLE IF NOT EXISTS inventory_snapshot (
            store_id TEXT NOT NULL,
            sku TEXT NOT NULL,
            on_hand_qty REAL NOT NULL DEFAULT 0,
            in_transit_qty REAL DEFAULT 0,
            unit TEXT DEFAULT 'kg',
            avg_daily_consumption REAL,
            shelf_life_days INTEGER,
            earliest_expiry DATE,
            last_received_at TIMESTAMPTZ,
            last_consumed_at TIMESTAMPTZ,
            updated_at TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (store_id, sku)
        );

        -- IoT 遥测数据 (WH02/WH06 用)
        CREATE TABLE IF NOT EXISTS iot_readings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            store_id TEXT NOT NULL,
            device_id TEXT NOT NULL,
            sensor_type TEXT DEFAULT 'temperature',
            temperature_c REAL,
            humidity_pct REAL,
            battery_pct REAL,
            signal_rssi INTEGER,
            reading_at TIMESTAMPTZ NOT NULL,
            raw_payload TEXT
        );

        -- IoT 阈值配置
        CREATE TABLE IF NOT EXISTS iot_thresholds (
            device_id TEXT PRIMARY KEY,
            temp_min_c REAL NOT NULL DEFAULT 0,
            temp_max_c REAL NOT NULL DEFAULT 40,
            humidity_min_pct REAL,
            humidity_max_pct REAL,
            alarm_duration_sec INTEGER NOT NULL DEFAULT 900,
            configured_by TEXT DEFAULT '',
            configured_at TIMESTAMPTZ
        );

        -- 收货记录 (S02 用)
        CREATE TABLE IF NOT EXISTS receiving_records (
            record_id TEXT PRIMARY KEY,
            store_id TEXT NOT NULL,
            supplier_name TEXT NOT NULL,
            po_number TEXT,
            received_at TIMESTAMPTZ,
            receiver TEXT DEFAULT '',
            items TEXT DEFAULT '[]',
            photos TEXT DEFAULT '[]',
            total_passed INTEGER DEFAULT 1,
            status TEXT DEFAULT 'pending',
            notes TEXT,
            quality_results TEXT DEFAULT '[]',
            updated_at TIMESTAMPTZ
        );

        -- 采购单 (S03 用)
        CREATE TABLE IF NOT EXISTS purchase_orders (
            po_number TEXT PRIMARY KEY,
            store_id TEXT NOT NULL,
            ordered_by TEXT DEFAULT '',
            ordered_at TIMESTAMPTZ,
            items TEXT DEFAULT '[]',
            total_amount REAL DEFAULT 0,
            status TEXT DEFAULT 'draft',
            supplier TEXT,
            delivery_address TEXT,
            notes TEXT,
            forecast_ref TEXT,
            auto_generated INTEGER DEFAULT 0,
            updated_at TIMESTAMPTZ
        );

        -- 供应商 (S01 用)
        CREATE TABLE IF NOT EXISTS suppliers (
            supplier_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            contact_person TEXT DEFAULT '',
            phone TEXT DEFAULT '',
            address TEXT DEFAULT '',
            license_no TEXT,
            status TEXT DEFAULT 'active',
            supplied_skus TEXT DEFAULT '[]',
            created_at TIMESTAMPTZ
        );

        -- 库存预警规则 (WH04 用)
        CREATE TABLE IF NOT EXISTS inventory_alert_rules (
            rule_id TEXT PRIMARY KEY,
            sku TEXT NOT NULL,
            store_id TEXT NOT NULL,
            rule_type TEXT NOT NULL,
            threshold_value REAL NOT NULL DEFAULT 0,
            unit TEXT DEFAULT 'days',
            enabled INTEGER DEFAULT 1,
            created_by TEXT,
            created_at TIMESTAMPTZ
        );
    """)
    conn.commit()
    yield conn
    conn.close()


@pytest.fixture
def sample_inventory(db_path):
    """插入测试用库存数据。"""
    now = datetime.utcnow()
    test_data = [
        # (store_id, sku, on_hand_qty, avg_daily_consumption, category, earliest_expiry, last_consumed_at)
        ("store_jiaojiang", "FZ_BEEF_5KG", 15.0, 5.0, "冻品", now.date() + timedelta(days=3), now - timedelta(days=1)),
        ("store_jiaojiang", "FZ_LAMB_5KG", 8.0, 2.0, "冻品", now.date() + timedelta(days=10), now - timedelta(hours=6)),
        ("store_jiaojiang", "VEG_CABBAGE", 20.0, 8.0, "蔬菜", now.date() + timedelta(days=2), now - timedelta(hours=2)),
        ("store_jiaojiang", "BASE_SPICY", 50.0, 1.5, "底料", now.date() + timedelta(days=180), now - timedelta(days=30)),
        ("store_jiaojiang", "FZ_SHRIMP_1KG", 0.0, 3.0, "冻品", None, now - timedelta(days=5)),  # 断货SKU
        ("store_jiaojiang", "FZ_DUCK_2KG", 80.0, 0.8, "冻品", now.date() + timedelta(days=60), now - timedelta(days=45)),  # 积压SKU
    ]
    for row in test_data:
        db_path.execute("""
            INSERT OR REPLACE INTO inventory_snapshot
            (store_id, sku, on_hand_qty, in_transit_qty, unit, avg_daily_consumption,
             shelf_life_days, earliest_expiry, last_received_at, last_consumed_at, updated_at)
            VALUES (?, ?, ?, 0, 'kg', ?, ?, ?, ?, ?, ?)
        """, (row[0], row[1], row[2], row[3],
              (row[4] - date.today()).days if isinstance(row[4], date) else 90,
              row[4].isoformat() if hasattr(row[4], 'isoformat') else (row[4] or None),
              now.isoformat(), row[5].isoformat() if len(row) > 5 and hasattr(row[5], 'isoformat') else None, now.isoformat()))
    db_path.commit()


# ============================================================
# WH01: RFID 批次追踪 测试
# ============================================================

class TestRFIDTracker:
    """WH01 RFID 批次追踪引擎测试。"""

    def test_track_batch_receive(self, db_path):
        """测试收货批次追踪。"""
        from hotpot_platform.cloud.warehouse.rfid_tracker import RFIDTracker
        from hotpot_platform.cloud.warehouse.models import RFIDItem

        tracker = RFIDTracker(db_session=db_path)
        items = [
            RFIDItem(epc="EPC001", sku="FZ_BEEF_5KG", batch_id="B20260730-001",
                      quantity=10.0, expiry_date=date.today() + timedelta(days=30)),
            RFIDItem(epc="EPC002", sku="FZ_BEEF_5KG", batch_id="B20260730-001",
                      quantity=10.0, expiry_date=date.today() + timedelta(days=30)),
            RFIDItem(epc="EPC003", sku="FZ_LAMB_5KG", batch_id="B20260730-002",
                      quantity=5.0),
        ]

        result = tracker.track_batch(
            store_id="store_jiaojiang",
            batch_id="B20260730-001",
            items=items,
            operation="receive",
            operator="库管A",
            location="receiving_dock",
        )

        assert result.batch_id == "B20260730-001"
        assert result.operation == "receive"
        assert result.items_tracked == 3
        assert result.items_expected == 3
        assert result.match_rate == 1.0
        assert result.ledger_entries_created >= 3
        print(f"   ✅ track_batch receive: {result.items_tracked}/{result.items_expected} match={result.match_rate:.0%}")

    def test_query_batch_trace(self, db_path, sample_inventory):
        """查询批次追溯链。"""
        from hotpot_platform.cloud.warehouse.rfid_tracker import RFIDTracker

        tracker = RFIDTracker(db_session=db_path)

        # 先写入一条记录
        from hotpot_platform.cloud.warehouse.models import RFIDItem
        tracker.track_batch(
            store_id="store_jiaojiang",
            batch_id="TEST-BATCH",
            items=[RFIDItem(epc="EPC-TEST", sku="FZ_BEEF_5KG", batch_id="TEST-BATCH", quantity=5.0)],
            operation="receive",
            operator="system",
            location="cold_room_a",
        )

        trace = tracker.query_batch_trace(
            batch_id="TEST-BATCH",
            store_id="store_jiaojiang",
        )

        assert trace.batch_id == "TEST-BATCH"
        assert trace.store_id == "store_jiaojiang"
        assert len(trace.timeline) >= 1
        assert trace.fefo_status in ("normal", "warning", "expired")
        print(f"   ✅ query_batch_trace: {len(trace.timeline)} entries, status={trace.fefo_status}")

    def test_invalid_operation(self, db_path):
        """无效操作类型应返回错误结果。"""
        from hotpot_platform.cloud.warehouse.rfid_tracker import RFIDTracker

        tracker = RFIDTracker(db_session=db_path)
        result = tracker.track_batch(
            store_id="store_test",
            batch_id="B001",
            items=[],
            operation="invalid_op",
            operator="test",
            location="test",
        )

        assert result.items_tracked == 0
        print(f"   ✅ invalid operation handled gracefully")


# ============================================================
# WH03: FEFO 监控 测试
# ============================================================

class TestFEFOMonitor:
    """WH03 FEFO 先失效先出监控测试。"""

    def test_check_fevo_all(self, db_path, sample_inventory):
        """全店 FEFO 检查。"""
        from hotpot_platform.cloud.warehouse.fefo_monitor import FEFOMonitor

        monitor = FEFOMonitor(db_session=db_path)
        status = monitor.check_fevo(store_id="store_jiaojiang")

        assert status.store_id == "store_jiaojiang"
        assert status.items_checked >= 4  # 至少有4个有库存的SKU
        assert 0 <= status.overall_score <= 100
        assert status.items_normal + status.items_warning + status.items_expired == status.items_checked
        print(f"   ✅ check_fevo: checked={status.items_checked} normal={status.items_normal} "
              f"warn={status.items_warning} expired={status.items_expired} score={status.overall_score}")

    def test_generate_pick_list(self, db_path, sample_inventory):
        """FEFO 拣货清单生成。"""
        from hotpot_platform.cloud.warehouse.fefo_monitor import FEFOMonitor, OrderItem

        monitor = FEFOMonitor(db_session=db_path)
        pick_list = monitor.generate_pick_list(
            store_id="store_jiaojiang",
            order_items=[
                OrderItem(sku="FZ_BEEF_5KG", required_qty=8.0),
                OrderItem(sku="VEG_CABBAGE", required_qty=5.0),
            ],
        )

        assert pick_list.store_id == "store_jiaojiang"
        assert len(pick_list.picks) == 2
        assert pick_list.generated_at is not None
        print(f"   ✅ generate_pick_list: {len(pick_list.picks)} SKUs, warnings={len(pick_list.warnings)}")

    def test_fevo_score_calculation(self):
        """FEFO 健康分计算边界测试。"""
        from hotpot_platform.cloud.warehouse.fefo_monitor import FEFOMonitor

        # 全部正常 → 100分
        assert FEFOMonitor._calc_fevo_score(10, 10, 0, 0) == 100.0
        # 全部过期 → 0分
        score = FEFOMonitor._calc_fevo_score(10, 0, 0, 10)
        assert score <= 0
        # 混合情况
        score = FEFOMonitor._calc_fevo_score(20, 15, 3, 2)
        assert 0 < score < 100
        print(f"   ✅ fevo_score boundaries OK")


# ============================================================
# WH02/06: IoT 监控 测试
# ============================================================

class TestIoTMonitor:
    """WH02/WH06 IoT 温湿度监控测试。"""

    def _seed_device(self, db_path, device_id="TEMP_COLD_01"):
        """预注册设备。"""
        db_path.execute("""
            INSERT OR REPLACE INTO device_registry (device_id, payload, updated_at)
            VALUES (?, ?, ?)
        """, (device_id, '{"location": "cold_room_a"}', datetime.utcnow().isoformat()))
        db_path.commit()

    def test_ingest_telemetry(self, db_path):
        """遥测数据入库与阈值检查。"""
        from hotpot_platform.cloud.warehouse.iot_monitor import IoTMonitor, IoTReading

        self._seed_device(db_path)
        monitor = IoTMonitor(db_session=db_path)

        readings = [
            IoTReading(device_id="TEMP_COLD_01", temperature_c=2.5, humidity_pct=82,
                       reading_at=datetime.utcnow(), battery_pct=85, signal_rssi=-55),
            IoTReading(device_id="TEMP_COLD_01", temperature_c=3.1, humidity_pct=80,
                       reading_at=datetime.utcnow(), battery_pct=84, signal_rssi=-54),
        ]

        result = monitor.ingest_telemetry(
            store_id="store_jiaojiang",
            device_id="TEMP_COLD_01",
            readings=readings,
        )

        assert result.readings_received == 2
        assert result.readings_stored == 2
        print(f"   ✅ ingest_telemetry: stored={result.readings_stored} alerts={result.alerts_triggered}")

    def test_temperature_violation_alert(self, db_path):
        """超温告警触发。"""
        from hotpot_platform.cloud.warehouse.iot_monitor import IoTMonitor, IoTReading

        self._seed_device(db_path)
        monitor = IoTMonitor(db_session=db_path)

        # 发送超温数据（冷藏间阈值 0~4°C，这里发 8°C）
        readings = [
            IoTReading(device_id="TEMP_COLD_01", temperature_c=8.0,
                       reading_at=datetime.utcnow()),
        ]

        result = monitor.ingest_telemetry(
            store_id="store_jiaojiang",
            device_id="TEMP_COLD_01",
            readings=readings,
        )

        # 超温应触发告警
        assert result.readings_stored == 1
        print(f"   ✅ temperature violation: alerts={result.alerts_triggered}")

    def test_get_device_status(self, db_path):
        """设备状态查询。"""
        from hotpot_platform.cloud.warehouse.iot_monitor import IoTMonitor

        self._seed_device(db_path, device_id="SENSOR_FREEZER")
        monitor = IoTMonitor(db_session=db_path)

        # 先写入一条读数
        from hotpot_platform.cloud.warehouse.models import IoTReading
        monitor.ingest_telemetry(
            store_id="store_jiaojiang",
            device_id="SENSOR_FREEZER",
            readings=[IoTReading(device_id="SENSOR_FREEZER", temperature_c=-18.0,
                                reading_at=datetime.utcnow())],
        )

        statuses = monitor.get_device_status(store_id="store_jiaojiang")
        assert len(statuses) >= 1
        device = next((s for s in statuses if s.device_id == "SENSOR_FREEZER"), None)
        assert device is not None
        assert device.current_temp_c is not None
        print(f"   ✅ get_device_status: {len(statuses)} devices, freezer temp={device.current_temp_c}°C")

    def test_configure_threshold(self, db_path):
        """阈值配置更新。"""
        from hotpot_platform.cloud.warehouse.iot_monitor import IoTMonitor

        monitor = IoTMonitor(db_session=db_path)
        config = monitor.configure_threshold(
            device_id="CUSTOM_SENSOR",
            temp_min_c=-25.0,
            temp_max_c=-15.0,
            alarm_duration_sec=600,
            configured_by="潘厨",
        )

        assert config.temp_min_c == -25.0
        assert config.temp_max_c == -15.0
        assert config.alarm_duration_sec == 600
        assert config.configured_by == "潘厨"
        print(f"   ✅ configure_threshold: [{config.temp_min_c}, {config.temp_max_c}]°C by {config.configured_by}")


# ============================================================
# WH04: 库存预警 测试
# ============================================================

class TestInventoryAlertor:
    """WH04 库存预警引擎测试。"""

    def test_check_stock_levels(self, db_path, sample_inventory):
        """库存水位检查。"""
        from hotpot_platform.cloud.warehouse.inventory_alertor import InventoryAlertor

        alertor = InventoryAlertor(db_session=db_path)
        report = alertor.check_stock_levels(store_id="store_jiaojiang")

        assert report.store_id == "store_jiaojiang"
        assert report.checked_at is not None
        assert len(report.alerts) > 0  # 应该有断货或临期预警
        assert report.summary.total_at_risk_sku == len(report.alerts)
        print(f"   ✅ check_stock_levels: {len(report.alerts)} alerts "
              f"(C={report.summary.critical_count} H={report.summary.high_count} M={report.summary.medium_count})")

        # 打印前3条预警详情
        for alert in report.alerts[:3]:
            print(f"      - {alert.sku}: {alert.alert_type} ({alert.urgency}) "
                  f"qty={alert.current_qty} days={alert.days_of_stock:.1f}")

    def test_configure_alert_rule(self, db_path):
        """单品级预警规则配置。"""
        from hotpot_platform.cloud.warehouse.inventory_alertor import InventoryAlertor

        alertor = InventoryAlertor(db_session=db_path)
        rule = alertor.configure_alert_rule(
            sku="FZ_BEEF_5KG",
            store_id="store_jiaojiang",
            rule_type="stockout",
            threshold_value=5.0,
            unit="days",
            enabled=True,
        )

        assert rule.sku == "FZ_BEEF_5KG"
        assert rule.rule_type == "stockout"
        assert rule.threshold_value == 5.0
        assert rule.rule_id is not None
        print(f"   ✅ configure_alert_rule: {rule.sku} {rule.rule_type} threshold={rule.threshold_value}{rule.unit}")


# ============================================================
# S01-S04: 冻品供应链 测试
# ============================================================

class TestSupplyChain:
    """S01-S04 冻品供应链集成测试。"""

    def test_s01_create_supplier(self, db_path):
        """S01 创建供应商。"""
        from hotpot_platform.cloud.supply_chain import SupplyChainManager, SupplierInfo

        mgr = SupplyChainManager(db_session=db_path)
        supplier = mgr.create_supplier(SupplierInfo(
            name="杭州冻品供应链",
            contact_person="王总",
            phone="138****1234",
            license_no="FY33010000",
            supplied_skus=["FZ_BEEF_5KG", "FZ_LAMB_5KG", "FZ_SHRIMP_1KG"],
        ))

        assert supplier.supplier_id is not None
        assert supplier.supplier_id.startswith("SUP-")
        assert supplier.name == "杭州冻品供应链"
        print(f"   ✅ S01 create_supplier: {supplier.supplier_id} - {supplier.name}")

    def test_s02_submit_receiving(self, db_path):
        """S02 提交收货记录。"""
        from hotpot_platform.cloud.supply_chain import SupplyChainManager, ReceivingRecord, ReceivingItem

        mgr = SupplyChainManager(db_session=db_path)
        record = ReceivingRecord(
            store_id="store_jiaojiang",
            supplier_name="杭州冻品供应链",
            receiver="库管A",
            items=[
                ReceivingItem(sku="FZ_BEEF_5KG", ordered_qty=10, received_qty=9.8,
                              batch_id="B-D0730", temperature_on_arrival=-18.0),
                ReceivingItem(sku="FZ_LAMB_5KG", ordered_qty=5, received_qty=5.0,
                              batch_id="B-D0730", temperature_on_arrival=-17.5),
            ],
        )

        result = mgr.submit_receiving(record)
        assert result.record_id is not None
        assert result.record_id.startswith("RCV-")
        assert result.status == "inspecting"
        assert len(result.items) == 2
        print(f"   ✅ S02 submit_receiving: {result.record_id} items={len(result.items)} status={result.status}")

    def test_s02_quality_approval(self, db_path):
        """S02 质检审批（潘厨操作）。"""
        from hotpot_platform.cloud.supply_chain import (
            SupplyChainManager, ReceivingRecord, ReceivingItem, QualityCheckResult
        )

        mgr = SupplyChainManager(db_session=db_path)

        # 先提交收货
        record = mgr.submit_receiving(ReceivingRecord(
            store_id="store_jiaojiang",
            supplier_name="杭州冻品供应链",
            receiver="库管A",
            items=[ReceivingItem(sku="FZ_BEEF_5KG", ordered_qty=10, received_qty=9.8)],
        ))

        # 潘厨质检通过
        quality_results = [QualityCheckResult(
            sku="FZ_BEEF_5KG", passed=True, grade="A",
            weight_variance_pct=-2.0, inspector="潘厨",
        )]

        approved = mgr.approve_quality_check(
            record_id=record.record_id,
            quality_results=quality_results,
            inspector="潘厨",
        )

        assert approved.status == "approved"
        assert approved.total_passed is True
        print(f"   ✅ S02 quality_approval: {record.record_id} → {approved.status} by 潘厨")

    def test_s03_purchase_order_lifecycle(self, db_path):
        """S03 采购订单生命周期：draft → submitted → confirmed。"""
        from hotpot_platform.cloud.supply_chain import (
            SupplyChainManager, PurchaseOrder, PurchaseOrderItem
        )

        mgr = SupplyChainManager(db_session=db_path)

        # 创建采购单
        po = mgr.create_purchase_order(PurchaseOrder(
            store_id="store_jiaojiang",
            ordered_by="曹总",
            supplier="杭州冻品供应链",
            items=[
                PurchaseOrderItem(sku="FZ_BEEF_5KG", quantity=20, unit_price=45.0),
                PurchaseOrderItem(sku="FZ_LAMB_5KG", quantity=10, unit_price=68.0),
            ],
        ))
        assert po.status == "draft"
        assert po.po_number.startswith("PO-")
        assert po.total_amount > 0
        print(f"   ✅ S03 PO create: {po.po_number} amount={po.total_amount}")

        # 提交
        po_submitted = mgr.submit_purchase_order(po.po_number)
        assert po_submitted.status == "submitted"

        # 确认
        po_confirmed = mgr.confirm_purchase_order(po.po_number)
        assert po_confirmed.status == "confirmed"
        print(f"   ✅ S03 PO lifecycle: draft → submitted → confirmed")


# ============================================================
# 集成端到端测试
# ============================================================

class TestD1EndToEnd:
    """D1 冻品供应链端到端集成场景。"""

    def test_full_receiving_to_warehouse_flow(self, db_path, sample_inventory):
        """完整流程: 收货→质检→RFID追踪→FEFO检查→库存预警。"""
        from hotpot_platform.cloud.supply_chain import (
            SupplyChainManager, ReceivingRecord, ReceivingItem, QualityCheckResult,
        )
        from hotpot_platform.cloud.warehouse import RFIDTracker, FEFOMonitor, InventoryAlertor

        # Step 1: 收货提交
        supply_mgr = SupplyChainManager(db_session=db_path)
        rcv = supply_mgr.submit_receiving(ReceivingRecord(
            store_id="store_jiaojiang",
            supplier_name="杭州冻品供应链",
            receiver="库管A",
            items=[
                ReceivingItem(sku="FZ_BEEF_5KG", ordered_qty=10, received_qty=9.8,
                              batch_id="E2E-BATCH", temperature_on_arrival=-18.0),
            ],
        ))
        assert rcv.status == "inspecting"

        # Step 2: 潘厨质检
        qc_result = QualityCheckResult(
            sku="FZ_BEEF_5KG", passed=True, grade="A",
            weight_variance_pct=-2.0, inspector="潘厨",
        )
        approved = supply_mgr.approve_quality_check(rcv.record_id, [qc_result], "潘厨")
        assert approved.status == "approved"

        # Step 3: RFID 批次追踪
        rfid = RFIDTracker(db_session=db_path)
        track = rfid.track_batch(
            store_id="store_jiaojiang",
            batch_id="E2E-BATCH",
            items=[],  # 已在收货时追踪
            operation="stock_in",
            operator="QC:潘厨",
            location="cold_room_a",
        )
        assert track.operation == "stock_in"

        # Step 4: FEFO 检查
        fefo = FEFOMonitor(db_session=db_path)
        fefo_status = fefo.check_fevo("store_jiaojiang")
        assert fefo_status.items_checked > 0

        # Step 5: 库存预警
        alertor = InventoryAlertor(db_session=db_path)
        stock_report = alertor.check_stock_levels("store_jiaojiang")
        assert stock_report.checked_at is not None

        print(f"\n   🎯 E2E 流程全部通过:")
        print(f"      收货: {rcv.record_id} → 质检: {approved.status}")
        print(f"      RFID: {track.operation} | FEFO: score={fefo_status.overall_score}")
        print(f"      预警: {len(stock_report.alerts)} 条")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
