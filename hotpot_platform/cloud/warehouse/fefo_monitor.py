"""
火瞳 · 仓库 IoT — FEFO 先失效先出监控引擎 (WH03 + WH05)

对应 PRD:
  WH03: FEFO 先失效先出策略
  WH05: 效期管理与预警
架构规范: 详细架构 v1.1 §1.8.2
模块路径: hotpot_platform.cloud.warehouse.fefo_monitor

触发机制:
  - 定时任务 (每15分钟)
  - 库存变动事件 (inventory_ledger INSERT 触发)
输出:
  - FEFO 告警 (Event Hub)
  - 出库建议 (API)
"""

from __future__ import annotations

import logging
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any

from hotpot_platform.cloud.warehouse.models import (
    FEFORecommendation,
    FEVOStatus,
    PickList,
    PickAllocation,
    Allocation,
    OrderItem,
)

logger = logging.getLogger(__name__)

# FEFO 阈值常量
DAYS_NORMAL_MIN = 7      # >7天: 正常
DAYS_WARNING_MAX = 7     # 1~7天: 警告
DAYS_EXPIRED_MAX = 0     # <=0天: 已过期


class FEFOMonitor:
    """先失效先出(FEFO)监控引擎 — 对接 PRD WH03 + WH05

    负责:
      1. 检查全店/单SKU的 FEFO 状态
      2. 生成 FEFO 拣货清单（优先出库最早过期批次）
      3. 计算整体 FEFO 健康分
      4. 效期预警推送
    """

    def __init__(self, db_session, alert_gateway=None) -> None:
        self._db = db_session
        self._alerts = alert_gateway

    # ---- 核心方法 ----

    def check_fevo(
        self,
        store_id: str,
        sku: Optional[str] = None,
    ) -> FEVOStatus:
        """检查 FEFO 状态。

        Args:
            store_id: 门店标识
            sku: 可选，指定SKU检查；None=检查全部

        Returns:
            FEVOStatus 含正常/警告/过期分类统计 + 出库建议列表 + 健康分
        """
        now = datetime.utcnow()

        # 1. 查询库存快照（含效期信息）
        rows = self._query_inventory_with_expiry(store_id, sku)

        items_checked = len(rows)
        items_normal = 0
        items_warning = 0
        items_expired = 0
        recommendations: List[FEFORecommendation] = []

        for row in rows:
            row_sku = row["sku"]
            earliest_expiry_str = row.get("earliest_expiry")
            on_hand_qty = row.get("on_hand_qty", 0) or 0

            if not earliest_expiry_str or on_hand_qty <= 0:
                items_normal += 1
                continue

            try:
                earliest_expiry = date.fromisoformat(str(earliest_expiry_str)[:10])
            except (ValueError, TypeError):
                items_normal += 1
                continue

            remaining_days = (earliest_expiry - date.today()).days
            batch_id = row.get("batch_id", "unknown")

            # 分类计数
            if remaining_days <= DAYS_EXPIRED_MAX:
                items_expired += 1
                action = "discard"
                priority = 1
            elif remaining_days <= DAYS_WARNING_MAX:
                items_warning += 1
                action = "consume_first"
                priority = min(remaining_days, 7)
            else:
                items_normal += 1
                action = "consume_first"  # 正常也按FEFO排序，优先早过期
                priority = max(8, remaining_days)

            recommendations.append(FEFORecommendation(
                sku=row_sku,
                batch_id=batch_id,
                expiry_date=earliest_expiry,
                days_remaining=remaining_days,
                on_hand_qty=on_hand_qty,
                action=action,
                priority=priority,
            ))

        # 2. 按优先级排序（最紧急在前）
        recommendations.sort(key=lambda r: r.priority)

        # 3. 计算健康分
        overall_score = self._calc_fevo_score(
            items_checked, items_normal, items_warning, items_expired
        )

        status = FEVOStatus(
            store_id=store_id,
            checked_at=now,
            items_checked=items_checked,
            items_normal=items_normal,
            items_warning=items_warning,
            items_expired=items_expired,
            recommendations=recommendations,
            overall_score=overall_score,
        )

        # 4. 有过期或大量警告时触发告警
        if items_expired > 0 or items_warning >= 5:
            self._emit_fevo_alert(store_id, status)

        logger.info(
            "FEVO检查完成 store=%s sku=%s normal=%d warn=%d expired=%d score=%.1f",
            store_id, sku or "*", items_normal, items_warning, items_expired, overall_score,
        )
        return status

    def generate_pick_list(
        self,
        store_id: str,
        order_items: List[OrderItem],
    ) -> PickList:
        """生成 FEFO 拣货清单。

        策略: 优先选择最早过期的批次，确保先失效先出。
        当某 SKU 无法满足 FEFO 时记录 warning。

        Args:
            store_id: 门店标识
            order_items: 需要拣货的商品清单

        Returns:
            PickList 含每个 SKU 的批次分配明细
        """
        now = datetime.utcnow()
        picks: List[PickAllocation] = []
        warnings: List[str] = []

        for item in order_items:
            required_qty = item.required_qty
            if required_qty <= 0:
                continue

            # 查询该 SKU 所有可用批次（按效期升序 → 最早过期优先）
            batches = self._query_batches_by_expiry(store_id, item.sku)

            allocations: List[Allocation] = []
            remaining = required_qty

            for batch in batches:
                if remaining <= 0:
                    break

                available = batch.get("available_qty", 0) or 0
                alloc_qty = min(remaining, available)

                allocations.append(Allocation(
                    batch_id=batch.get("batch_id", "unknown"),
                    qty=alloc_qty,
                    expiry_date=self._parse_date(batch.get("expiry_date")),
                    location=batch.get("location", "unknown"),
                ))
                remaining -= alloc_qty

            picks.append(PickAllocation(
                sku=item.sku,
                required_qty=required_qty,
                allocations=allocations,
            ))

            if remaining > 0:
                warnings.append(
                    f"SKU {item.sku} 缺货 {remaining:.2f}{item.unit or 'kg'}，"
                    f"无法满足 FEFO 拣货需求"
                )

        pick_list = PickList(
            store_id=store_id,
            generated_at=now,
            picks=picks,
            warnings=warnings,
        )

        logger.info(
            "FEFO拣货清单生成 store=%s items=%d warnings=%d",
            store_id, len(order_items), len(warnings),
        )
        return pick_list

    # ---- 内部方法 ----

    def _query_inventory_with_expiry(
        self, store_id: str, sku: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """查询库存快照（含效期信息）。"""
        if sku:
            sql = """
                SELECT * FROM inventory_snapshot
                WHERE store_id = ? AND sku = ? AND on_hand_qty > 0
                ORDER BY earliest_expiry ASC
            """
            cursor = self._db.execute(sql, (store_id, sku))
        else:
            sql = """
                SELECT * FROM inventory_snapshot
                WHERE store_id = ? AND on_hand_qty > 0
                ORDER BY earliest_expiry ASC
            """
            cursor = self._db.execute(sql, (store_id,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    def _query_batches_by_expiry(
        self, store_id: str, sku: str
    ) -> List[Dict[str, Any]]:
        """查询指定 SKU 的所有可用批次，按效期升序排列。"""
        # 从 inventory_ledger 聚合各批次当前余额
        sql = """
            SELECT
                batch_id,
                SUM(CASE WHEN qty_change > 0 THEN qty_change ELSE 0 END) as total_in,
                SUM(CASE WHEN qty_change < 0 THEN ABS(qty_change) ELSE 0 END) as total_out,
                MIN(recorded_at) as first_received,
                MAX(recorded_at) as last_movement
            FROM inventory_ledger
            WHERE store_id = ? AND sku = ?
            GROUP BY batch_id
            ORDER BY first_received ASC
        """
        cursor = self._db.execute(sql, (store_id, sku))
        columns = [desc[0] for desc in cursor.description]
        raw_rows = [dict(zip(columns, row)) for row in cursor.fetchall()]

        # 计算可用量并补充效期信息
        result = []
        for r in raw_rows:
            total_in = r.get("total_in", 0) or 0
            total_out = r.get("total_out", 0) or 0
            available = total_in - total_out
            if available <= 0:
                continue
            r["available_qty"] = available
            # 尝试从 snapshot 获取效期
            exp_row = self._db.execute(
                "SELECT earliest_expiry FROM inventory_snapshot WHERE store_id=? AND sku=?",
                (store_id, sku),
            ).fetchone()
            r["expiry_date"] = exp_row[0] if exp_row else None
            result.append(r)

        return result

    @staticmethod
    def _calc_fevo_score(
        checked: int, normal: int, warning: int, expired: int
    ) -> float:
        """计算 FEFO 健康分 (0-100)。"""
        if checked == 0:
            return 100.0
        # 基础分 = 正常占比 * 100
        score = (normal / checked) * 100
        # 过期每个扣15分，警告每个扣5分
        score -= expired * 15
        score -= warning * 5
        return max(0.0, min(100.0, round(score, 1)))

    @staticmethod
    def _parse_date(value: Optional[str]) -> Optional[date]:
        """安全解析日期字符串。"""
        if not value:
            return None
        try:
            return date.fromisoformat(str(value)[:10])
        except (ValueError, TypeError):
            return None

    def _emit_fevo_alert(self, store_id: str, status: FEVOStatus) -> None:
        """发送 FEFO 告警到 EventHub / AlertGateway。"""
        if self._alerts is None:
            return
        try:
            level = "critical" if status.items_expired > 0 else "warn"
            summary = (
                f"门店 {store_id} FEFO 告警: "
                f"{status.items_expired}件已过期, "
                f"{status.items_warning}件即将过期"
            )
            # 通过 alert_gateway 或 event_hub 发送
            if hasattr(self._alerts, "emit"):
                self._alerts.emit({
                    "alert_type": "fefo_violation",
                    "level": level,
                    "source": "warehouse",
                    "store_id": store_id,
                    "summary": summary,
                    "detail": {
                        "overall_score": status.overall_score,
                        "items_expired": status.items_expired,
                        "items_warning": status.items_warning,
                        "recommendations": [
                            r.model_dump() for r in status.recommendations[:10]
                        ],
                    },
                })
            logger.info("FEFO告警已发送 store=%s level=%s", store_id, level)
        except Exception as e:
            logger.error("FEFO告警发送失败: %s", e)
