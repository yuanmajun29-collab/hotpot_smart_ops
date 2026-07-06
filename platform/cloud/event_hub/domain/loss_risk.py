"""Loss-risk rule baseline (LOSS-402 · P1B 切入).

Pure function: aggregates a store's cost snapshot into a Top-N loss-risk list with
a risk_score, a human reason, and a suggested action. This is the rule baseline the
later LLM forecast (see kitchen_loss_prediction_wedge_plan.md §8 L3) will replace /
augment. No FastAPI / state dependency.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

# Frozen-item temperature ceiling (°C); above this is a cold-chain risk.
_FROZEN_TEMP_CEIL = -12.0
_LOW_GRADES = {"C", "D"}
# Fallback unit price (¥/kg) for the rule baseline loss estimate when the item
# carries no explicit price. Refined once ERP price feeds land (P1B+).
_DEFAULT_PRICE_PER_KG = 80.0


def _estimated_loss_amount(item: Dict[str, Any], grade: str, var: Optional[float]) -> float:
    """Rough rule-baseline loss estimate (¥). Short weight uses the kg shortfall ×
    unit price; quality/temperature risks add a nominal share of batch value."""
    price = item.get("unit_price")
    price = float(price) if price is not None else _DEFAULT_PRICE_PER_KG
    weight = item.get("weight_kg")
    po_weight = item.get("po_weight_kg")
    amount = 0.0
    if weight is not None and po_weight is not None and po_weight > weight:
        amount += (po_weight - weight) * price
    if grade in _LOW_GRADES and weight is not None:
        amount += (0.10 if grade == "D" else 0.05) * weight * price
    return round(amount, 2)


def _score_item(item: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    reasons: List[str] = []
    actions: List[str] = []
    score = 0.0

    var = item.get("variance_pct")
    if var is not None and var < -3:
        score += min(50.0, abs(var) * 5)
        reasons.append(f"短重 {var:.1f}%")
        actions.append("复称并留证，必要时退货")

    grade = (item.get("vlm_grade") or "").upper()
    if grade in _LOW_GRADES:
        score += 40.0 if grade == "D" else 30.0
        reasons.append(f"品质等级 {grade}")
        actions.append("优先消耗或拒收")

    temp = item.get("temp_c")
    if temp is not None and temp > _FROZEN_TEMP_CEIL:
        score += 20.0
        reasons.append(f"温度 {temp:.1f}℃ 偏高")
        actions.append("核查冷链与解冻流程")

    if score <= 0:
        return None
    batch_id = item.get("batch_id")
    return {
        "batch_id": batch_id,
        "sku": item.get("sku"),
        "po_id": item.get("po_id"),
        "risk_score": round(min(100.0, score), 1),
        "estimated_loss_amount": _estimated_loss_amount(item, grade, var),
        "reason": "；".join(reasons),
        "suggested_action": "；".join(actions),
        # Traceability back to the source batch (aligns with F-TRACE ref model).
        "ref_type": "receiving_batch",
        "ref_id": batch_id,
        "variance_pct": var,
        "vlm_grade": item.get("vlm_grade"),
    }


def compute_loss_risk(cost_stats: Dict[str, Any], limit: int = 10) -> List[Dict[str, Any]]:
    """Return Top-N loss-risk items (highest risk first) from a cost snapshot."""
    items = (cost_stats or {}).get("items") or []
    risks = [r for r in (_score_item(i) for i in items) if r is not None]
    risks.sort(key=lambda r: (-r["risk_score"], str(r.get("batch_id") or "")))
    return risks[: max(1, limit)]
