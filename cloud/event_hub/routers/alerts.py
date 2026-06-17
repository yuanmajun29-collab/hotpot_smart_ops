"""Alerts routes."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_write, enforce_action, AUTH_MODE
from cloud.event_hub.hub_core import DEFAULT_STORE_ID
from cloud.event_hub.receiving_store import receiving_store
from cloud.event_hub.sop_assign_store import sop_assign_store
from cloud.event_hub.routers._deps import (
    resolve_store_id as _resolve_store_id,
    AlertAckBody,
)

router = APIRouter()


@router.get("/v1/audit/acks")
def audit_acks(
    request: Request,
    store_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    acks = runtime.alert_gateway.list_acks(sid)
    signatures = receiving_store(runtime.db).list_signatures(sid, limit=limit)
    assignments = sop_assign_store(runtime.db).list_assignments(sid, limit=limit)
    return {
        "store_id": sid,
        "alert_acks": acks,
        "alert_ack_count": len(acks),
        "receiving_signatures": signatures,
        "receiving_signature_count": len(signatures),
        "sop_assignments": assignments,
        "sop_assignment_count": len(assignments),
    }


@router.get("/alerts/routes")
def alerts_routes(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Return per-store webhook config status (DEV-414). URLs are masked."""
    if store_id:
        sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
        return {"routes": [runtime.alert_gateway.route_status(sid)]}
    store_ids = sorted(set(runtime.hub._registry) | set(runtime.hub._stores))
    if not store_ids:
        store_ids = ["store_yuhuan", "store_jiaojiang"]
    return {"routes": [runtime.alert_gateway.route_status(sid) for sid in store_ids]}


@router.post("/alerts/test-push")
def alerts_test_push(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Send synthetic critical card to verify WeChat webhook (DEV-414 checklist)."""
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    if AUTH_MODE != "demo" and auth.role not in ("店长", "区域督导"):
        raise HTTPException(status_code=403, detail="无 webhook 测试权限")
    return runtime.alert_gateway.send_test_push(sid)


@router.get("/alerts/push-log")
def alerts_push_log(
    request: Request,
    store_id: Optional[str] = Query(None),
    limit: int = Query(20),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    return {"store_id": sid, "pushes": runtime.alert_gateway.list_pushes(sid, limit)}


@router.get("/alerts/acks")
def alerts_acks(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    return {"store_id": sid, "acks": runtime.alert_gateway.list_acks(sid)}


@router.post("/alerts/ack")
def alerts_ack(
    body: AlertAckBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    enforce_action(auth, "ack")
    ack_by = body.ack_by or auth.sub or "店长"
    return runtime.alert_gateway.ack(body.event_id, sid, ack_by, body.ack_note or "")


@router.get("/alerts/escalations")
def alerts_escalations(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    events = runtime.hub.get_store(sid).get_events("critical", 100)
    return {"store_id": sid, **runtime.alert_gateway.count_escalations(sid, events)}
