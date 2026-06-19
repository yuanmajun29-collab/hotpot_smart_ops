"""Cost analytics routes (P1B 损耗预测切入).

LOSS-402: read-only loss-risk rule baseline over the store's cost snapshot. This is
the minimal stub Codex review asked for — proves the /v1/cost/loss-risk contract and
store scope before the LLM forecast layer (wedge plan §8 L3) lands.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query, Request

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context
from cloud.event_hub.domain.loss_risk import compute_loss_risk
from cloud.event_hub.routers._deps import resolve_store_id as _resolve_store_id

router = APIRouter()


@router.get("/v1/cost/loss-risk")
def cost_loss_risk(
    request: Request,
    store_id: Optional[str] = Query(None),
    top_n: int = Query(5, ge=1, le=50),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Top-N loss-risk (rule baseline) for a store — read-only (LOSS-402)."""
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    cost_stats = runtime.hub.get_store(sid).cost_stats or {"store_id": sid, "items": []}
    risks = compute_loss_risk(cost_stats, top_n=top_n)
    return {
        "store_id": sid,
        "baseline": "rule",
        "risks": risks,
        "count": len(risks),
    }
