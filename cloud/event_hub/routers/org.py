"""Org/region/national overview routes."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Query

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context, AUTH_MODE

router = APIRouter()


@router.get("/benchmark")
def benchmark(
    region_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    if auth.role not in ("区域督导", "总部PMO") and auth.store_id != "*" and AUTH_MODE != "demo":
        if auth.auth_type != "anonymous":
            pass
    return runtime.hub.get_region_overview(region_id)


@router.get("/v1/region/overview")
def region_overview(
    region_id: Optional[str] = Query(None, description="e.g. region_taizhou"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Regional rollup · health matrix · anomaly stores (F-HQ06/F-HQ07)."""
    return runtime.hub.get_region_overview(region_id)


@router.get("/v1/national/overview")
def national_overview(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    """National rollup across all zones (F-HQ12)."""
    if auth.role not in ("区域督导", "总部PMO", "总部 IT") and auth.store_id != "*":
        if AUTH_MODE == "strict" and auth.auth_type != "anonymous":
            pass
    return runtime.hub.get_national_overview()
