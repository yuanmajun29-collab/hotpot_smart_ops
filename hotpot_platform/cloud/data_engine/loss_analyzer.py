"""
火瞳 · 数据引擎 — N04 损耗分析模块

损耗率 = (采购量 - 销售量 - 期末库存) / 采购量 × 100%

数据来源:
  - ERP 收货记录 (purchase qty)
  - POS 销量记录 (sales qty)
  - 库存账本 (closing inventory)
  - 视觉检测事件 (front_hall customer leftover, kitchen waste vision)

扩展 cost_control.analyzer.CostControlAnalyzer，复用收货成本分析能力。
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from hotpot_platform.cloud.cost_control.analyzer import CostControlAnalyzer
from hotpot_platform.cloud.data_engine.models import LossAnalysis, LossTrend


# ============================================================
# 损耗根因分类常量
# ============================================================

ROOT_CAUSE_CATEGORIES = {
    "over_purchase": "采购过多 — 预测偏差或安全库存偏高，导致未售出积压过期",
    "poor_storage": "存储不当 — 冷链/温控异常，食材变质损耗",
    "processing_waste": "加工损耗 — 分拣/切配/解冻 SOP 执行偏差，出成率低",
    "customer_leftover": "顾客剩余 — 顾客点餐后未食用导致退菜/泔水损耗",
}

# 损耗率警戒阈值（按 SKU 类别）
LOSS_THRESHOLDS: Dict[str, float] = {
    "肉类": 5.0,   # 鲜肉衰减快
    "蔬菜": 8.0,   # 叶菜易蔫
    "冻品": 3.0,   # 冻品稳定
    "底料": 2.0,   # 底料损耗低
    "蘸料": 2.0,   # 蘸料耐放
    "默认": 5.0,
}

# 根因推断权重（按信号来源）
ROOT_CAUSE_SIGNALS = {
    "over_purchase": ["forecast_deviation", "safety_stock_high", "order_frequency_low"],
    "poor_storage": ["cold_chain_alert", "temp_out_of_range", "shelf_life_expired"],
    "processing_waste": ["yield_rate_low", "trim_excessive", "thaw_incorrect"],
    "customer_leftover": ["return_rate_high", "plate_waste_event", "portion_oversize"],
}


class LossAnalyzer(CostControlAnalyzer):
    """SKU 级损耗分析器 — 扩展 CostControlAnalyzer。

    核心方法:
      compute_loss_rate   — 单SKU/单日损耗率
      loss_trend          — 多日损耗趋势
      loss_correlation    — 全店损耗关联分析
      root_cause          — 损耗根因诊断
      optimization_suggestion — ROI排序优化建议
    """

    def __init__(
        self,
        price_tolerance: float = 0.05,
        weight_tolerance: float = 0.03,
        yield_tolerance: float = 0.05,
    ) -> None:
        super().__init__(price_tolerance, weight_tolerance, yield_tolerance)

    # ------------------------------------------------------------------
    # compute_loss_rate
    # ------------------------------------------------------------------

    def compute_loss_rate(
        self,
        store_id: str,
        sku: str,
        business_date: date,
        *,
        purchase_qty: float = 0.0,
        sales_qty: float = 0.0,
        closing_inventory: float = 0.0,
        unit: str = "kg",
    ) -> Dict[str, Any]:
        """计算单 SKU / 单日损耗率。

        公式: loss_rate = (purchase - sales - closing_inventory) / purchase × 100%

        Args:
            store_id: 门店 ID
            sku: SKU 编码
            business_date: 营业日期
            purchase_qty: 采购量 (来自 ERP 收货)
            sales_qty: 销售量 (来自 POS)
            closing_inventory: 期末库存 (来自 inventory_book)
            unit: 计量单位

        Returns:
            dict with loss_rate_pct, loss_amount, status, etc.
        """
        if purchase_qty <= 0:
            return {
                "store_id": store_id,
                "sku": sku,
                "date": business_date.isoformat(),
                "loss_rate_pct": 0.0,
                "loss_qty": 0.0,
                "loss_amount": 0.0,
                "status": "no_purchase",
                "detail": {"purchase_qty": 0, "sales_qty": sales_qty, "closing_inventory": closing_inventory},
            }

        loss_qty = purchase_qty - sales_qty - closing_inventory

        # 理论损耗不能为负（负值说明库存/销售录入有偏差，按 0 处理）
        loss_qty = max(0.0, loss_qty)
        loss_rate_pct = round(loss_qty / purchase_qty * 100, 2)

        category = self._sku_category(sku)
        threshold = LOSS_THRESHOLDS.get(category, LOSS_THRESHOLDS["默认"])
        status = "alert" if loss_rate_pct > threshold else "normal"

        return {
            "store_id": store_id,
            "sku": sku,
            "date": business_date.isoformat(),
            "sku_category": category,
            "loss_rate_pct": loss_rate_pct,
            "loss_qty": round(loss_qty, 2),
            "loss_amount": None,  # 调用方可根据 unit_price 填充
            "status": status,
            "threshold_pct": threshold,
            "detail": {
                "purchase_qty": purchase_qty,
                "sales_qty": sales_qty,
                "closing_inventory": closing_inventory,
                "unit": unit,
            },
        }

    # ------------------------------------------------------------------
    # loss_trend
    # ------------------------------------------------------------------

    def loss_trend(
        self,
        store_id: str,
        sku: str,
        days: int = 30,
        *,
        purchase_history: Optional[Dict[date, float]] = None,
        sales_history: Optional[Dict[date, float]] = None,
        inventory_history: Optional[Dict[date, float]] = None,
    ) -> List[Dict[str, Any]]:
        """per-SKU 损耗率趋势 (最近 N 天)。

        Args:
            store_id: 门店 ID
            sku: SKU 编码
            days: 回溯天数
            purchase_history: {date: purchase_qty} ERP 采购历史
            sales_history: {date: sales_qty} POS 销售历史
            inventory_history: {date: closing_inventory} 库存快照历史

        Returns:
            List[Dict] 每日损耗率记录，按日期升序
        """
        purchase_history = purchase_history or {}
        sales_history = sales_history or {}
        inventory_history = inventory_history or {}

        today = date.today()
        trend: List[Dict[str, Any]] = []

        for offset in range(days - 1, -1, -1):
            d = today - timedelta(days=offset)
            p = purchase_history.get(d, 0.0)
            s = sales_history.get(d, 0.0)
            inv = inventory_history.get(d, 0.0)
            result = self.compute_loss_rate(store_id, sku, d, purchase_qty=p, sales_qty=s, closing_inventory=inv)
            trend.append(result)

        return trend

    # ------------------------------------------------------------------
    # loss_correlation
    # ------------------------------------------------------------------

    def loss_correlation(
        self,
        store_id: str,
        *,
        sku_loss_rates: Optional[Dict[str, float]] = None,
        sku_sales: Optional[Dict[str, float]] = None,
        sku_prices: Optional[Dict[str, float]] = None,
        top_n: int = 10,
    ) -> Dict[str, Any]:
        """全店损耗关联分析: Top10 高损耗 SKU + 损耗-销量相关系数。

        Args:
            store_id: 门店 ID
            sku_loss_rates: {sku: loss_rate_pct} 各 SKU 近期平均损耗率
            sku_sales: {sku: avg_daily_sales_qty} 各 SKU 日均销量
            sku_prices: {sku: unit_price} 各 SKU 单价 (用于计算损耗金额)
            top_n: 返回 Top N

        Returns:
            Dict with top_loss_skus, correlation_coefficient, summary
        """
        sku_loss_rates = sku_loss_rates or {}
        sku_sales = sku_sales or {}
        sku_prices = sku_prices or {}

        # 构建 SKU 列表，按损耗率排序取 Top N
        ranked = sorted(sku_loss_rates.items(), key=lambda x: -x[1])

        top_skus: List[Dict[str, Any]] = []
        for sku, loss_rate in ranked[:top_n]:
            sales_qty = sku_sales.get(sku, 0.0)
            unit_price = sku_prices.get(sku, 0.0)
            category = self._sku_category(sku)
            threshold = LOSS_THRESHOLDS.get(category, LOSS_THRESHOLDS["默认"])
            top_skus.append({
                "sku": sku,
                "loss_rate_pct": round(loss_rate, 2),
                "avg_daily_sales": round(sales_qty, 2),
                "unit_price": unit_price,
                "estimated_daily_loss": round(loss_rate / 100 * sales_qty * unit_price, 2),
                "threshold_pct": threshold,
                "over_threshold": loss_rate > threshold,
            })

        # 计算损耗率-销量 Pearson 相关系数
        correlation = self._pearson_correlation(sku_loss_rates, sku_sales)

        return {
            "store_id": store_id,
            "top_loss_skus": top_skus,
            "correlation_coefficient": round(correlation, 4) if correlation is not None else None,
            "correlation_interpretation": self._interpret_correlation(correlation),
            "total_skus_analyzed": len(sku_loss_rates),
        }

    # ------------------------------------------------------------------
    # root_cause
    # ------------------------------------------------------------------

    def root_cause(
        self,
        store_id: str,
        sku: str,
        *,
        receipt_data: Optional[Dict[str, Any]] = None,
        pos_data: Optional[Dict[str, Any]] = None,
        inventory_data: Optional[Dict[str, Any]] = None,
        vision_events: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """诊断 SKU 损耗根因: 采购过多? 存储不当? 加工损耗? 顾客剩余?

        基于多源数据信号加权推断最可能的根因类别。

        Args:
            store_id: 门店 ID
            sku: SKU 编码
            receipt_data: ERP 收货数据 (含 forecast deviation, safety stock 等)
            pos_data: POS 数据 (含 return_rate, order_pattern 等)
            inventory_data: 库存数据 (含 cold_chain, shelf_life, temp 等)
            vision_events: 视觉检测事件列表 (含 plate_waste, portion_size 等)

        Returns:
            Dict with primary_cause, cause_scores, evidence, suggestions
        """
        receipt_data = receipt_data or {}
        pos_data = pos_data or {}
        inventory_data = inventory_data or {}
        vision_events = vision_events or []

        # 逐类评分
        scores: Dict[str, float] = {}
        evidence: Dict[str, List[str]] = {}

        # ---- 采购过多 ----
        op_score, op_evidence = self._score_over_purchase(receipt_data)
        scores["over_purchase"] = op_score
        evidence["over_purchase"] = op_evidence

        # ---- 存储不当 ----
        ps_score, ps_evidence = self._score_poor_storage(inventory_data)
        scores["poor_storage"] = ps_score
        evidence["poor_storage"] = ps_evidence

        # ---- 加工损耗 ----
        pw_score, pw_evidence = self._score_processing_waste(receipt_data, inventory_data)
        scores["processing_waste"] = pw_score
        evidence["processing_waste"] = pw_evidence

        # ---- 顾客剩余 ----
        cl_score, cl_evidence = self._score_customer_leftover(pos_data, vision_events)
        scores["customer_leftover"] = cl_score
        evidence["customer_leftover"] = cl_evidence

        # 确定主要根因
        primary_cause = max(scores, key=scores.get) if scores else "unknown"
        primary_score = scores.get(primary_cause, 0)

        return {
            "store_id": store_id,
            "sku": sku,
            "primary_cause": primary_cause,
            "primary_cause_label": ROOT_CAUSE_CATEGORIES.get(primary_cause, "未知"),
            "cause_scores": {k: round(v, 2) for k, v in sorted(scores.items(), key=lambda x: -x[1])},
            "evidence": {k: v for k, v in evidence.items() if v},
            "confidence": "high" if primary_score > 0.6 else "medium" if primary_score > 0.3 else "low",
            "suggestion": self._root_cause_suggestion(primary_cause, sku),
        }

    # ------------------------------------------------------------------
    # optimization_suggestion
    # ------------------------------------------------------------------

    def optimization_suggestion(
        self,
        store_id: str,
        *,
        sku_loss_data: Optional[List[Dict[str, Any]]] = None,
        sku_price_data: Optional[Dict[str, float]] = None,
    ) -> List[Dict[str, Any]]:
        """按 ROI 排序的损耗优化建议。

        优先级: 高损耗金额 & 高损耗率 SKU 优先，预估优化收益 = 损耗减少量 × 单价。

        Args:
            store_id: 门店 ID
            sku_loss_data: [{sku, loss_rate_pct, avg_daily_sales, loss_qty}, ...]
            sku_price_data: {sku: unit_price}

        Returns:
            List[Dict] 按 estimated_roi 降序
        """
        sku_loss_data = sku_loss_data or []
        sku_price_data = sku_price_data or {}

        suggestions: List[Dict[str, Any]] = []
        for item in sku_loss_data:
            sku = item.get("sku", "")
            loss_rate = float(item.get("loss_rate_pct", 0))
            loss_qty = float(item.get("loss_qty", 0))
            price = sku_price_data.get(sku, 0.0)
            category = self._sku_category(sku)
            threshold = LOSS_THRESHOLDS.get(category, LOSS_THRESHOLDS["默认"])

            if loss_rate <= threshold * 0.5:
                continue  # 远低于阈值，无需优化

            # 预估可优化损耗: 假设可降低到阈值的 80%
            target_rate = threshold * 0.8
            reducible_pct = max(0, loss_rate - target_rate)
            estimated_saving = round(reducible_pct / 100 * loss_qty * price, 2)

            # 获取根因
            cause_info = self.root_cause(store_id, sku)
            primary_cause = cause_info.get("primary_cause", "unknown")

            suggestions.append({
                "sku": sku,
                "category": category,
                "current_loss_rate_pct": round(loss_rate, 2),
                "target_loss_rate_pct": round(target_rate, 2),
                "estimated_monthly_saving": estimated_saving,
                "primary_root_cause": primary_cause,
                "action": self._get_optimization_action(sku, primary_cause, loss_rate, threshold),
                "roi_priority": "high" if estimated_saving > 500 else "medium" if estimated_saving > 100 else "low",
            })

        suggestions.sort(key=lambda x: -x["estimated_monthly_saving"])
        return suggestions

    # ------------------------------------------------------------------
    # 内部辅助方法
    # ------------------------------------------------------------------

    @staticmethod
    def _sku_category(sku: str) -> str:
        """根据 SKU 名称推断类别。"""
        sku_lower = sku.lower()
        if any(k in sku_lower for k in ("肉", "牛", "羊", "猪", "鸡", "鸭", "虾", "鱼", "丸", "滑")):
            return "肉类"
        if any(k in sku_lower for k in ("菜", "蔬", "菇", "菌", "豆", "笋", "藕")):
            return "蔬菜"
        if any(k in sku_lower for k in ("冻", "冰")):
            return "冻品"
        if any(k in sku_lower for k in ("底料", "锅底", "汤底")):
            return "底料"
        if any(k in sku_lower for k in ("蘸", "酱", "料")):
            return "蘸料"
        return "默认"

    @staticmethod
    def _pearson_correlation(
        x_dict: Dict[str, float], y_dict: Dict[str, float]
    ) -> Optional[float]:
        """计算两个 dict 的 Pearson 相关系数 (仅取交集 keys)。"""
        common_keys = [k for k in x_dict if k in y_dict]
        if len(common_keys) < 3:
            return None
        xs = [x_dict[k] for k in common_keys]
        ys = [y_dict[k] for k in common_keys]
        n = len(xs)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        std_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
        std_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
        if std_x == 0 or std_y == 0:
            return None
        return cov / (std_x * std_y)

    @staticmethod
    def _interpret_correlation(coef: Optional[float]) -> str:
        if coef is None:
            return "样本不足，无法计算"
        if coef > 0.5:
            return "正相关 — 销量越高的 SKU 损耗率也越高，可能存在规模化损耗问题"
        if coef < -0.3:
            return "负相关 — 滞销品损耗更严重，建议减少采购或促销清库存"
        return "弱相关 — 损耗率与销量无明显线性关系，损耗更可能源于运营因素"

    # ---- 根因评分逻辑 ----

    def _score_over_purchase(self, receipt: Dict[str, Any]) -> Tuple[float, List[str]]:
        """采购过多评分."""
        score = 0.0
        ev: List[str] = []
        if receipt.get("forecast_deviation_pct", 0) > 20:
            score += 0.35
            ev.append(f"预测偏差 {receipt['forecast_deviation_pct']:.0f}%")
        if receipt.get("safety_stock_days", 0) > 3:
            score += 0.25
            ev.append(f"安全库存天数 {receipt['safety_stock_days']} 天偏高")
        if receipt.get("order_frequency", "").lower() in ("weekly", "monthly"):
            score += 0.15
            ev.append("订货频率偏低，单次采购量偏大")
        if receipt.get("po_qty_vs_forecast_ratio", 1.0) > 1.3:
            score += 0.15
            ev.append("PO 量超预测 30% 以上")
        return score, ev

    def _score_poor_storage(self, inventory: Dict[str, Any]) -> Tuple[float, List[str]]:
        """存储不当评分."""
        score = 0.0
        ev: List[str] = []
        if inventory.get("cold_chain_breach_count", 0) > 0:
            score += 0.3
            ev.append(f"冷链异常 {inventory['cold_chain_breach_count']} 次")
        if inventory.get("avg_storage_temp_c", -18) > -12:
            score += 0.2
            ev.append(f"平均存储温度 {inventory['avg_storage_temp_c']}°C 偏离标准")
        if inventory.get("expired_qty", 0) > 0:
            score += 0.25
            ev.append(f"过期库存 {inventory['expired_qty']} {inventory.get('unit','kg')}")
        if inventory.get("near_expiry_days", 30) < 3:
            score += 0.15
            ev.append("库存临期，FIFO 执行不到位")
        return score, ev

    def _score_processing_waste(
        self, receipt: Dict[str, Any], inventory: Dict[str, Any]
    ) -> Tuple[float, List[str]]:
        """加工损耗评分."""
        score = 0.0
        ev: List[str] = []
        yield_rate = receipt.get("yield_rate") or inventory.get("yield_rate")
        if yield_rate is not None and yield_rate < 0.85:
            score += 0.35
            ev.append(f"出成率 {yield_rate*100:.0f}% 低于标准 85%")
        if receipt.get("trim_waste_pct", 0) > 10:
            score += 0.2
            ev.append(f"边角料损耗 {receipt['trim_waste_pct']:.0f}%")
        if inventory.get("thaw_water_loss_pct", 0) > 8:
            score += 0.15
            ev.append(f"解冻失水率 {inventory['thaw_water_loss_pct']:.0f}% 偏高")
        if inventory.get("kitchen_waste_event_count", 0) > 5:
            score += 0.2
            ev.append(f"后厨视觉检测损耗事件 {inventory['kitchen_waste_event_count']} 次")
        return score, ev

    def _score_customer_leftover(
        self, pos: Dict[str, Any], vision_events: List[Dict[str, Any]]
    ) -> Tuple[float, List[str]]:
        """顾客剩余评分."""
        score = 0.0
        ev: List[str] = []
        return_rate = pos.get("return_rate_pct", 0)
        if return_rate > 5:
            score += 0.3
            ev.append(f"退菜率 {return_rate:.1f}%")
        portion_oversize = pos.get("portion_oversize_ratio", 0)
        if portion_oversize > 0.2:
            score += 0.2
            ev.append("份量偏大比例偏高")
        plate_waste = sum(1 for e in vision_events if e.get("event_type") == "plate_waste")
        if plate_waste > 0:
            score += 0.2
            ev.append(f"前厅视觉检测到 {plate_waste} 次餐盘剩余")
        return score, ev

    @staticmethod
    def _root_cause_suggestion(cause: str, sku: str) -> str:
        """根据根因生成优化建议文本。"""
        suggestions = {
            "over_purchase": f"缩小 {sku} 安全库存窗口至 T+1，联动 forecast_agent 提高预测精度",
            "poor_storage": f"排查 {sku} 冷链设备，强制执行 FIFO 出库并加装 IoT 温控探头",
            "processing_waste": f"复核 {sku} 切配 SOP 与解冻流程，建立出成率日考核",
            "customer_leftover": f"评估 {sku} 份量是否与顾客实际需求匹配，考虑推出小份规格",
        }
        return suggestions.get(cause, "需进一步收集数据以精确定位损耗根因")

    @staticmethod
    def _get_optimization_action(
        sku: str, cause: str, loss_rate: float, threshold: float
    ) -> str:
        """生成可执行的优化行动项。"""
        gap = loss_rate - threshold
        if cause == "over_purchase":
            return f"{sku}: 调整订货模型，降低预测偏差 → 预计损耗率降低 {gap:.1f}pp"
        if cause == "poor_storage":
            return f"{sku}: 升级冷链监控 + 每日库存巡检 → 预计损耗率降低 {gap:.1f}pp"
        if cause == "processing_waste":
            return f"{sku}: 切配 SOP 标准化 + 刀工培训 → 预计损耗率降低 {gap:.1f}pp"
        if cause == "customer_leftover":
            return f"{sku}: 份量优化 + 小份规格上线 → 预计损耗率降低 {gap:.1f}pp"
        return f"{sku}: 综合排查损耗来源，优先控制采购与存储环节"
