"""FastAPI endpoints for cloud-side analytics."""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from hotpot_platform.analytics.ai_suggestions import SuggestionEngine
from hotpot_platform.analytics.store_compare import StoreCompareEngine
from hotpot_platform.analytics.trend_engine import TrendEngine
from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import (
    AuthContext,
    auth_mode,
    enforce_store_read,
    get_auth_context,
)

router = APIRouter(tags=["analytics"])
ROUTER_TAG = "analytics"


class SuggestionStatusBody(BaseModel):
    status: str


def _enforce_analytics_read(auth: AuthContext) -> None:
    if auth_mode() == "demo" and auth.auth_type == "anonymous":
        return
    if auth.store_id == "*" or auth.role in ("区域督导", "总部PMO", "总部 IT", "集团决策者", "大区运营"):
        return
    raise HTTPException(status_code=403, detail="Analytics requires region or HQ scope")


def _enforce_analytics_store_read(auth: AuthContext, store_id: str) -> None:
    if auth_mode() == "demo" and auth.auth_type == "anonymous":
        return
    enforce_store_read(auth, store_id)


def _engines() -> tuple[StoreCompareEngine, TrendEngine, SuggestionEngine]:
    trend = TrendEngine(runtime.hub, runtime.db)
    compare = StoreCompareEngine(runtime.hub, runtime.db, trend)
    suggestions = SuggestionEngine(runtime.hub, runtime.db, compare)
    return compare, trend, suggestions


@router.get("/api/analytics/compare")
def analytics_compare(
    zone_id: Optional[str] = Query(None),
    region_id: Optional[str] = Query(None),
    days: int = Query(7, ge=1, le=365),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    _enforce_analytics_read(auth)
    compare, _, _ = _engines()
    return compare.compare(zone_id=zone_id, region_id=region_id, days=days)


@router.get("/api/analytics/trends/{store_id}")
def analytics_trends(
    store_id: str,
    metric: str = Query("waste"),
    days: int = Query(30, ge=1, le=365),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    _enforce_analytics_store_read(auth, store_id)
    _, trend, _ = _engines()
    return trend.trend(store_id=store_id, metric=metric, days=days)


@router.get("/api/analytics/suggestions/{store_id}")
def analytics_suggestions(
    store_id: str,
    days: int = Query(7, ge=1, le=365),
    refresh: bool = Query(True),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    _enforce_analytics_store_read(auth, store_id)
    _, _, suggestions = _engines()
    return suggestions.suggestions_for_store(store_id, days=days, refresh=refresh)


@router.post("/api/analytics/suggestions/{store_id}/{suggestion_id}/status")
def analytics_suggestion_status(
    store_id: str,
    suggestion_id: str,
    body: SuggestionStatusBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    _enforce_analytics_store_read(auth, store_id)
    _, _, suggestions = _engines()
    try:
        item = suggestions.update_status(store_id, suggestion_id, body.status, actor=auth.sub)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="suggestion not found") from exc
    return {"ok": True, "suggestion": item}


@router.get("/api/analytics/dashboard/{zone_id}")
def analytics_dashboard(
    zone_id: str,
    days: int = Query(7, ge=1, le=365),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    _enforce_analytics_read(auth)
    compare, _, _ = _engines()
    return compare.dashboard(zone_id=zone_id, days=days)
