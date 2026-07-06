"""Ingest routes."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request

from platform.cloud.event_hub import runtime
from platform.cloud.event_hub.auth import (
    AuthContext,
    enforce_action,
    enforce_store_write,
    get_auth_context,
)
from platform.cloud.event_hub.routers._deps import resolve_store_id as _resolve_store_id
from platform.cloud.event_hub.routers._deps import readable_store_ids as _readable_store_ids

router = APIRouter()


@router.get("/summary", deprecated=True)
def summary(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("x-store-id"), auth)
    return runtime.hub.get_store(sid).get_summary()


@router.get("/events", deprecated=True)
def get_events(
    request: Request,
    store_id: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    limit: int = Query(50),
    auth: AuthContext = Depends(get_auth_context),
) -> List[Dict[str, Any]]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    return runtime.hub.get_store(sid).get_events(level, limit)


@router.get("/tables", deprecated=True)
def get_tables(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> List[Dict[str, Any]]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    return list(runtime.hub.get_store(sid).table_states.values())


@router.get("/sop", deprecated=True)
def get_sop(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    store = runtime.hub.get_store(sid)
    return store.sop_stats or {"store_id": sid, "results": []}


@router.get("/pos", deprecated=True)
def get_pos(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    store = runtime.hub.get_store(sid)
    return store.pos_stats or {"store_id": sid}


@router.get("/erp", deprecated=True)
def get_erp(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    store = runtime.hub.get_store(sid)
    return store.erp_stats or {"store_id": sid, "orders": []}


@router.get("/cost", deprecated=True)
def get_cost(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    store = runtime.hub.get_store(sid)
    return store.cost_stats or {"store_id": sid, "items": []}


@router.get("/iot", deprecated=True)
def get_iot(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    store = runtime.hub.get_store(sid)
    return store.iot_stats or {"store_id": sid, "stage_readings": {}}


@router.get("/stores", deprecated=True)
def list_stores(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    stores = runtime.hub.list_stores()
    readable = set(_readable_store_ids([s.get("store_id", "") for s in stores], auth))
    visible = [s for s in stores if s.get("store_id") in readable]
    return {"stores": visible}


@router.post("/events", deprecated=True)
async def post_event(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    event = runtime.hub.get_store(sid).add_event(data if isinstance(data, dict) else {})
    push = runtime.alert_gateway.handle_event(event, sid)
    if push:
        event = dict(event)
        event["_alert_push"] = {
            "pushed": True,
            "channel": push.get("channel"),
            "webhook_sent": push.get("webhook_sent", False),
        }
    return event


@router.post("/tables", deprecated=True)
async def post_tables(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    enforce_action(auth, "table_correct")
    tables = data if isinstance(data, list) else data.get("tables", [])
    runtime.hub.get_store(sid).set_table_states(tables)
    return {"ok": True, "store_id": sid, "count": len(tables)}


@router.post("/pos", deprecated=True)
async def post_pos(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    runtime.hub.get_store(sid).set_pos_stats(data if isinstance(data, dict) else {})
    return {"ok": True, "store_id": sid}


@router.post("/sop", deprecated=True)
async def post_sop(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    runtime.hub.get_store(sid).set_sop_stats(data if isinstance(data, dict) else {})
    return {"ok": True, "store_id": sid, "compliance_rate": data.get("compliance_rate") if isinstance(data, dict) else None}


@router.post("/cost", deprecated=True)
async def post_cost(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    runtime.hub.get_store(sid).set_cost_stats(data if isinstance(data, dict) else {})
    return {"ok": True, "store_id": sid, "variance_rate_pct": data.get("variance_rate_pct") if isinstance(data, dict) else None}


@router.post("/iot", deprecated=True)
async def post_iot(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    runtime.hub.get_store(sid).set_iot_stats(data if isinstance(data, dict) else {})
    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    return {"ok": True, "store_id": sid, "iot_alert_count": summary.get("iot_alert_count")}



@router.post("/erp", deprecated=True)
async def post_erp(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    runtime.hub.get_store(sid).set_erp_stats(data if isinstance(data, dict) else {})
    return {
        "ok": True,
        "store_id": sid,
        "order_count": data.get("order_count") if isinstance(data, dict) else None,
    }


# /v1 canonical aliases
router.add_api_route("/v1/summary", summary, methods=["GET"])
router.add_api_route("/v1/events", get_events, methods=["GET"])
router.add_api_route("/v1/tables", get_tables, methods=["GET"])
router.add_api_route("/v1/sop", get_sop, methods=["GET"])
router.add_api_route("/v1/pos", get_pos, methods=["GET"])
router.add_api_route("/v1/erp", get_erp, methods=["GET"])
router.add_api_route("/v1/cost", get_cost, methods=["GET"])
router.add_api_route("/v1/iot", get_iot, methods=["GET"])
router.add_api_route("/v1/stores", list_stores, methods=["GET"])
router.add_api_route("/v1/events", post_event, methods=["POST"])
router.add_api_route("/v1/tables", post_tables, methods=["POST"])
router.add_api_route("/v1/pos", post_pos, methods=["POST"])
router.add_api_route("/v1/sop", post_sop, methods=["POST"])
router.add_api_route("/v1/cost", post_cost, methods=["POST"])
router.add_api_route("/v1/iot", post_iot, methods=["POST"])
router.add_api_route("/v1/erp", post_erp, methods=["POST"])
