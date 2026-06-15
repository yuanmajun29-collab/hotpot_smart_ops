"""FastAPI Event Hub (DEV-101 + DEV-102)."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cloud.event_hub.auth import (
    AUTH_MODE,
    AuthContext,
    TokenRequest,
    enforce_store_read,
    enforce_store_write,
    get_auth_context,
    login_user,
)
from cloud.alert_gateway.gateway import AlertGateway
from cloud.event_hub.db import HubDatabase
from cloud.event_hub.hub_core import DEFAULT_STORE_ID, MultiTenantHub, seed_from_directory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "demo" / "data" / "hub.db"

_db_path = Path(os.environ.get("HOTPOT_DB", str(DEFAULT_DB)))
db = HubDatabase(_db_path)
hub = MultiTenantHub(on_persist=db.on_persist)
alert_gateway = AlertGateway(_db_path)

app = FastAPI(title="Hotpot Event Hub", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _resolve_store_id(
    store_id: Optional[str],
    body: Any,
    header_store: Optional[str],
    auth: AuthContext,
) -> str:
    sid = header_store or store_id
    if not sid and isinstance(body, dict):
        sid = body.get("store_id")
    if not sid and isinstance(body, list) and body and isinstance(body[0], dict):
        sid = body[0].get("store_id")
    sid = sid or DEFAULT_STORE_ID
    enforce_store_read(auth, sid)
    return sid


@app.on_event("startup")
def startup() -> None:
    seed_dir = os.environ.get("HOTPOT_SEED_DIR", "")
    if not db.is_empty():
        db.hydrate_hub(hub)
        print(f"[EventHub] Hydrated from {db.db_path}")
    elif seed_dir:
        n = seed_from_directory(hub, Path(seed_dir))
        print(f"[EventHub] Seeded {n} store(s) from {seed_dir}")
    else:
        print("[EventHub] Started empty (no DB data, no seed dir)")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {
        "status": "ok",
        "multi_tenant": True,
        "engine": "fastapi",
        "auth_mode": AUTH_MODE,
        "persistent": True,
        "alert_gateway": True,
    }


class AlertAckBody(BaseModel):
    event_id: str
    store_id: Optional[str] = None
    ack_by: Optional[str] = "店长"
    ack_note: Optional[str] = ""


@app.post("/auth/token")
def auth_token(req: TokenRequest) -> Dict[str, Any]:
    return login_user(req)


@app.get("/stores")
def list_stores(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    return {"stores": hub.list_stores()}


@app.get("/benchmark")
def benchmark(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    if auth.role not in ("区域督导",) and auth.store_id != "*" and AUTH_MODE != "demo":
        if auth.auth_type != "anonymous":
            pass  # still allow in demo; regional preferred
    return hub.get_benchmark()


@app.get("/summary")
def summary(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("x-store-id"), auth)
    return hub.get_store(sid).get_summary()


@app.get("/events")
def get_events(
    request: Request,
    store_id: Optional[str] = Query(None),
    level: Optional[str] = Query(None),
    limit: int = Query(50),
    auth: AuthContext = Depends(get_auth_context),
) -> List[Dict[str, Any]]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    return hub.get_store(sid).get_events(level, limit)


@app.get("/tables")
def get_tables(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> List[Dict[str, Any]]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    return list(hub.get_store(sid).table_states.values())


@app.get("/sop")
def get_sop(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    store = hub.get_store(sid)
    return store.sop_stats or {"store_id": sid, "results": []}


@app.get("/cost")
def get_cost(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    store = hub.get_store(sid)
    return store.cost_stats or {"store_id": sid, "items": []}


@app.get("/iot")
def get_iot(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    store = hub.get_store(sid)
    return store.iot_stats or {"store_id": sid, "stage_readings": {}}


@app.post("/events")
async def post_event(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    event = hub.get_store(sid).add_event(data if isinstance(data, dict) else {})
    push = alert_gateway.handle_event(event, sid)
    if push:
        event = dict(event)
        event["_alert_push"] = {
            "pushed": True,
            "channel": push.get("channel"),
            "webhook_sent": push.get("webhook_sent", False),
        }
    return event


@app.post("/tables")
async def post_tables(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    tables = data if isinstance(data, list) else data.get("tables", [])
    hub.get_store(sid).set_table_states(tables)
    return {"ok": True, "store_id": sid, "count": len(tables)}


@app.post("/pos")
async def post_pos(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    hub.get_store(sid).set_pos_stats(data if isinstance(data, dict) else {})
    return {"ok": True, "store_id": sid}


@app.post("/sop")
async def post_sop(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    hub.get_store(sid).set_sop_stats(data if isinstance(data, dict) else {})
    return {"ok": True, "store_id": sid, "compliance_rate": data.get("compliance_rate") if isinstance(data, dict) else None}


@app.post("/cost")
async def post_cost(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    hub.get_store(sid).set_cost_stats(data if isinstance(data, dict) else {})
    return {"ok": True, "store_id": sid, "variance_rate_pct": data.get("variance_rate_pct") if isinstance(data, dict) else None}


@app.post("/iot")
async def post_iot(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    sid = _resolve_store_id(store_id, data, request.headers.get("X-Store-Id"), auth)
    enforce_store_write(auth, sid)
    hub.get_store(sid).set_iot_stats(data if isinstance(data, dict) else {})
    summary = data.get("summary", {}) if isinstance(data, dict) else {}
    return {"ok": True, "store_id": sid, "iot_alert_count": summary.get("iot_alert_count")}


@app.get("/alerts/push-log")
def alerts_push_log(
    request: Request,
    store_id: Optional[str] = Query(None),
    limit: int = Query(20),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    return {"store_id": sid, "pushes": alert_gateway.list_pushes(sid, limit)}


@app.get("/alerts/acks")
def alerts_acks(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    return {"store_id": sid, "acks": alert_gateway.list_acks(sid)}


@app.post("/alerts/ack")
def alerts_ack(
    body: AlertAckBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    ack_by = body.ack_by or auth.sub or "店长"
    return alert_gateway.ack(body.event_id, sid, ack_by, body.ack_note or "")


@app.get("/alerts/escalations")
def alerts_escalations(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    events = hub.get_store(sid).get_events("critical", 100)
    return {"store_id": sid, **alert_gateway.count_escalations(sid, events)}


@app.post("/seed")
async def post_seed(
    request: Request,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    data = await request.json()
    if AUTH_MODE == "strict" and auth.auth_type == "anonymous":
        raise HTTPException(status_code=401, detail="Seed requires auth")
    hub.apply_seed(data if isinstance(data, dict) else {})
    return {"ok": True, "store_id": data.get("store_id", DEFAULT_STORE_ID) if isinstance(data, dict) else DEFAULT_STORE_ID}
