"""
火瞳 · 数据引擎 N05 — 供应商评分引擎 (Supplier Scorer)

评分维度权重:
  价格竞争力 25% + 质量等级 25% + 交货可靠性 25%
  + 数量准确性 15% + 响应灵活性 10%

评分等级: A(85-100) / B(70-84) / C(55-69) / D(<55)

数据来源: ERP 收货记录 + cost_control/analyzer 成本分析 + receiving_store 质检
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

import sys
import os
_sys_base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _sys_base not in sys.path:
    sys.path.insert(0, _sys_base)

from hotpot_platform.cloud.data_engine.models import SupplierScorecard


# ---------------------------------------------------------------------------
# 维度权重
# ---------------------------------------------------------------------------

WEIGHTS = {
    "price_competitiveness": 0.25,
    "quality_grade":         0.25,
    "delivery_reliability":  0.25,
    "quantity_accuracy":     0.15,
    "response_flexibility":  0.10,
}

# 评分等级阈值
SCORE_LEVELS = [
    (85, "A"),
    (70, "B"),
    (55, "C"),
    (0,  "D"),
]


def _level(score: float) -> str:
    for threshold, label in SCORE_LEVELS:
        if score >= threshold:
            return label
    return "D"


# ---------------------------------------------------------------------------
# SupplierScorer
# ---------------------------------------------------------------------------

class SupplierScorer:
    """供应商综合评分引擎。

    使用 ERP 收货记录 + 成本分析 + 质检数据进行五维评分。
    可独立运行: 所有非标准库依赖均通过 try/except 惰性加载。
    """

    def __init__(
        self,
        weights: Optional[Dict[str, float]] = None,
        eval_window_days: int = 90,
    ) -> None:
        self.weights = weights or WEIGHTS.copy()
        self.eval_window_days = eval_window_days

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def evaluate_supplier(
        self,
        supplier_name: str,
        store_id: Optional[str] = None,
        sku: Optional[str] = None,
        eval_days: Optional[int] = None,
        *,
        receiving_records: Optional[List[Dict[str, Any]]] = None,
        cost_records: Optional[List[Dict[str, Any]]] = None,
    ) -> SupplierScorecard:
        """对单个供应商进行综合评价。

        入参
        ----
        receiving_records: ERP 收货记录列表, 每条含 batch_id/sku/supplier/weight_kg/
                           po_weight_kg/variance_pct/vlm_grade/created_at 等字段。
        cost_records:      cost_control/analyzer 输出, 每条含 supplier/sku/
                           po_amount/actual_amount/variance_pct/yield_rate/quality_grade.
        若未传入, 会自动尝试从本地 demo 数据加载 (development 模式)。

        返回
        ----
        SupplierScorecard
        """
        window = eval_days or self.eval_window_days
        cutoff = datetime.now() - timedelta(days=window)

        recs = self._filter_by_supplier(receiving_records or [], supplier_name, store_id, sku, cutoff)
        costs = self._filter_by_supplier(cost_records or [], supplier_name, store_id, sku, cutoff)

        if not recs and not costs:
            return SupplierScorecard(
                store_id=store_id,
                supplier_name=supplier_name,
                sku=sku,
                total_batches=0,
                total_score=0.0,
                score_level="D",
            )

        n_batches = len(recs) or len(costs)

        # ── 维度得分 ──
        price_score     = self._score_price_competitiveness(costs, recs)
        quality_score   = self._score_quality_grade(recs, costs)
        delivery_score  = self._score_delivery_reliability(recs)
        accuracy_score  = self._score_quantity_accuracy(recs, costs)
        response_score  = self._score_response_flexibility(recs)

        total = (
            price_score    * self.weights["price_competitiveness"]
            + quality_score  * self.weights["quality_grade"]
            + delivery_score * self.weights["delivery_reliability"]
            + accuracy_score * self.weights["quantity_accuracy"]
            + response_score * self.weights["response_flexibility"]
        )
        total = round(total, 1)

        # ── 汇总指标 ──
        variances = [r.get("variance_pct") for r in recs if r.get("variance_pct") is not None]
        avg_variance = round(sum(variances) / len(variances), 2) if variances else None

        yield_vals = [c.get("yield_rate") for c in costs if c.get("yield_rate") is not None]
        avg_yield = round(sum(yield_vals) / len(yield_vals), 3) if yield_vals else None

        # quality grade dist
        grade_dist = defaultdict(int)
        for r in recs:
            g = r.get("vlm_grade") or r.get("quality_grade")
            if g:
                grade_dist[str(g)] += 1
        for c in costs:
            g = c.get("quality_grade")
            if g and g not in grade_dist:
                grade_dist[str(g)] += 1

        # avg price
        prices = [
            (c.get("actual_amount") / c.get("po_qty_kg", 1) if c.get("actual_amount") else None)
            for c in costs
        ]
        prices = [p for p in prices if p is not None]
        avg_price = round(sum(prices) / len(prices), 2) if prices else None

        # price stability = 1 - cv of unit prices
        price_stability = None
        if prices and len(prices) >= 2:
            mu = sum(prices) / len(prices)
            cv = math.sqrt(sum((p - mu) ** 2 for p in prices) / len(prices)) / max(mu, 0.01)
            price_stability = round(max(0, 1 - cv), 4)

        # on-time rate
        on_time = sum(1 for r in recs if self._is_on_time(r))
        on_time_rate = round(on_time / n_batches, 4) if n_batches else None

        # reject rate: vlm_grade C/D 且 action=reject
        rejected = sum(
            1 for c in (costs or [])
            if c.get("quality_grade") in ("C", "D") or c.get("action") == "reject"
        )
        reject_rate = round(rejected / n_batches, 4) if n_batches else None

        return SupplierScorecard(
            store_id=store_id,
            supplier_name=supplier_name,
            sku=sku,
            total_batches=n_batches,
            avg_variance_pct=avg_variance,
            avg_yield_rate=avg_yield,
            quality_grade_dist=dict(grade_dist) if grade_dist else None,
            avg_price=avg_price,
            price_stability=price_stability,
            on_time_rate=on_time_rate,
            reject_rate=reject_rate,
            total_score=total,
            score_level=_level(total),
        )

    def rank_suppliers(
        self,
        store_id: str,
        sku: str,
        *,
        receiving_records: Optional[List[Dict[str, Any]]] = None,
        cost_records: Optional[List[Dict[str, Any]]] = None,
    ) -> List[SupplierScorecard]:
        """对相同 SKU 的所有供应商按综合评分排序。

        返回
        ----
        List[SupplierScorecard] — score 降序, D 级排最末。
        """
        recs = self._filter_records(receiving_records or [], store_id, sku)
        costs = self._filter_records(cost_records or [], store_id, sku)

        # 按 supplier 分组记录
        supplier_recs = defaultdict(list)
        for r in recs:
            supplier_recs[r.get("supplier", "")].append(r)
        supplier_costs = defaultdict(list)
        for c in costs:
            supplier_costs[c.get("supplier", "")].append(c)

        all_suppliers = set(supplier_recs.keys()) | set(supplier_costs.keys())

        cards: List[SupplierScorecard] = []
        for supplier in all_suppliers:
            card = self.evaluate_supplier(
                supplier,
                store_id=store_id,
                sku=sku,
                receiving_records=supplier_recs.get(supplier, []),
                cost_records=supplier_costs.get(supplier, []),
            )
            cards.append(card)

        # 排序: D 永远在最末
        cards.sort(key=lambda c: (0 if c.score_level != "D" else 1, -(c.total_score or 0)))
        return cards

    def suggest_alternative(
        self,
        store_id: str,
        sku: str,
        *,
        receiving_records: Optional[List[Dict[str, Any]]] = None,
        cost_records: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """为当前 SKU 的 C / D 级供应商推荐替代方案。

        返回
        ----
        {
          "store_id": ...,
          "sku": ...,
          "flagged": [SupplierScorecard, ...],       # C/D 级供应商
          "alternatives": [SupplierScorecard, ...],  # A/B 级替代供应商
          "recommendation": str,                     # 建议文本
        }
        """
        ranked = self.rank_suppliers(
            store_id=store_id,
            sku=sku,
            receiving_records=receiving_records,
            cost_records=cost_records,
        )

        flagged = [c for c in ranked if c.score_level in ("C", "D")]
        alternatives = [c for c in ranked if c.score_level in ("A", "B")]

        if not flagged:
            return {
                "store_id": store_id,
                "sku": sku,
                "flagged": [],
                "alternatives": ranked,
                "recommendation": f"{sku} 现有供应商评分均在 B 级以上，无需替换。",
            }

        if not alternatives:
            return {
                "store_id": store_id,
                "sku": sku,
                "flagged": flagged,
                "alternatives": [],
                "recommendation": f"{sku} 的 {len(flagged)} 家供应商评分偏低 (C/D)，暂无 A/B 级替代，建议拓展供应商池。",
            }

        rec_parts = []
        for alt in alternatives[:3]:
            rec_parts.append(
                f"{alt.supplier_name} (综合 {alt.total_score}, {alt.score_level} 级"
                f"{', 准时率 ' + str(int((alt.on_time_rate or 0)*100)) + '%' if alt.on_time_rate else ''})"
            )
        return {
            "store_id": store_id,
            "sku": sku,
            "flagged": flagged,
            "alternatives": alternatives,
            "recommendation": f"建议将 {sku} 从 {', '.join(f.supplier_name for f in flagged)} 切换至: {'; '.join(rec_parts)}。",
        }

    # ------------------------------------------------------------------
    # 五维评分细则
    # ------------------------------------------------------------------

    def _score_price_competitiveness(
        self,
        costs: List[Dict[str, Any]],
        recs: List[Dict[str, Any]],
    ) -> float:
        """价格竞争力: 基于 cost variance 和 price stability。

        成本偏差越低越好; 满分 100, 偏差超 5% 则线性扣分。
        """
        variances = [c.get("variance_pct") for c in costs if c.get("variance_pct") is not None]
        if not variances:
            # 回退到 recs 中的 variance_pct
            variances = [r.get("variance_pct") for r in recs if r.get("variance_pct") is not None]
        if not variances:
            return 60.0  # 无数据 → 中等偏下

        avg_dev = abs(sum(variances) / len(variances))
        # 0% 偏差 → 100, 每 1% 偏差扣 5 分, 下限 0
        score = max(0, 100 - avg_dev * 5)
        return round(score, 1)

    def _score_quality_grade(
        self,
        recs: List[Dict[str, Any]],
        costs: List[Dict[str, Any]],
    ) -> float:
        """质量等级: 基于 VLM 质检评级分布。

        A=100, B=75, C=40, D=10; 加权平均。
        """
        grade_map = {"A": 100, "B": 75, "C": 40, "D": 10}
        grades: List[str] = []

        for r in recs:
            g = r.get("vlm_grade") or r.get("quality_grade")
            if g:
                grades.append(str(g))
        for c in costs:
            g = c.get("quality_grade")
            if g and c.get("supplier") not in {
                r.get("supplier") for r in recs
            }:
                grades.append(str(g))

        if not grades:
            return 60.0

        score = sum(grade_map.get(g, 60) for g in grades) / len(grades)
        return round(score, 1)

    def _score_delivery_reliability(
        self,
        recs: List[Dict[str, Any]],
    ) -> float:
        """交货可靠性: 准时率 + 历史稳定性。

        准时交货比例 × 100; 无数据则 70。
        """
        if not recs:
            return 70.0

        n = len(recs)
        on_time = sum(1 for r in recs if self._is_on_time(r))
        on_time_rate = on_time / n

        # 准时率 100% → 100, <100% → 按比例
        score = on_time_rate * 100

        # 批次少 (<3) 时加不确定性惩罚
        if n < 3:
            score *= 0.85

        return round(score, 1)

    def _score_quantity_accuracy(
        self,
        recs: List[Dict[str, Any]],
        costs: List[Dict[str, Any]],
    ) -> float:
        """数量准确性: 基于短重率 (variance_pct)。

        PO 重量与实际收货偏差的绝对值; 0 偏差 → 100, 每 1% 偏差扣 4 分。
        """
        shorts = []
        for r in recs:
            v = r.get("variance_pct")
            if v is not None:
                shorts.append(v)
        for c in costs:
            v = c.get("variance_pct")
            if v is not None:
                shorts.append(v)

        if not shorts:
            return 70.0

        avg_short = abs(sum(shorts) / len(shorts))
        score = max(0, 100 - avg_short * 4)
        return round(score, 1)

    def _score_response_flexibility(
        self,
        recs: List[Dict[str, Any]],
    ) -> float:
        """响应灵活性: 基于批次分散度 (供应商供货频次/覆盖天数)。

        频次越高 → 响应越灵活; 默认 60。
        """
        if not recs:
            return 60.0

        # 统计最近 90 天覆盖了多少个不同日期
        dates = set()
        for r in recs:
            created = r.get("created_at")
            if created:
                if isinstance(created, str):
                    created = created[:10]
                dates.add(str(created))

        # 覆盖天数 > 30 → 高灵活, 10-30 → 中等, <10 → 偏低
        coverage = len(dates)
        if coverage >= 30:
            return 90.0
        elif coverage >= 15:
            return 75.0
        elif coverage >= 5:
            return 60.0
        else:
            return 40.0

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _filter_by_supplier(
        records: List[Dict[str, Any]],
        supplier_name: str,
        store_id: Optional[str],
        sku: Optional[str],
        cutoff: datetime,
    ) -> List[Dict[str, Any]]:
        """筛选: supplier + store + sku + 时间窗口"""
        result = []
        for r in records:
            if r.get("supplier") != supplier_name and r.get("supplier_id") != supplier_name:
                continue
            if store_id and r.get("store_id") and r.get("store_id") != store_id:
                continue
            if sku and r.get("sku") and r.get("sku") != sku:
                continue
            # 时间过滤
            created = r.get("created_at")
            if created:
                if isinstance(created, str):
                    try:
                        created = datetime.fromisoformat(created.replace("Z", "+00:00"))
                    except (ValueError, TypeError):
                        pass
                if isinstance(created, datetime) and created < cutoff:
                    continue
            result.append(r)
        return result

    @staticmethod
    def _filter_records(
        records: List[Dict[str, Any]],
        store_id: str,
        sku: str,
    ) -> List[Dict[str, Any]]:
        return [
            r for r in records
            if r.get("store_id", store_id) == store_id
            and r.get("sku", sku) == sku
        ]

    @staticmethod
    def _is_on_time(record: Dict[str, Any]) -> bool:
        """简易准时判定: status 含 'complete' 或 variance_pct 在 ±3% 内视为正常到货。"""
        status = record.get("status", "")
        if "complete" in str(status).lower():
            return True
        v = record.get("variance_pct")
        if v is not None and abs(v) <= 3:
            return True
        return False
