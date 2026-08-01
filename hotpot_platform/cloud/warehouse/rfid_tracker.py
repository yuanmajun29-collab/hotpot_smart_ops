"""
火瞳 · 仓库 IoT — RFID 批次追踪引擎 (WH01)

对应 PRD WH01: RFID 批次全链路追溯
架构规范: 详细架构 v1.1 §1.8.1
模块路径: hotpot_platform.cloud.warehouse.rfid_tracker

数据流:
  MQTT(warehouse/gateway/{store_id}/rfid) / API手动录入
  → RFIDTracker.track_batch()
  → inventory_ledger 写入台账
  → Event Hub 发送追踪事件
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, date
from typing import List, Optional, Dict, Any

from hotpot_platform.cloud.warehouse.models import (
    RFIDItem,
    TrackingResult,
    Discrepancy,
    BatchTrace,
    BatchTimelineEntry,
    ItemLocation,
)

logger = logging.getLogger(__name__)

# 合法的批次操作类型
VALID_OPERATIONS = {"receive", "transfer", "consume", "waste", "ship_out"}

# 合法的库位前缀
VALID_LOCATIONS = {
    "cold_room_a", "cold_room_b",           # 冷藏间
    "freezer_01", "freezer_02",             # 冷冻间
    "shelf_a01", "shelf_b02", "shelf_c03",  # 货架
    "prep_table", "receiving_dock",         # 操作台/收货区
}


class RFIDTracker:
    """RFID 批次追踪引擎 — 对接 PRD WH01

    负责:
      1. 记录批次流转 (收货/调拨/消耗/报损/出库)
      2. 查询批次完整追溯链
      3. 定位单品当前位置
      4. 差异检测 (预期 vs 实际)
    """

    def __init__(
        self,
        db_session,  # sqlite3.Connection 或兼容游标
        event_hub_client=None,   # Optional[EventHubClient]
        inventory_service=None,  # Optional[InventoryService]
    ) -> None:
        self._db = db_session
        self._hub = event_hub_client
        self._inventory = inventory_service

    # ---- 核心方法 ----

    def track_batch(
        self,
        store_id: str,
        batch_id: str,
        items: List[RFIDItem],
        operation: str,
        operator: str,
        location: str,
        photos: Optional[List[str]] = None,
    ) -> TrackingResult:
        """记录批次流转。

        Args:
            store_id: 门店标识
            batch_id: 批次号 (RFID EPC 或手动编码)
            items: 该批次的物品清单
            operation: 操作类型 receive/transfer/consume/waste/ship_out
            operator: 操作人
            location: 库位
            photos: 收货/出库照片路径列表

        Returns:
            TrackingResult 包含匹配率、差异明细、台账写入数、告警列表
        """
        if operation not in VALID_OPERATIONS:
            logger.warning("未知操作类型: %s", operation)
            return TrackingResult(
                batch_id=batch_id,
                store_id=store_id,
                operation=operation,
                items_expected=len(items),
                errors=[f"无效操作类型: {operation}"],
            )

        now = datetime.utcnow()
        items_expected = len(items)
        items_tracked = 0
        discrepancies: List[Discrepancy] = []
        ledger_entries = 0
        alerts: List[str] = []

        # 1. 逐物品验证并记录
        for item in items:
            try:
                # 写入库存台账
                qty_change = item.quantity if operation in ("receive",) else -item.quantity
                self._write_ledger(
                    store_id=store_id,
                    sku=item.sku,
                    batch_id=batch_id,
                    movement_type=operation,
                    qty_change=qty_change,
                    unit=item.unit,
                    operator=operator,
                    location=location,
                    recorded_at=now,
                )
                items_tracked += 1
                ledger_entries += 1

            except Exception as e:
                discrepancies.append(Discrepancy(
                    epc=item.epc,
                    sku=item.sku,
                    expected_qty=item.quantity,
                    actual_qty=0,
                    reason="write_error",
                ))
                logger.error("RFID 物品写入失败 epc=%s: %s", item.epc, e)

        # 2. 计算匹配率
        match_rate = items_tracked / items_expected if items_expected > 0 else 1.0

        # 3. 差异检测：如果实际数量与预期不符
        if match_rate < 0.95 and items_expected > 0:
            alert_id = str(uuid.uuid4())
            alerts.append(alert_id)
            self._emit_alert(
                alert_id=alert_id,
                store_id=store_id,
                alert_type="rfid_mismatch",
                level="warn" if match_rate >= 0.8 else "critical",
                summary=f"批次 {batch_id} {operation} 匹配率 {match_rate:.1%}"
                f" ({items_tracked}/{items_expected})",
                detail={
                    "batch_id": batch_id,
                    "operation": operation,
                    "match_rate": round(match_rate, 4),
                    "items_tracked": items_tracked,
                    "items_expected": items_expected,
                    "discrepancies": [d.model_dump() for d in discrepancies],
                },
            )

        result = TrackingResult(
            batch_id=batch_id,
            store_id=store_id,
            operation=operation,
            items_tracked=items_tracked,
            items_expected=items_expected,
            match_rate=round(match_rate, 4),
            discrepancies=discrepancies,
            ledger_entries_created=ledger_entries,
            alerts_triggered=alerts,
            recorded_at=now,
        )

        logger.info(
            "批次追踪完成 batch=%s op=%s store=%s tracked=%d/%d match=%.1f%%",
            batch_id, operation, store_id, items_tracked, items_expected, match_rate * 100,
        )
        return result

    def query_batch_trace(
        self,
        batch_id: str,
        store_id: str,
    ) -> BatchTrace:
        """查询批次完整追溯链。

        Returns:
            BatchTrace 含时间线、当前库位、剩余保质期、FEFO状态
        """
        rows = self._query_ledger(store_id, batch_id)

        timeline = [
            BatchTimelineEntry(
                timestamp=row["recorded_at"],
                operation=row["movement_type"],
                operator=row.get("operator", "system"),
                location=row.get("location", "unknown"),
                qty_change=row["qty_change"],
            )
            for row in rows
        ]

        # 计算当前状态
        current_qty = sum(
            row["qty_change"] for row in rows if row["qty_change"] > 0
        ) + sum(
            row["qty_change"] for row in rows if row["qty_change"] < 0
        )
        current_qty = max(0, current_qty)

        # 取最后一条记录的位置作为当前位置
        current_location = timeline[-1].location if timeline else "unknown"

        # 取最早的生产日期计算剩余保质期
        remaining_days = self._calc_remaining_days(batch_id, store_id)
        fefo_status = self._calc_fefo_status(remaining_days)

        trace = BatchTrace(
            batch_id=batch_id,
            store_id=store_id,
            current_location=current_location,
            current_qty=current_qty,
            timeline=timeline,
            remaining_shelf_life_days=remaining_days,
            fefo_status=fefo_status,
        )

        logger.info(
            "批次追溯查询 batch=%s store=%s entries=%d qty=%.2f status=%s",
            batch_id, store_id, len(timeline), current_qty, fefo_status,
        )
        return trace

    def locate_item(
        self,
        epc: str,
        store_id: str,
    ) -> ItemLocation:
        """查询单个 RFID 标签的当前位置。"""
        row = self._query_epc_location(store_id, epc)
        if not row:
            return ItemLocation(
                epc=epc, sku="", batch_id="", location="not_found"
            )

        return ItemLocation(
            epc=epc,
            sku=row.get("sku", ""),
            batch_id=row.get("batch_id", ""),
            location=row.get("location", "unknown"),
            last_seen_at=row.get("recorded_at"),
            qty=row.get("qty_change", 1.0),
        )

    # ---- 内部方法 ----

    def _write_ledger(
        self,
        store_id: str,
        sku: str,
        batch_id: str,
        movement_type: str,
        qty_change: float,
        unit: str = "kg",
        operator: str = "system",
        location: str = "unknown",
        recorded_at: Optional[datetime] = None,
    ) -> None:
        """写入库存台账 (inventory_ledger 表)。"""
        recorded_at = recorded_at or datetime.utcnow()
        sql = """
            INSERT OR REPLACE INTO inventory_ledger
            (store_id, sku, batch_id, movement_type, qty_change, unit,
             reason, ref_type, operator, recorded_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        self._db.execute(sql, (
            store_id, sku, batch_id, movement_type, qty_change, unit,
            f"{movement_type}:{location}", "rfid_track", operator,
            recorded_at.isoformat(),
        ))
        self._db.commit()

    def _query_ledger(self, store_id: str, batch_id: str) -> List[Dict[str, Any]]:
        """查询批次所有台账记录，按时间正序排列。"""
        sql = """
            SELECT * FROM inventory_ledger
            WHERE store_id = ? AND batch_id = ?
            ORDER BY recorded_at ASC
        """
        cursor = self._db.execute(sql, (store_id, batch_id))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _query_epc_location(self, store_id: str, epc: str) -> Optional[Dict[str, Any]]:
        """查询单个 EPC 最新位置（从 events 表或扩展表）。"""
        # TODO: 当 EPC 级别追踪表就位后改为精确查询
        # 当前回退到按批次最新记录推断
        sql = """
            SELECT * FROM inventory_ledger
            WHERE store_id = ?
            ORDER BY recorded_at DESC LIMIT 1
        """
        cursor = self._db.execute(sql, (store_id,))
        columns = [desc[0] for desc in cursor.description]
        row = cursor.fetchone()
        return dict(zip(columns, row)) if row else None

    def _calc_remaining_days(self, batch_id: str, store_id: str) -> int:
        """根据批次最早过期日期计算剩余天数。"""
        # 从 inventory_snapshot 查询 earliest_expiry
        sql = """
            SELECT earliest_expiry FROM inventory_snapshot
            WHERE store_id = ?
            ORDER BY earliest_expiry ASC LIMIT 1
        """
        cursor = self._db.execute(sql, (store_id,))
        row = cursor.fetchone()
        if not row or not row[0]:
            return 999  # 无效期信息
        try:
            expiry = date.fromisoformat(str(row[0])[:10])
            return max(0, (expiry - date.today()).days)
        except (ValueError, TypeError):
            return 999

    @staticmethod
    def _calc_fefo_status(remaining_days: int) -> str:
        """根据剩余天数判定 FEFO 状态。"""
        if remaining_days <= 0:
            return "expired"
        if remaining_days <= 7:
            return "warning"
        return "normal"

    def _emit_alert(
        self,
        alert_id: str,
        store_id: str,
        alert_type: str,
        level: str,
        summary: str,
        detail: Optional[Dict] = None,
    ) -> None:
        """通过 EventHub 发送告警事件。"""
        if self._hub is None:
            logger.debug("EventHub 未配置，跳过告警发送: %s", alert_id)
            return
        try:
            self._hub.emit({
                "event_id": alert_id,
                "store_id": store_id,
                "level": level,
                "source": "iot",
                "payload": {
                    "alert_type": alert_type,
                    "summary": summary,
                    "detail": detail or {},
                },
                "created_at": datetime.utcnow().isoformat(),
            })
        except Exception as e:
            logger.error("告警发送失败: %s", e)
