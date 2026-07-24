"""
火瞳 · 数据引擎 — N03 库存台账 (Inventory Book)

InventoryBook 维护 per-SKU 实时库存水位, 消费视觉引擎损耗事件自动扣减,
支持每日盘点校准 (POS + 视觉 vs 理论库存), 并提供多维度库存告警。

库存变动来源:
    stock_in   → ERP 收货入库
    stock_out  → POS 销售出库
    waste      → 视觉 AI 损耗识别
    adjust     → 人工盘点调整
    transfer   → 门店间调拨

依赖: data_engine.models.InventoryMovement, InventorySnapshot
"""

from typing import Dict, List, Optional, Tuple
from datetime import date, datetime, timedelta
from collections import defaultdict

from .models import InventoryMovement, InventorySnapshot


# ---------------------------------------------------------------------------
# 常量
# ---------------------------------------------------------------------------

# 告警阈值
LOW_STOCK_DAYS = 2          # 库存不足 N 天销量时告警
EXPIRE_WARN_DAYS = 3        # 距最早到期日 ≤ N 天时告警
OVERSTOCK_DAYS = 14         # 库存超过 N 天销量时告警
CALIBRATION_DEVIATION_PCT = 5.0   # 盘点偏差超过 5% 时告警


# ---------------------------------------------------------------------------
# InventoryBook
# ---------------------------------------------------------------------------

