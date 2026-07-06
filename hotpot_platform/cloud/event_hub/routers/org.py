"""Org/region/national overview routes."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import AuthContext, auth_mode, get_auth_context

router = APIRouter()


def _enforce_rollup_read(auth: AuthContext) -> None:
    if auth_mode() == "demo" and auth.auth_type == "anonymous":
        return
    if auth.role in ("区域督导", "总部PMO", "总部 IT", "集团决策者"):
        return
    if auth.store_id == "*":
        return
    raise HTTPException(status_code=403, detail="Rollup overview requires region or national scope")


@router.get("/benchmark", deprecated=True)
def benchmark(
    region_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    _enforce_rollup_read(auth)
    return runtime.hub.get_region_overview(region_id)


router.add_api_route("/v1/benchmark", benchmark, methods=["GET"])


@router.get("/v1/region/overview")
def region_overview(
    region_id: Optional[str] = Query(None, description="e.g. region_taizhou"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Regional rollup · health matrix · anomaly stores (F-HQ06/F-HQ07)."""
    _enforce_rollup_read(auth)
    return runtime.hub.get_region_overview(region_id)


@router.get("/v1/national/overview")
def national_overview(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    """National rollup across all zones (F-HQ12)."""
    _enforce_rollup_read(auth)
    return runtime.hub.get_national_overview()
