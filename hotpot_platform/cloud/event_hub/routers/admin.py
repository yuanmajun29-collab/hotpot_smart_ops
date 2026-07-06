"""Admin routes."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException, Query

from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import AuthContext, get_auth_context, enforce_admin, data_scope_for_role
from hotpot_platform.cloud.event_hub.device_stub import get_pipeline_status, run_subprocess_pipeline, tick_all_stores_inprocess, tick_store_inprocess
from hotpot_platform.cloud.event_hub.routers._deps import AdminStoreCreate, AdminStoreUpdate, PipelineTickBody

router = APIRouter()


@router.get("/v1/admin/org-tree")
def admin_org_tree(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    enforce_admin(auth)
    return runtime.org_registry.get_org_tree()


@router.get("/v1/admin/stores")
def admin_list_stores(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    enforce_admin(auth)
    stores = runtime.org_registry.list_stores()
    pipeline_by_id = {r["store_id"]: r for r in get_pipeline_status(runtime.hub)}
    for s in stores:
        sid = s.get("store_id")
        if sid:
            row = pipeline_by_id.get(sid, {})
            s["has_data"] = runtime.hub.get_store(sid).has_data()
            s["layers"] = row.get("layers", {})
            s["pipeline_pct"] = row.get("pipeline_pct", 0)
    return {"stores": stores, "count": len(stores)}


@router.post("/v1/admin/stores")
def admin_create_store(
    body: AdminStoreCreate,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    enforce_admin(auth)
    try:
        item = runtime.org_registry.create_store(
            body.store_name,
            body.region_id,
            city=body.city,
            store_type=body.store_type,
            status=body.status,
            actor=auth.sub,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    runtime.org_registry.apply_to_hub(runtime.hub)
    tick_store_inprocess(runtime.hub, item["store_id"], item["store_name"])
    return {"ok": True, "store": item}


@router.put("/v1/admin/stores/{store_id}")
def admin_update_store(
    store_id: str,
    body: AdminStoreUpdate,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    enforce_admin(auth)
    fields = body.model_dump(exclude_none=True)
    try:
        item = runtime.org_registry.update_store(store_id, actor=auth.sub, **fields)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    runtime.org_registry.apply_to_hub(runtime.hub)
    return {"ok": True, "store": item}


@router.get("/v1/admin/users")
def admin_list_users(auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    enforce_admin(auth)
    from hotpot_platform.cloud.event_hub.auth import DEMO_USERS

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


@router.get("/v1/admin/audit-logs")
def admin_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    enforce_admin(auth)
    logs = runtime.org_registry.list_audit(limit=limit)
    return {"logs": logs, "count": len(logs)}


@router.get("/v1/admin/pipeline/status")
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


@router.post("/v1/admin/pipeline/tick")
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
