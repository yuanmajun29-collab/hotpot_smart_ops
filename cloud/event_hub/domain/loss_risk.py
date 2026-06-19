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
    return {
        "batch_id": item.get("batch_id"),
        "sku": item.get("sku"),
        "po_id": item.get("po_id"),
        "risk_score": round(min(100.0, score), 1),
        "reason": "；".join(reasons),
        "suggested_action": "；".join(actions),
        "variance_pct": var,
        "vlm_grade": item.get("vlm_grade"),
    }


def compute_loss_risk(cost_stats: Dict[str, Any], top_n: int = 5) -> List[Dict[str, Any]]:
    """Return Top-N loss-risk items (highest risk first) from a cost snapshot."""
    items = (cost_stats or {}).get("items") or []
    risks = [r for r in (_score_item(i) for i in items) if r is not None]
    risks.sort(key=lambda r: (-r["risk_score"], str(r.get("batch_id") or "")))
    return risks[: max(1, top_n)]
