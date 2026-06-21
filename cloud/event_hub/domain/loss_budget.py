"""Loss-budget rule/LLM baseline (LOSS-505 · P1B).

Builds on the loss-risk rule baseline (LOSS-402): each risk becomes a budget line
(budget_loss_amount). When an LLM forecast map is supplied, forecast_qty/unit are
filled; otherwise they stay None with source="rule". The next-day复盘 backfills
actual_loss_amount and variance_pct. Pure function: no FastAPI / state dependency.

Frozen contract: docs/kitchen_loss_budget_solution.md §2.1.
"""

from __future__ import annotations

import math
from typing import Any, Dict, Optional

from cloud.event_hub.domain.loss_risk import compute_loss_risk


def _clean_forecast(value: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Normalize one LLM forecast entry and reject unsafe quantities."""
    raw_qty = value.get("forecast_qty")
    try:
        qty = float(raw_qty)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(qty) or qty < 0:
        return None
    unit = value.get("forecast_unit")
    if not isinstance(unit, str) or not unit.strip():
        unit = "份"
    reason = value.get("reason")
    if not isinstance(reason, str):
        reason = ""
    return {
        "forecast_qty": int(qty) if qty.is_integer() else round(qty, 2),
        "forecast_unit": unit.strip()[:16],
        "reason": reason.strip()[:160],
    }


def compute_loss_budget(
    cost_stats: Dict[str, Any],
    *,
    limit: int = 10,
    actuals: Optional[Dict[str, float]] = None,
    forecasts: Optional[Dict[str, Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Return loss-budget items + totals from a cost snapshot.

    ``actuals`` maps a budget line's ``ref_id`` to the realized loss amount
    (next-day复盘); when present, ``variance_pct = (actual - budget)/budget*100``.

    ``forecasts`` maps ``ref_id`` to ``{forecast_qty, forecast_unit, reason}`` from
    the LLM 备货预测 (LOSS-505+). When a line gets a forecast its forecast_qty/unit
    are filled and the forecast reason merged; the result ``forecasted`` flag lets
    the caller set source="rule+llm" vs "rule".
    """
    actuals = actuals or {}
    forecasts = forecasts or {}
    items = []
    forecasted = False
    for r in compute_loss_risk(cost_stats, limit=limit):
        budget = float(r.get("estimated_loss_amount") or 0.0)
        ref_id = r.get("ref_id")
        actual = actuals.get(ref_id)
        variance = None
        if actual is not None and budget:
            variance = round((actual - budget) / budget * 100, 1)
        reason = r.get("reason")
        fc = forecasts.get(ref_id) or {}
        clean_fc = _clean_forecast(fc) if isinstance(fc, dict) else None
        forecast_qty = clean_fc["forecast_qty"] if clean_fc else None
        forecast_unit = clean_fc["forecast_unit"] if clean_fc else None
        if clean_fc is not None:
            forecasted = True
            if clean_fc.get("reason"):
                reason = "；".join(p for p in (reason, clean_fc["reason"]) if p)
        items.append(
            {
                "sku": r.get("sku"),
                "forecast_qty": forecast_qty,   # None → rule baseline; set → LLM 备货量
                "forecast_unit": forecast_unit,
                "budget_loss_amount": budget,
                "actual_loss_amount": actual,
                "variance_pct": variance,
                "reason": reason,
                "suggested_action": r.get("suggested_action"),
                "ref_type": r.get("ref_type"),
                "ref_id": ref_id,
            }
        )
    actual_vals = [i["actual_loss_amount"] for i in items if i["actual_loss_amount"] is not None]
    return {
        "items": items,
        "forecasted": forecasted,
        "budget_loss_amount_total": round(sum(i["budget_loss_amount"] for i in items), 2),
        "actual_loss_amount_total": round(sum(actual_vals), 2) if actual_vals else None,
    }
