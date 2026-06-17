"""FastAPI Event Hub (DEV-101 + DEV-102)."""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_START_TIME = time.time()

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from cloud.event_hub.auth import (
    AUTH_MODE,
    AuthContext,
    TokenRequest,
    can_admin,
    data_scope_for_role,
    enforce_action,
    enforce_admin,
    enforce_store_read,
    enforce_store_write,
    get_auth_context,
    login_user,
)
from cloud.alert_gateway.gateway import AlertGateway
from cloud.event_hub.device_stub import (
    get_pipeline_status,
    run_subprocess_pipeline,
    tick_all_stores_inprocess,
    tick_store_inprocess,
)
from cloud.event_hub.org_registry import org_registry
from cloud.event_hub.db import create_hub_database
from cloud.event_hub.daily_report_store import daily_report_store
from cloud.event_hub.daily_scheduler import DailyReportScheduler, generate_daily_report_for_store
from cloud.event_hub.iot_readings_store import iot_readings_store
from cloud.event_hub.receiving_store import new_batch_id, receiving_store, variance_pct
from cloud.event_hub.sop_assign_store import sop_assign_store
from cloud.event_hub.hub_core import DEFAULT_STORE_ID, MultiTenantHub, seed_from_directory

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DB = PROJECT_ROOT / "demo" / "data" / "hub.db"
DEFAULT_ALERT_DB = PROJECT_ROOT / "demo" / "data" / "hub_alerts.db"

from cloud.event_hub import runtime
from cloud.event_hub.routers._deps import (
    resolve_store_id as _resolve_store_id,
    _enforce_report_generate,
    _append_cost_item,
    SopAskBody, AlertAckBody, SignatureInput, ReceivingSubmitBody,
    SopAssignBody, SopAssignStatusBody, IotReadingInput, IotReadingsBatchBody,
    DailyReportGenerateBody, AdminStoreCreate, AdminStoreUpdate, PipelineTickBody,
)

_db_path = Path(os.environ.get("HOTPOT_DB", str(DEFAULT_DB)))
_database_url = os.environ.get("HOTPOT_DATABASE_URL", "")
_alert_db_path = Path(os.environ.get("HOTPOT_ALERT_DB", str(_db_path if not _database_url else DEFAULT_ALERT_DB)))

_db = create_hub_database(_db_path, _database_url)
runtime.init(
    MultiTenantHub(on_persist=_db.on_persist),
    _db,
    AlertGateway(_alert_db_path),
)
_daily_scheduler: Optional[DailyReportScheduler] = None


