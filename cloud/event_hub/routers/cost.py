"""Cost analytics routes (P1B 损耗预测切入).

LOSS-402: read-only loss-risk rule baseline over the store's cost snapshot. This is
the minimal stub Codex review asked for — proves the /v1/cost/loss-risk contract and
store scope before the LLM forecast layer (wedge plan §8 L3) lands.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from cloud.event_hub import runtime
from cloud.event_hub.auth import (
    AuthContext, get_auth_context, enforce_store_write, enforce_action,
)
from cloud.event_hub.domain.loss_risk import compute_loss_risk
from cloud.event_hub.domain.loss_budget import compute_loss_budget
from cloud.event_hub.hub_core import DEFAULT_STORE_ID
from cloud.event_hub.routers._deps import resolve_store_id as _resolve_store_id
from cloud.event_hub.task_store import task_store, TaskError
from shared.schemas import utc_now_iso

_STORE_TZ = "Asia/Shanghai"

router = APIRouter()


def _risk_priority(score: float) -> str:
    return "P0" if score >= 70 else "P1" if score >= 40 else "P2"


class RiskToTaskBody(BaseModel):
    store_id: Optional[str] = None
    assignee_id: Optional[str] = None
    assignee_group: Optional[str] = None


def _business_date(date: Optional[str]) -> str:
    return date or datetime.now(ZoneInfo(_STORE_TZ)).strftime("%Y-%m-%d")


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
        "date": _business_date(date),
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
        "date": _business_date(date),
        "generated_at": utc_now_iso(),
        "source": "rule",
        "items": result["items"],
        "budget_loss_amount_total": result["budget_loss_amount_total"],
        "actual_loss_amount_total": result["actual_loss_amount_total"],
    }


@router.post("/v1/cost/loss-risk/{batch_id}/task")
def loss_risk_to_task(
    batch_id: str,
    body: RiskToTaskBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """风险一键转复称任务（LOSS-506）。

    把指定批次的损耗风险转成 recheck_weight（复称留证）任务，复用任务引擎；
    source_id 保证 (店,批次) 幂等，ref 追溯到收货批次（ADR-012）。store-scoped。
    """
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    enforce_action(auth, "task_create")
    cost_stats = runtime.hub.get_store(sid).cost_stats or {"store_id": sid, "items": []}
    risks = compute_loss_risk(cost_stats, limit=1000)
    risk = next((r for r in risks if (r.get("ref_id") or r.get("batch_id")) == batch_id), None)
    if risk is None:
        raise HTTPException(status_code=404, detail=f"无该批次损耗风险: {batch_id}")

    sku = risk.get("sku") or batch_id
    actor = auth.sub or auth.role or "user"
    try:
        task = task_store(runtime.db).create(
            sid,
            task_type="recheck_weight",
            title=f"复称留证：{sku}（{risk.get('reason', '')}）",
            created_by=actor,
            priority=_risk_priority(risk.get("risk_score", 0)),
            source="loss_risk",
            ref_type="receiving_batch",
            ref_id=batch_id,
            assignee_id=body.assignee_id,
            assignee_group=body.assignee_group,
            detail=risk.get("suggested_action", ""),
            source_id=f"loss-risk:{sid}:{batch_id}:recheck",
        )
    except TaskError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "task": task, "risk": risk}
