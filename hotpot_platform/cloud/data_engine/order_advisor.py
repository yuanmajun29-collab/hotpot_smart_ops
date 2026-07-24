"""
火瞳 · 数据引擎 N02 — 智能订货顾问 (Order Advisor)

三模型混合订货, 按品类保质期自动选择:
  - 保质期 > 30 天   → EOQ 经济订货量  Q* = √(2DS/H)
  - 保质期 ≤ 3 天    → 报童模型        Q* = μ + Z·σ,  CR = (p-c)/(p-s)
  - 中间品 (4~30 天)  → 动态安全库存    ROP = d̄·L + Z·σ_L·√L

决策流: 预测需求 → 计算可用库存 → gap → 选模型 → 约束调整 → 生成建议 + 紧急度判定
"""

from __future__ import annotations

import math
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple

import sys
import os
_sys_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _sys_base not in sys.path:
    sys.path.insert(0, _sys_base)

from hotpot_platform.cloud.data_engine.models import OrderSuggestion, InventorySnapshot


# ---------------------------------------------------------------------------
# 品类保质期映射 (可配置, 缺省)
# ---------------------------------------------------------------------------

DEFAULT_SHELF_LIFE_DAYS: Dict[str, int] = {
    # 生鲜短保 ≤3 天 — 报童模型
    "鲜毛肚": 2,
    "鲜鸭血": 2,
    "活虾": 1,
    "鲜切牛肉": 2,
    "鲜鱼片": 1,
    # 中间品 4-30 天 — 动态安全库存
    "冷冻虾滑": 14,
    "冷冻牛肉卷": 30,
    "冷冻羊肉卷": 30,
    "冷冻丸子": 28,
    "冻豆腐": 21,
    # 长保 >30 天 — EOQ
    "底料": 180,
    "蘸料": 180,
    "干货": 365,
    "调味粉": 365,
    "饮料": 180,
}

# NORMSINV 近似: Z 值 = Φ⁻¹(service_level)
_Z_TABLE: Dict[float, float] = {
    0.80: 0.842, 0.85: 1.036, 0.90: 1.282,
    0.95: 1.645, 0.975: 1.960, 0.99: 2.326,
}


def _z_value(service_level: float) -> float:
    """Linear interpolation in the Z-table; clamp to [0.80, 0.99]."""
    if service_level <= 0.80:
        return _Z_TABLE[0.80]
    if service_level >= 0.99:
        return _Z_TABLE[0.99]
    keys = sorted(_Z_TABLE.keys())
    for i in range(len(keys) - 1):
        lo, hi = keys[i], keys[i + 1]
        if lo <= service_level <= hi:
            ratio = (service_level - lo) / (hi - lo)
            return _Z_TABLE[lo] + ratio * (_Z_TABLE[hi] - _Z_TABLE[lo])
    return _Z_TABLE[0.95]


# ---------------------------------------------------------------------------
# Internal candidate container
# ---------------------------------------------------------------------------

@dataclass
class _OrderCandidate:
    store_id: str
    sku: str
    suggested_qty: float
    unit: str
    current_stock: float
    safety_stock: float
    forecast_demand: float
    lead_time_days: int
    supplier: Optional[str]
    urgency: str
    reason: str
    model_used: str
    # score for break-ties when multiple SKUs
    gap_ratio: float = 0.0


# ---------------------------------------------------------------------------
# OrderAdvisor
# ---------------------------------------------------------------------------