class InventoryBook:
    """
    实时库存台账。

    外部数据特征:
        - ERP 推送 stock_in/transfer 事件 → record_movement()
        - POS 推送 stock_out 事件        → record_movement()
        - 视觉引擎推送 vlm_waste_estimate → consume_vision_event()

    内部自动维护 per-SKU 水位, 支持:
        - 实时库存快照查询
        - 多维度告警 (低库存 / 临期 / 积压)
        - 每日盘点校准 (理论 vs 实际偏差检测)

    用法:
        book = InventoryBook()
        book.record_movement(InventoryMovement(store_id="S001", sku="肥牛",
            movement_type="stock_in", qty_change=20.0))
        book.consume_vision_event({"store_id": "S001", "sku": "肥牛",
            "waste_qty_kg": 0.5, "timestamp": "2026-07-25T20:30:00"})
        status = book.get_inventory_status("S001")
        alerts = book.check_alerts("S001")
    """

    def __init__(self):
        # per-store, per-SKU 库存水位: {store_id: {sku: on_hand_qty}}
        self._inventory: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

        # per-store, per-SKU 批次信息: {store_id: {sku: [batch_dict, ...]}}
        self._batches: Dict[str, Dict[str, List[Dict]]] = defaultdict(lambda: defaultdict(list))

        # per-store, per-SKU 变动流水: {store_id: {sku: [movement, ...]}}
        self._movements: Dict[str, Dict[str, List[InventoryMovement]]] = defaultdict(
            lambda: defaultdict(list)
        )

        # per-store, per-SKU 日均消耗 (由内部自动维护或外部注入)
        self._avg_daily_consumption: Dict[str, Dict[str, float]] = defaultdict(lambda: defaultdict(float))

        # 日历告警: 避免对同一告警重复推送 (每日一次)
        self._last_alert_date: Dict[Tuple[str, str, str], date] = {}

    # ------------------------------------------------------------------
    # 库存水位查询
    # ------------------------------------------------------------------

    def get_inventory_status(self, store_id: str) -> List[InventorySnapshot]:
        """
        返回某门店所有 SKU 的实时库存快照。

        Args:
            store_id: 门店 ID

        Returns:
            InventorySnapshot 列表, 按 sku 排序。
        """
        store_inv = self._inventory.get(store_id, {})
        batches = self._batches.get(store_id, {})
        consumption = self._avg_daily_consumption.get(store_id, {})

        snapshots: List[InventorySnapshot] = []
        for sku, qty in sorted(store_inv.items()):
            snapshots.append(InventorySnapshot(
                store_id=store_id,
                sku=sku,
                on_hand_qty=round(qty, 3),
                in_transit_qty=0.0,   # TODO: 后续从 transfer 事件中追踪在途
                unit="kg",
                avg_daily_consumption=round(consumption.get(sku, 0), 3),
                shelf_life_days=self._compute_shelf_life(batches.get(sku, [])),
                earliest_expiry=self._earliest_expiry(batches.get(sku, [])),
            ))
        return snapshots

    # ------------------------------------------------------------------
    # 变动记录
    # ------------------------------------------------------------------

    def record_movement(self, movement: InventoryMovement) -> None:
        """
        记录一条库存变动并更新水位。

        stock_in  / transfer(in)  → 增加
        stock_out / waste / transfer(out) → 扣减
        adjust                     → 直接修正 (覆盖当前值或用 delta 调整)
        """
        store_id = movement.store_id
        sku = movement.sku
        qty = movement.qty_change
        mtype = movement.movement_type

        # 记录流水
        self._movements[store_id][sku].append(movement)

        # 更新水位
        if mtype in ("stock_in",):
            self._inventory[store_id][sku] += qty
        elif mtype in ("stock_out", "waste"):
            # 扣减, 但不能为负 (负数库存由校准纠正)
            self._inventory[store_id][sku] = max(0.0, self._inventory[store_id][sku] + qty)  # qty 为负
        elif mtype == "adjust":
            # adjust: qty_change 为实际库存值 (覆盖) 或 delta
            # 约定: 正值 = 调增, 负值 = 调减, 与 movement.reason 配合判断
            self._inventory[store_id][sku] += qty
            self._inventory[store_id][sku] = max(0.0, self._inventory[store_id][sku])
        elif mtype == "transfer":
            # 调拨: 当前门店视方向而定
            # transfer 本身不区分方向, 由 reason 字段指示 "in"/"out"
            reason = (movement.reason or "").lower()
            if reason == "out":
                self._inventory[store_id][sku] = max(0.0, self._inventory[store_id][sku] + qty)
            else:
                self._inventory[store_id][sku] += qty

        # 更新批次 (stock_in 携带批次信息时)
        if mtype == "stock_in" and movement.batch_id:
            self._upsert_batch(store_id, sku, movement)

    # ------------------------------------------------------------------
    # 视觉引擎事件消费
    # ------------------------------------------------------------------

    def consume_vision_event(self, event: Dict) -> Optional[InventoryMovement]:
        """
        消费视觉引擎的 vlm_waste_estimate 事件, 自动生成 waste 变动并扣减库存。

        Args:
            event: {
                "store_id": str,
                "sku": str,
                "waste_qty_kg": float,
                "timestamp": str (ISO 8601),
                "confidence": Optional[float] (0-1),
                "image_id": Optional[str],
                "reason": Optional[str],
            }

        Returns:
            生成的 InventoryMovement, 若数据无效则返回 None。
        """
        store_id = event.get("store_id")
        sku = event.get("sku")
        waste_qty = event.get("waste_qty_kg", 0.0)

        if not store_id or not sku or waste_qty <= 0:
            return None

        movement = InventoryMovement(
            store_id=store_id,
            sku=sku,
            movement_type="waste",
            qty_change=-waste_qty,          # 负值 = 出库
            unit="kg",
            reason=f"视觉引擎损耗检测 (confidence={event.get('confidence', 0.0):.2f})",
            ref_type="vlm_waste_estimate",
            ref_id=event.get("image_id"),
            recorded_at=datetime.fromisoformat(event["timestamp"]) if event.get("timestamp") else datetime.now(),
            operator="vision_engine",
        )
        self.record_movement(movement)
        return movement

    # ------------------------------------------------------------------
    # 告警
    # ------------------------------------------------------------------

    def check_alerts(self, store_id: str) -> List[Dict]:
        """
        对某门店执行全量告警检查。

        告警类型:
            - low_stock:      库存不足
            - near_expiry:    临期
            - overstock:      积压
            - negative_stock: 负库存 (异常)

        Returns:
            [{"type": str, "severity": str, "sku": str, "message": str, "detail": Dict}, ...]
        """
        alerts: List[Dict] = []
        today = date.today()

        snapshots = self.get_inventory_status(store_id)
        for snap in snapshots:
            # --- 负库存异常 (高优) ---
            if snap.on_hand_qty < 0:
                alerts.append({
                    "type": "negative_stock",
                    "severity": "critical",
                    "sku": snap.sku,
                    "message": f"[{snap.sku}] 负库存 {snap.on_hand_qty:.2f} kg — 数据异常, 立即盘点",
                    "detail": {"on_hand_qty": snap.on_hand_qty},
                })
                continue

            avg = snap.avg_daily_consumption or 0

            # --- 低库存 ---
            if avg > 0 and (snap.on_hand_qty / avg) <= LOW_STOCK_DAYS:
                alert_key = (store_id, snap.sku, "low_stock")
                if self._should_alert(alert_key, today):
                    alerts.append({
                        "type": "low_stock",
                        "severity": "warning",
                        "sku": snap.sku,
                        "message": (
                            f"[{snap.sku}] 库存仅 {snap.on_hand_qty:.2f} kg, "
                            f"不足 {LOW_STOCK_DAYS} 天销量 (日均 {avg:.2f} kg)"
                        ),
                        "detail": {
                            "on_hand_qty": snap.on_hand_qty,
                            "avg_daily_consumption": avg,
                            "days_remaining": round(snap.on_hand_qty / avg, 1) if avg else None,
                        },
                    })

            # --- 临期 ---
            if snap.shelf_life_days is not None and snap.shelf_life_days <= EXPIRE_WARN_DAYS:
                alert_key = (store_id, snap.sku, "near_expiry")
                if self._should_alert(alert_key, today):
                    alerts.append({
                        "type": "near_expiry",
                        "severity": "warning",
                        "sku": snap.sku,
                        "message": (
                            f"[{snap.sku}] 最早批次距到期仅 {snap.shelf_life_days} 天 "
                            f"(到期日: {snap.earliest_expiry})"
                        ),
                        "detail": {
                            "shelf_life_days": snap.shelf_life_days,
                            "earliest_expiry": snap.earliest_expiry,
                        },
                    })

            # --- 积压 ---
            if avg > 0 and (snap.on_hand_qty / avg) >= OVERSTOCK_DAYS:
                alert_key = (store_id, snap.sku, "overstock")
                if self._should_alert(alert_key, today):
                    alerts.append({
                        "type": "overstock",
                        "severity": "info",
                        "sku": snap.sku,
                        "message": (
                            f"[{snap.sku}] 库存 {snap.on_hand_qty:.2f} kg, "
                            f"超 {OVERSTOCK_DAYS} 天销量 (日均 {avg:.2f} kg), 建议减少订货"
                        ),
                        "detail": {
                            "on_hand_qty": snap.on_hand_qty,
                            "avg_daily_consumption": avg,
                            "days_coverage": round(snap.on_hand_qty / avg, 1) if avg else None,
                        },
                    })

        return alerts

    # ------------------------------------------------------------------
    # 每日盘点校准
    # ------------------------------------------------------------------

    def calibrate(self, store_id: str, calibration_date: Optional[date] = None) -> Dict:
        """
        每日盘点校准: POS 销量 + 视觉损耗 vs 理论库存。

        逻辑:
            理论库存 = 上期库存 + stock_in - stock_out - waste + adjust + net_transfer
            实际库存 = POS 销量推算 (或人工盘点值, 此方法假设视觉+POS 可推)
            偏差 %   = |理论 - 实际| / 理论 * 100
            偏差 > 5% → 告警

        Args:
            store_id:          门店 ID
            calibration_date:  校准日期 (默认今天)

        Returns:
            {
                "status": "ok" | "alert",
                "store_id": str,
                "date": str,
                "snapshots": [...],   # per-SKU 校准结果
                "alerts": [...],      # 偏差超标项
            }
        """
        cal_date = calibration_date or date.today()
        cal_start = cal_date - timedelta(days=1)  # 校准昨日到今日的变动
        cal_end = cal_date

        results: Dict = {
            "status": "ok",
            "store_id": store_id,
            "date": cal_date.isoformat(),
            "snapshots": [],
            "alerts": [],
        }

        store_movements = self._movements.get(store_id, {})
        store_inv = self._inventory.get(store_id, {})
        store_batches = self._batches.get(store_id, {})

        all_skus = set(store_inv.keys()) | set(store_movements.keys())

        for sku in sorted(all_skus):
            movements = store_movements.get(sku, [])

            # 理论库存: 当前水位
            theoretical = store_inv.get(sku, 0.0)

            # 实际库存: 从变动推算 (上期 + 本期净变动)
            # 取校准日之前的变动做基准
            prev_date_balance = self._balance_before(movements, cal_date)
            day_movements = self._net_movement_on(movements, cal_date)

            actual = prev_date_balance + day_movements

            # 偏差计算
            if theoretical > 0:
                deviation_pct = abs(theoretical - actual) / theoretical * 100
            elif actual > 0:
                deviation_pct = abs(theoretical - actual) / actual * 100
            else:
                deviation_pct = 0.0

            deviation_pct = round(deviation_pct, 2)

            snapshot = {
                "sku": sku,
                "theoretical_qty": round(theoretical, 3),
                "actual_qty": round(actual, 3),
                "deviation_pct": deviation_pct,
                "deviation_ok": deviation_pct <= CALIBRATION_DEVIATION_PCT,
            }
            results["snapshots"].append(snapshot)

            if deviation_pct > CALIBRATION_DEVIATION_PCT:
                results["alerts"].append({
                    "sku": sku,
                    "theoretical_qty": round(theoretical, 3),
                    "actual_qty": round(actual, 3),
                    "deviation_pct": deviation_pct,
                    "message": (
                        f"[{sku}] 盘点偏差 {deviation_pct}% > {CALIBRATION_DEVIATION_PCT}%: "
                        f"理论 {theoretical:.2f} kg, 实际 {actual:.2f} kg"
                    ),
                })

        if results["alerts"]:
            results["status"] = "alert"

        return results

    # ------------------------------------------------------------------
    # 批次管理 (内部)
    # ------------------------------------------------------------------

    def _upsert_batch(self, store_id: str, sku: str, movement: InventoryMovement) -> None:
        """入库时更新批次信息 (FIFO 追加)。"""
        batch = {
            "batch_id": movement.batch_id,
            "qty": movement.qty_change,
            "unit_cost": movement.unit_cost,
            "received_at": (movement.recorded_at or datetime.now()).isoformat(),
            # 保质期: 后续从 ERP 物料主数据补全, 此处默认 7 天
            "expiry_date": ((movement.recorded_at or datetime.now()) + timedelta(days=7)).date().isoformat(),
        }
        self._batches[store_id][sku].append(batch)

    @staticmethod
    def _compute_shelf_life(batches: List[Dict]) -> Optional[int]:
        """最近批次距到期天数。"""
        if not batches:
            return None
        today = date.today()
        min_days = None
        for b in batches:
            try:
                exp = date.fromisoformat(b.get("expiry_date", ""))
                days = (exp - today).days
                if min_days is None or days < min_days:
                    min_days = days
            except (ValueError, TypeError):
                continue
        return min_days

    @staticmethod
    def _earliest_expiry(batches: List[Dict]) -> Optional[str]:
        """最早到期日。"""
        if not batches:
            return None
        expiries = [b.get("expiry_date") for b in batches if b.get("expiry_date")]
        if not expiries:
            return None
        return min(expiries)

    # ------------------------------------------------------------------
    # 辅助
    # ------------------------------------------------------------------

    def _should_alert(self, alert_key: Tuple[str, str, str], today: date) -> bool:
        """同日同告警仅触发一次。"""
        last = self._last_alert_date.get(alert_key)
        if last == today:
            return False
        self._last_alert_date[alert_key] = today
        return True

    @staticmethod
    def _balance_before(movements: List[InventoryMovement], target_date: date) -> float:
        """计算 target_date 之前的累计余额。"""
        balance = 0.0
        for m in movements:
            m_date = (m.recorded_at or datetime.min).date()
            if m_date < target_date:
                balance += m.qty_change
        return balance

    @staticmethod
    def _net_movement_on(movements: List[InventoryMovement], target_date: date) -> float:
        """计算 target_date 当天的净变动。"""
        net = 0.0
        for m in movements:
            m_date = (m.recorded_at or datetime.min).date()
            if m_date == target_date:
                net += m.qty_change
        return net