def __getattr__(name: str):
    """Delegate reads of hub/db/alert_gateway to runtime (test compat)."""
    if name in ("hub", "db", "alert_gateway"):
        return getattr(runtime, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

app = FastAPI(title="Hotpot Event Hub", version="2.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def startup() -> None:
    org_registry.apply_to_hub(runtime.hub)
    seed_dir = os.environ.get("HOTPOT_SEED_DIR", "")
    if not runtime.db.is_empty():
        runtime.db.hydrate_hub(runtime.hub)
        print(f"[EventHub] Hydrated from {runtime.db.db_path}")
    elif seed_dir:
        n = seed_from_directory(runtime.hub, Path(seed_dir))
        print(f"[EventHub] Seeded {n} store(s) from {seed_dir}")
    else:
        print("[EventHub] Started empty (no DB data, no seed dir)")

    if os.environ.get("HOTPOT_DAILY_REPORT_SCHEDULER", "1") == "1":

        def _gen(sid: str, push: bool) -> Dict[str, Any]:
            return generate_daily_report_for_store(runtime.hub, runtime.db, runtime.alert_gateway, sid, push=push)

        global _daily_scheduler
        _daily_scheduler = DailyReportScheduler(_gen)
        _daily_scheduler.start()




@app.get("/v1/audit/acks")
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




@app.post("/v1/reports/daily/generate")
def daily_report_generate(
    body: DailyReportGenerateBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    if sid == "*":
        sid = DEFAULT_STORE_ID
    enforce_store_read(auth, sid)
    _enforce_report_generate(auth)
    return generate_daily_report_for_store(
        runtime.hub,
        runtime.db,
        runtime.alert_gateway,
        sid,
        push=body.push,
        report_date=body.report_date,
    )


@app.get("/v1/reports/daily")
def daily_report_list(
    request: Request,
    store_id: Optional[str] = Query(None),
    report_date: Optional[str] = Query(None),
    limit: int = Query(30, ge=1, le=90),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    reports = daily_report_store(runtime.db).list_reports(sid, limit=limit, report_date=report_date)
    return {"store_id": sid, "reports": reports, "count": len(reports)}



@app.get("/benchmark")
def benchmark(
    region_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    if auth.role not in ("区域督导", "总部PMO") and auth.store_id != "*" and AUTH_MODE != "demo":
        if auth.auth_type != "anonymous":
            pass
    return runtime.hub.get_region_overview(region_id)


@app.get("/v1/region/overview")
def region_overview(
    region_id: Optional[str] = Query(None, description="e.g. region_taizhou"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Regional rollup · health matrix · anomaly stores (F-HQ06/F-HQ07)."""
    return runtime.hub.get_region_overview(region_id)



@app.get("/v1/national/overview")
def national_overview(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    """National rollup across all zones (F-HQ12)."""
    if auth.role not in ("区域督导", "总部PMO", "总部 IT") and auth.store_id != "*":
        if AUTH_MODE == "strict" and auth.auth_type != "anonymous":
            pass
    return runtime.hub.get_national_overview()


@app.get("/v1/admin/org-tree")
def admin_org_tree(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    enforce_admin(auth)
    return org_registry.get_org_tree()


@app.get("/v1/admin/stores")
def admin_list_stores(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    enforce_admin(auth)
    stores = org_registry.list_stores()
    pipeline_by_id = {r["store_id"]: r for r in get_pipeline_status(runtime.hub)}
    for s in stores:
        sid = s.get("store_id")
        if sid:
            row = pipeline_by_id.get(sid, {})
            s["has_data"] = runtime.hub.get_store(sid).has_data()
            s["layers"] = row.get("layers", {})
            s["pipeline_pct"] = row.get("pipeline_pct", 0)
    return {"stores": stores, "count": len(stores)}


@app.post("/v1/admin/stores")
def admin_create_store(
    body: AdminStoreCreate,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    enforce_admin(auth)
    try:
        item = org_registry.create_store(
            body.store_name,
            body.region_id,
            city=body.city,
            store_type=body.store_type,
            status=body.status,
            actor=auth.sub,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    org_registry.apply_to_hub(runtime.hub)
    tick_store_inprocess(runtime.hub, item["store_id"], item["store_name"])
    return {"ok": True, "store": item}


@app.put("/v1/admin/stores/{store_id}")
def admin_update_store(
    store_id: str,
    body: AdminStoreUpdate,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    enforce_admin(auth)
    fields = body.model_dump(exclude_none=True)
    try:
        item = org_registry.update_store(store_id, actor=auth.sub, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    org_registry.apply_to_hub(runtime.hub)
    return {"ok": True, "store": item}


@app.get("/v1/admin/users")
def admin_list_users(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    enforce_admin(auth)
    from cloud.event_hub.auth import DEMO_USERS

    users = []
    for (username, _password), info in DEMO_USERS.items():
        role = info["role"]
        users.append(
            {
                "username": username,
                "name": info["name"],
                "role": role,
                "store_id": info.get("store_id", "store_yuhuan"),
                "data_scope": data_scope_for_role(role),
                "source": "demo_stub",
            }
        )
    return {"users": users, "count": len(users), "note": "Phase 2: 迁移至 users 表"}


@app.get("/v1/admin/audit-logs")
def admin_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    enforce_admin(auth)
    logs = org_registry.list_audit(limit=limit)
    return {"logs": logs, "count": len(logs)}


@app.get("/v1/admin/pipeline/status")
def admin_pipeline_status(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    enforce_admin(auth)
    rows = get_pipeline_status(runtime.hub)
    total_ready = sum(r["ready_count"] for r in rows)
    total_layers = sum(r["total_layers"] for r in rows) or 1
    return {
        "stores": rows,
        "summary": {
            "store_count": len(rows),
            "avg_pipeline_pct": round(total_ready / total_layers * 100, 1),
            "stub_mode": True,
            "layers": ["vision", "iot", "pos", "sop", "erp", "cost", "events"],
        },
    }


@app.post("/v1/admin/pipeline/tick")
def admin_pipeline_tick(
    body: PipelineTickBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    enforce_admin(auth)
    if body.store_id:
        meta = runtime.hub._registry.get(body.store_id, {})
        name = meta.get("store_name", body.store_id)
        if body.mode == "subprocess":
            result = run_subprocess_pipeline(
                body.store_id, name, body.hub_url, inject_anomaly=body.inject_anomaly
            )
        else:
            result = tick_store_inprocess(
                runtime.hub, body.store_id, name, inject_anomaly=body.inject_anomaly
            )
        return {"ok": True, "results": [result]}
    if body.mode == "subprocess":
        results = []
        for sid, meta in sorted(runtime.hub._registry.items()):
            results.append(
                run_subprocess_pipeline(
                    sid, meta.get("store_name", sid), body.hub_url, inject_anomaly=body.inject_anomaly
                )
            )
        return {"ok": all(r.get("ok", False) for r in results), "results": results}
    results = tick_all_stores_inprocess(runtime.hub, inject_anomaly=body.inject_anomaly)
    return {"ok": True, "results": results}



@app.get("/alerts/routes")
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


@app.post("/alerts/test-push")
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


@app.get("/alerts/push-log")
def alerts_push_log(
    request: Request,
    store_id: Optional[str] = Query(None),
    limit: int = Query(20),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    return {"store_id": sid, "pushes": runtime.alert_gateway.list_pushes(sid, limit)}


@app.get("/alerts/acks")
def alerts_acks(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    return {"store_id": sid, "acks": runtime.alert_gateway.list_acks(sid)}


@app.post("/alerts/ack")
def alerts_ack(
    body: AlertAckBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    enforce_action(auth, "ack")
    ack_by = body.ack_by or auth.sub or "店长"
    return runtime.alert_gateway.ack(body.event_id, sid, ack_by, body.ack_note or "")


@app.get("/alerts/escalations")
def alerts_escalations(
    request: Request,
    store_id: Optional[str] = Query(None),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    events = runtime.hub.get_store(sid).get_events("critical", 100)
    return {"store_id": sid, **runtime.alert_gateway.count_escalations(sid, events)}


from cloud.event_hub.routers import system as _system_router
from cloud.event_hub.routers import auth_routes as _auth_routes_router
from cloud.event_hub.routers import ingest as _ingest_router
from cloud.event_hub.routers import receiving as _receiving_router
from cloud.event_hub.routers import sop as _sop_router
from cloud.event_hub.routers import iot as _iot_router

app.include_router(_system_router.router)
app.include_router(_auth_routes_router.router)
app.include_router(_ingest_router.router)
app.include_router(_receiving_router.router)
app.include_router(_sop_router.router)
app.include_router(_iot_router.router)
