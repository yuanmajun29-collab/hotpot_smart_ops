"""
火瞳 · 仓库 IoT — 库存预警引擎 (WH04)

对应 PRD WH04: 多维度库存水位监控与智能预警
架构规范: 详细架构 v1.1 §1.8.4
模块路径: hotpot_platform.cloud.warehouse.inventory_alertor

触发机制:
  - 库存快照变更事件
  - 定时任务 (每日 9:00)
输出:
  - Event Hub warn / critical 事件
  - API 查询接口
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, date, timedelta
from typing import List, Optional, Dict, Any

from hotpot_platform.cloud.warehouse.models import (
    StockAlertItem,
    StockAlertSummary,
    StockAlertReport,
    AlertRule,
)

logger = logging.getLogger(__name__)

# 默认预警规则
DEFAULT_RULES = {
    "stockout": {"threshold": 3.0, "unit": "days"},      # 库存不足3天
    "overstock": {"threshold": 30.0, "unit": "days"},     # 库存超30天
    "expiring": {"threshold": 7.0, "unit": "days"},       # 7天内过期
    "slow_moving": {"threshold": 14.0, "unit": "days"},   # 14天无动销
}


class InventoryAlertor:
    """库存预警引擎 — 对接 PRD WH04

    负责:
      1. 检查全店库存水位（断货/积压/滞销/临期）
      2. 计算安全库存、可销售天数、建议订货量
      3. 配置单品级预警规则
      4. 推送分级告警到 EventHub
    """

    def __init__(self, db_session, alert_gateway=None) -> None:
        self._db = db_session
        self._alerts = alert_gateway

    # ---- 核心方法 ----

    def check_stock_levels(self, store_id: str) -> StockAlertReport:
        """检查库存水位。

        Returns:
            StockAlertReport 含各 SKU 预警明细 + 汇总统计
        """
        now = datetime.utcnow()

        # 1. 获取全店库存快照
        snapshots = self._query_all_snapshots(store_id)

        alerts: List[StockAlertItem] = []
        critical_count = 0
        high_count = 0
        medium_count = 0

        for snap in snapshots:
            sku = snap.get("sku", "")
            on_hand = snap.get("on_hand_qty", 0) or 0
            daily_avg = snap.get("avg_daily_consumption") or 0
            category = snap.get("category")
            earliest_expiry_str = snap.get("earliest_expiry")

            # 跳过无动销或零库存的SKU
            if on_hand <= 0 and daily_avg <= 0:
                continue

            # 计算核心指标
            days_of_stock = round(daily_avg / on_hand, 2) if daily_avg > 0 and on_hand > 0 else 999
            safety_stock = self._calc_safety_stock(snap)

            # 检查各项预警条件
            item_alerts = self._evaluate_sku(
                store_id=store_id,
                sku=sku,
                snapshot=snap,
                on_hand=on_hand,
                daily_avg=daily_avg,
                days_of_stock=days_of_stock,
                safety_stock=safety_stock,
                earliest_expiry_str=earliest_expiry_str,
            )

            for alert in item_alerts:
                alerts.append(alert)
                if alert.urgency == "critical":
                    critical_count += 1
                elif alert.urgency == "high":
                    high_count += 1
                else:
                    medium_count += 1

        # 按 urgency 排序（critical 在前）
        alerts.sort(key=lambda a: {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(a.urgency, 4))

        report = StockAlertReport(
            store_id=store_id,
            checked_at=now,
            alerts=alerts,
            summary=StockAlertSummary(
                critical_count=critical_count,
                high_count=high_count,
                medium_count=medium_count,
                total_at_risk_sku=len(alerts),
            ),
        )

        # 有 critical 级别告警时立即推送
        if critical_count > 0:
            self._emit_stock_alert(report, level_filter="critical")
        elif high_count >= 3:
            self._emit_stock_alert(report, level_filter="high")

        logger.info(
            "库存预警检查完成 store=%s total=%d (C=%d H=%d M=%d)",
            store_id, len(alerts), critical_count, high_count, medium_count,
        )
        return report

    def configure_alert_rule(
        self,
        sku: str,
        store_id: str,
        rule_type: str,
        threshold_value: float,
        unit: str = "days",
        enabled: bool = True,
    ) -> AlertRule:
        """配置单品级预警规则。

        Args:
            sku: 商品编码
            store_id: 门店标识
            rule_type: stockout / overstock / expiring
            threshold_value: 阈值
            unit: days / qty / pct
            enabled: 是否启用

        Returns:
            AlertRule 已保存的规则配置
        """
        rule_id = str(uuid.uuid4())
        now = datetime.utcnow()

        rule = AlertRule(
            rule_id=rule_id,
            sku=sku,
            store_id=store_id,
            rule_type=rule_type,
            threshold_value=threshold_value,
            unit=unit,
            enabled=enabled,
            created_at=now,
        )

        # 持久化到 inventory_alert_rules 表
        sql = """
            INSERT OR REPLACE INTO inventory_alert_rules
            (rule_id, sku, store_id, rule_type, threshold_value, unit, enabled, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """
        try:
            self._db.execute(sql, (
                rule_id, sku, store_id, rule_type,
                threshold_value, unit, int(enabled), now.isoformat(),
            ))
            self._db.commit()
        except Exception as e:
            logger.error("预警规则保存失败: %s", e)
            # 表可能不存在，忽略写入错误（DEV模式）

        logger.info(
            "预警规则配置 %s sku=%s type=%s threshold=%.1f%s",
            rule_id[:8], sku, rule_type, threshold_value, unit,
        )
        return rule

    # ---- 内部方法 ----

    def _query_all_snapshots(self, store_id: str) -> List[Dict[str, Any]]:
        """查询门店全部库存快照。"""
        sql = """
            SELECT * FROM inventory_snapshot
            WHERE store_id = ?
            ORDER BY on_hand_qty ASC
        """
        cursor = self._db.execute(sql, (store_id,))
        columns = [desc[0] for desc in cursor.description]
        return [dict(zip(columns, row)) for row in cursor.fetchall()]

    @staticmethod
    def _calc_safety_stock(snapshot: Dict[str, Any]) -> float:
        """根据品类计算安全库存基准（天数）。"""
        category = (snapshot.get("category") or "").lower()
        daily_avg = snapshot.get("avg_daily_consumption") or 0

        # 品类系数：冻品需要更多缓冲
        category_factors = {
            "冻品": 5.0,     # 冻品备货周期长
            "肉类": 3.0,
            "蔬菜": 2.0,     # 蔬菜周转快
            "底料": 10.0,    # 低频但不可断货
            "蘸料": 14.0,
        }
        factor = category_factors.get(category, 3.0)
        return max(1.0, daily_avg * factor)

    def _evaluate_sku(
        self,
        store_id: str,
        sku: str,
        snapshot: Dict,
        on_hand: float,
        daily_avg: float,
        days_of_stock: float,
        safety_stock: float,
        earliest_expiry_str: Optional[str],
    ) -> List[StockAlertItem]:
        """评估单个 SKU 的所有预警条件，返回触发的告警列表。"""
        results: List[StockAlertItem] = []
        category = snapshot.get("category")
        unit = snapshot.get("unit", "kg")

        # A. 断货预警 (stockout)
        if daily_avg > 0 and days_of_stock < DEFAULT_RULES["stockout"]["threshold"]:
            results.append(StockAlertItem(
                sku=sku,
                sku_name=snapshot.get("sku_name"),
                category=category,
                current_qty=on_hand,
                unit=unit,
                safety_stock_level=safety_stock,
                days_of_stock=days_of_stock,
                daily_avg_consumption=daily_avg,
                alert_type="stockout",
                urgency="critical" if days_of_stock <= 1 else "high",
                suggested_order_qty=round(daily_avg * 3, 2),  # 建订3天量
                estimated_stockout_date=date.today() + timedelta(days=int(days_of_stock)),
            ))

        # B. 积压预警 (overstock)
        if daily_avg > 0 and days_of_stock > DEFAULT_RULES["overstock"]["threshold"]:
            results.append(StockAlertItem(
                sku=sku,
                sku_name=snapshot.get("sku_name"),
                category=category,
                current_qty=on_hand,
                unit=unit,
                safety_stock_level=safety_stock,
                days_of_stock=days_of_stock,
                daily_avg_consumption=daily_avg,
                alert_type="overstock",
                urgency="medium" if days_of_stock < 60 else "low",
            ))

        # C. 临期预警 (expiring)
        if earliest_expiry_str:
            try:
                expiry = date.fromisoformat(str(earliest_expiry_str)[:10])
                remaining = (expiry - date.today()).days
                if remaining <= DEFAULT_RULES["expiring"]["threshold"]:
                    results.append(StockAlertItem(
                        sku=sku,
                        sku_name=snapshot.get("sku_name"),
                        category=category,
                        current_qty=on_hand,
                        unit=unit,
                        safety_stock_level=safety_stock,
                        days_of_stock=days_of_stock,
                        daily_avg_consumption=daily_avg,
                        alert_type="expiring",
                        urgency="critical" if remaining <= 0 else "high",
                    ))
            except (ValueError, TypeError):
                pass

        # D. 滞销预警 (slow_moving): 最后消耗时间距今超过阈值
        last_consumed = snapshot.get("last_consumed_at")
        if last_consumed:
            try:
                last_date = datetime.fromisoformat(str(last_consumed)[:10]).date()
                days_idle = (date.today() - last_date).days
                if days_idle > DEFAULT_RULES["slow_moving"]["threshold"] and on_hand > 0:
                    results.append(StockAlertItem(
                        sku=sku,
                        sku_name=snapshot.get("sku_name"),
                        category=category,
                        current_qty=on_hand,
                        unit=unit,
                        safety_stock_level=safety_stock,
                        days_of_stock=days_of_stock,
                        daily_avg_consumption=daily_avg,
                        alert_type="slow_moving",
                        urgency="low",
                    ))
            except (ValueError, TypeError):
                pass

        return results

    def _emit_stock_alert(
        self, report: StockAlertReport, level_filter: str = ""
    ) -> None:
        """推送库存告警到 EventHub。"""
        if self._alerts is None:
            return
        try:
            filtered = [
                a for a in report.alerts
                if not level_filter or a.urgency == level_filter
            ]
            if not filtered:
                return

            summary = (
                f"门店 {report.store_id} 库存预警: "
                f"{report.summary.critical_count}严重 + "
                f"{report.summary.high_count}高 + "
                f"{report.summary.medium_count}中"
            )
            payload = {
                "alert_type": "stock_alert",
                "level": "critical" if level_filter == "critical" else "warn",
                "source": "data_engine",
                "store_id": report.store_id,
                "summary": summary,
                "detail": {
                    "summary": report.summary.model_dump(),
                    "top_alerts": [a.model_dump() for a in filtered[:5]],
                },
                "created_at": datetime.utcnow().isoformat(),
            }
            if hasattr(self._alerts, "emit"):
                self._alerts.emit(payload)
            logger.info("库存告警已推送 store=%s count=%d", report.store_id, len(filtered))
        except Exception as e:
            logger.error("库存告警发送失败: %s", e)