class OrderAdvisor:
    """三模型混合订货引擎。

    Parameters
    ----------
    ordering_cost: 单次订货固定成本 S (元/次)
    holding_rate:  年库存持有成本比率 H (占单位成本比), 默认 0.20
    service_level: 目标服务水平 (报童 & 安全库存的 Z 值出处), 默认 0.95
    """

    def __init__(
        self,
        ordering_cost: float = 80.0,
        holding_rate: float = 0.20,
        service_level: float = 0.95,
    ) -> None:
        self.S = ordering_cost
        self.h = holding_rate
        self.service_level = service_level
        self._suggestions: Dict[str, OrderSuggestion] = {}  # id → 已生成建议

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def generate_suggestions(
        self,
        store_id: str,
        target_date: date,
        horizon_days: int = 7,
        *,
        inventory_snapshots: Optional[List[InventorySnapshot]] = None,
        demand_forecasts: Optional[List[Dict[str, Any]]] = None,
        moq_map: Optional[Dict[str, float]] = None,
        pack_round: Optional[Dict[str, float]] = None,
        budget_limit: Optional[float] = None,
    ) -> List[OrderSuggestion]:
        """为门店生成未来 horizon_days 天的订货建议。

        入参
        ----
        inventory_snapshots: 当前库存快照列表。
        demand_forecasts:   [{sku, forecast_date, predicted_qty, ...}, ...]
        moq_map:            {sku: 最小起订量}
        pack_round:         {sku: 包装取整单位}, e.g. {“鲜毛肚”: 2.5}
        budget_limit:       本期订货预算上限 (元)

        返回
        ----
        List[OrderSuggestion] — 按 urgency (urgent→normal→low) 排序。
        """
        snapshots = {s.sku: s for s in (inventory_snapshots or [])}
        forecasts: Dict[str, Dict[str, float]] = {}
        for f in (demand_forecasts or []):
            sku = f.get("sku", "")
            d = f.get("forecast_date")
            if isinstance(d, str):
                d = date.fromisoformat(d)
            q = float(f.get("predicted_qty", 0))
            forecasts.setdefault(sku, {})[d] = q

        moq = moq_map or {}
        pkg = pack_round or {}
        candidates: List[_OrderCandidate] = []

        for sku, daily_map in forecasts.items():
            total_demand = sum(
                q for d, q in daily_map.items()
                if d >= target_date and d < date.fromordinal(target_date.toordinal() + horizon_days)
            )
            if total_demand <= 0:
                continue

            snap = snapshots.get(sku)
            on_hand = float(snap.on_hand_qty) if snap else 0.0
            in_transit = float(snap.in_transit_qty) if snap else 0.0
            shelf_life = (snap.shelf_life_days
                          if snap and snap.shelf_life_days
                          else DEFAULT_SHELF_LIFE_DAYS.get(sku, 14))
            lead_time = int(snap.avg_daily_consumption or 1) if snap else 1
            lead_time = max(lead_time, 1)

            # 估算损耗: 用 3% 日损耗率 × shelf_life 衰减
            daily_loss_rate = 0.03
            estimated_loss = on_hand * daily_loss_rate * min(horizon_days, shelf_life)
            available = on_hand + in_transit - estimated_loss
            gap = max(0, total_demand - available)

            if gap <= 0:
                # 库存充足, 但生成一条 low 建议供 review
                candidates.append(_OrderCandidate(
                    store_id=store_id, sku=sku,
                    suggested_qty=0.0, unit=snap.unit if snap else "kg",
                    current_stock=on_hand, safety_stock=0.0,
                    forecast_demand=total_demand, lead_time_days=lead_time,
                    supplier=None, urgency="low",
                    reason=f"库存充足 ({on_hand:.1f} on-hand), 本期无需订货",
                    model_used="skip",
                ))
                continue

            # ── 选模型 ──
            unit_price = self._estimate_unit_price(sku)
            if shelf_life > 30:
                suggested = self._model_eoq(total_demand, unit_price)
                model = "EOQ"
            elif shelf_life <= 3:
                suggested = self._model_newsvendor(total_demand, unit_price, daily_map, target_date)
                model = "newsvendor"
            else:
                suggested = self._model_rop(total_demand, daily_map, target_date, lead_time)
                model = "ROP"

            # ── 约束调整 ──
            if sku in moq and suggested < moq[sku]:
                suggested = moq[sku]
            if sku in pkg and pkg[sku] > 0:
                suggested = math.ceil(suggested / pkg[sku]) * pkg[sku]

            suggested = max(0, round(suggested, 2))
            gap = round(gap, 2)

            # ── 紧急度 ──
            safety = round(self._safety_stock(total_demand, lead_time, daily_map, target_date), 2)
            if gap > safety:
                urgency = "urgent"
            elif gap > 0:
                urgency = "normal"
            else:
                urgency = "low"

            reason_parts = [f"{model} 订货", f"需求 {total_demand:.1f}{snap.unit if snap else 'kg'}"]
            if sku in moq:
                reason_parts.append(f"≥MOQ {moq[sku]}")

            candidates.append(_OrderCandidate(
                store_id=store_id, sku=sku,
                suggested_qty=suggested,
                unit=snap.unit if snap else "kg",
                current_stock=on_hand,
                safety_stock=safety,
                forecast_demand=total_demand,
                lead_time_days=lead_time,
                supplier=None,
                urgency=urgency,
                reason="; ".join(reason_parts),
                model_used=model,
                gap_ratio=gap / max(total_demand, 1),
            ))

        # ── 预算检查 ──
        candidates = self._apply_budget(candidates, budget_limit)

        # ── 排序 & 持久化 ──
        urgency_order = {"urgent": 0, "normal": 1, "low": 2}
        candidates.sort(key=lambda c: (urgency_order[c.urgency], -c.gap_ratio))

        results: List[OrderSuggestion] = []
        for c in candidates:
            sug_id = self._gen_sug_id(store_id, c.sku)
            suggestion = OrderSuggestion(
                store_id=c.store_id,
                sku=c.sku,
                suggested_qty=c.suggested_qty,
                unit=c.unit,
                current_stock=c.current_stock,
                safety_stock=c.safety_stock,
                forecast_demand=c.forecast_demand,
                lead_time_days=c.lead_time_days,
                supplier=c.supplier,
                urgency=c.urgency,
                reason=c.reason,
                status="pending",
            )
            self._suggestions[sug_id] = suggestion
            results.append(suggestion)

        return results

    def approve_suggestion(
        self,
        suggestion_id: str,
        approved_by: str,
        adjusted_qty: Optional[float] = None,
    ) -> Optional[OrderSuggestion]:
        """审批一条订货建议。

        返回更新后的 OrderSuggestion; 未找到返回 None。
        """
        sug = self._suggestions.get(suggestion_id)
        if sug is None:
            return None
        if adjusted_qty is not None:
            sug.suggested_qty = max(0, adjusted_qty)
        sug.status = "approved"
        return sug

    # ------------------------------------------------------------------
    # 三模型
    # ------------------------------------------------------------------

    def _model_eoq(self, annual_demand: float, unit_price: float) -> float:
        """EOQ: Q* = sqrt(2 · D · S / H)"""
        if unit_price <= 0:
            return annual_demand
        H = self.h * unit_price  # 单件年持有成本
        if H <= 0:
            return annual_demand
        q = math.sqrt(2 * annual_demand * self.S / H)
        return max(q, 0)

    def _model_newsvendor(
        self,
        horizon_demand: float,
        unit_price: float,
        daily_map: Dict[date, float],
        target_date: date,
    ) -> float:
        """报童模型: Q* = μ + Z·σ

        CR = (p - c) / (p - s)
        - p = 售价 (估算), c = 成本 (unit_price), s = 残值 (滞销折价)
        """
        mu, sigma = self._demand_stats(daily_map, target_date)
        if sigma == 0:
            return max(horizon_demand, mu)

        selling_price = unit_price * 2.5  # 餐饮行业典型加价率
        salvage = unit_price * 0.2        # 残值: 烂掉/报废仅回 20%
        cr = (selling_price - unit_price) / max(selling_price - salvage, 0.01)
        cr = max(0.5, min(0.99, cr))

        z = _z_value(cr)
        return max(mu + z * sigma, 0)

    def _model_rop(
        self,
        horizon_demand: float,
        daily_map: Dict[date, float],
        target_date: date,
        lead_time: int,
    ) -> float:
        """再订货点 ROP: d̄ · L + Z · σ_L · √L"""
        mu, sigma = self._demand_stats(daily_map, target_date)
        z = _z_value(self.service_level)
        rop = mu * lead_time + z * sigma * math.sqrt(max(lead_time, 1))
        return max(rop, horizon_demand * 0.5)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _demand_stats(
        daily_map: Dict[date, float],
        target_date: date,
    ) -> Tuple[float, float]:
        """从 daily_map 中取 date >= target_date 的每日需求计算 μ, σ。"""
        vals = [q for d, q in daily_map.items() if d >= target_date]
        if not vals:
            vals = list(daily_map.values())
        if not vals:
            return 0.0, 0.0
        mu = sum(vals) / len(vals)
        variance = sum((v - mu) ** 2 for v in vals) / max(len(vals), 1)
        return mu, math.sqrt(variance)

    @staticmethod
    def _estimate_unit_price(sku: str) -> float:
        """简单单价估算: 后续可接 cost_control/analyzer 真实价格。"""
        _defaults = {
            "鲜毛肚": 45.0, "鲜鸭血": 12.0, "鲜切牛肉": 55.0, "活虾": 80.0,
            "鲜鱼片": 35.0, "冷冻虾滑": 22.0, "冷冻牛肉卷": 48.0,
            "冷冻羊肉卷": 42.0, "冷冻丸子": 18.0, "冻豆腐": 8.0,
            "底料": 25.0, "蘸料": 15.0, "干货": 30.0, "调味粉": 10.0, "饮料": 6.0,
        }
        return _defaults.get(sku, 20.0)

    def _safety_stock(
        self,
        horizon_demand: float,
        lead_time: int,
        daily_map: Dict[date, float],
        target_date: date,
    ) -> float:
        """安全库存 = Z · σ_L · √L"""
        _, sigma = self._demand_stats(daily_map, target_date)
        z = _z_value(self.service_level)
        return z * sigma * math.sqrt(max(lead_time, 1))

    def _apply_budget(
        self,
        candidates: List[_OrderCandidate],
        budget_limit: Optional[float],
    ) -> List[_OrderCandidate]:
        """预算约束: 按 urgency 优先级, 超预算后裁剪 low 项。"""
        if budget_limit is None or budget_limit <= 0:
            return candidates

        urgency_order = {"urgent": 0, "normal": 1, "low": 2}
        sorted_c = sorted(candidates, key=lambda c: (urgency_order[c.urgency], -c.gap_ratio))

        total = 0.0
        kept: List[_OrderCandidate] = []
        deferred: List[_OrderCandidate] = []

        for c in sorted_c:
            unit_price = self._estimate_unit_price(c.sku)
            cost = c.suggested_qty * unit_price
            if c.urgency == "urgent" or total + cost <= budget_limit:
                kept.append(c)
                total += cost
            else:
                # 降级为 low + 裁剪到预算剩余
                remaining = budget_limit - total
                if remaining > 0 and c.urgency != "low":
                    scaled_qty = remaining / max(unit_price, 0.01)
                    c.suggested_qty = max(0, round(scaled_qty, 2))
                    c.urgency = "low"
                    c.reason += f" (预算不足, 削减至 {c.suggested_qty:.1f})"
                    kept.append(c)
                    total += scaled_qty * unit_price
                else:
                    deferred.append(c)

        return kept + deferred

    @staticmethod
    def _gen_sug_id(store_id: str, sku: str) -> str:
        day = datetime.now().strftime("%Y%m%d")
        short = uuid.uuid4().hex[:8].upper()
        return f"ORD-{day}-{store_id[-6:]}-{sku[:6]}-{short}"
