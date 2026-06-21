"""Loss-budget rule baseline (LOSS-505 · P1B).

Builds on the loss-risk rule baseline (LOSS-402): each risk becomes a budget line
(budget_loss_amount). The LLM备货预测 (forecast_qty) is not wired yet, so it is
left None with source="rule"; the next-day复盘 backfills actual_loss_amount and
variance_pct. Pure function: no FastAPI / state dependency.

Frozen contract: docs/kitchen_loss_budget_solution.md §2.1.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from cloud.event_hub.domain.loss_risk import compute_loss_risk


def compute_loss_budget(
    cost_stats: Dict[str, Any],
    *,
    limit: int = 10,
    actuals: Optional[Dict[str, float]] = None,
) -> Dict[str, Any]:
    """Return loss-budget items + totals from a cost snapshot.

    ``actuals`` maps a budget line's ``ref_id`` to the realized loss amount
    (next-day复盘); when present, ``variance_pct = (actual - budget)/budget*100``.
    """
    actuals = actuals or {}
    items = []
    for r in compute_loss_risk(cost_stats, limit=limit):
        budget = float(r.get("estimated_loss_amount") or 0.0)
        ref_id = r.get("ref_id")
        actual = actuals.get(ref_id)
        variance = None
        if actual is not None and budget:
            variance = round((actual - budget) / budget * 100, 1)
        items.append(
            {
                "sku": r.get("sku"),
                "forecast_qty": None,      # LLM forecast not wired (rule baseline)
                "forecast_unit": None,
                "budget_loss_amount": budget,
                "actual_loss_amount": actual,
                "variance_pct": variance,
                "reason": r.get("reason"),
                "suggested_action": r.get("suggested_action"),
                "ref_type": r.get("ref_type"),
                "ref_id": ref_id,
            }
        )
    actual_vals = [i["actual_loss_amount"] for i in items if i["actual_loss_amount"] is not None]
    return {
        "items": items,
        "budget_loss_amount_total": round(sum(i["budget_loss_amount"] for i in items), 2),
        "actual_loss_amount_total": round(sum(actual_vals), 2) if actual_vals else None,
    }
