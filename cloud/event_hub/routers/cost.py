"""Cost analytics routes (P1B 损耗预测切入).

LOSS-402: read-only loss-risk rule baseline over the store's cost snapshot. This is
the minimal stub Codex review asked for — proves the /v1/cost/loss-risk contract and
store scope before the LLM forecast layer (wedge plan §8 L3) lands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Query, Request

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context
from cloud.event_hub.domain.loss_risk import compute_loss_risk
from cloud.event_hub.domain.loss_budget import compute_loss_budget
from cloud.event_hub.routers._deps import resolve_store_id as _resolve_store_id
from shared.schemas import utc_now_iso

_STORE_TZ = "Asia/Shanghai"

router = APIRouter()


@router.get("/v1/cost/loss-risk")
def cost_loss_risk(
    request: Request,
    store_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None, description="业务日期，默认今日"),
    limit: int = Query(10, ge=1, le=50, description="TopN 条数，默认 10"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Top-N loss-risk (rule baseline) for a store — read-only (LOSS-402).

    Contract per architecture_api_spec §3. `date` is accepted for forward
    compatibility; the rule baseline currently scores the latest cost snapshot
    (cross-day replay lands with the feature_builder, see wedge §8.4).
    """
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    cost_stats = runtime.hub.get_store(sid).cost_stats or {"store_id": sid, "items": []}
    risks = compute_loss_risk(cost_stats, limit=limit)
    return {
        "store_id": sid,
        "date": date,
        "baseline": "rule",
        "risks": risks,
        "count": len(risks),
        "estimated_loss_amount_total": round(
            sum(r.get("estimated_loss_amount", 0) for r in risks), 2
        ),
    }


@router.get("/v1/cost/loss-budget")
def cost_loss_budget(
    request: Request,
    store_id: Optional[str] = Query(None),
    date: Optional[str] = Query(None, description="预算日期，默认今日（门店时区）"),
    limit: int = Query(10, ge=1, le=50, description="TopN 条数，默认 10"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """损耗预算（LOSS-505）— 只读，在 loss-risk 规则基线上叠加预算维度。

    契约见 docs/kitchen_loss_budget_solution.md §2.1。LLM 备货预测尚未接线，
    故 source="rule"、forecast_qty=null；actual/variance 为次日复盘回填。
    """
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    cost_stats = runtime.hub.get_store(sid).cost_stats or {"store_id": sid, "items": []}
    result = compute_loss_budget(cost_stats, limit=limit)
    return {
        "store_id": sid,
        "date": date or datetime.now(ZoneInfo(_STORE_TZ)).strftime("%Y-%m-%d"),
        "generated_at": utc_now_iso(),
        "source": "rule",
        "items": result["items"],
        "budget_loss_amount_total": result["budget_loss_amount_total"],
        "actual_loss_amount_total": result["actual_loss_amount_total"],
    }
