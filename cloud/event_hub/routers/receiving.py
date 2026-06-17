"""Receiving routes."""
from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_write, enforce_action
from cloud.event_hub.routers._deps import resolve_store_id as _resolve_store_id, ReceivingSubmitBody, _append_cost_item
from cloud.event_hub.receiving_store import new_batch_id, receiving_store, variance_pct
from cloud.event_hub.hub_core import DEFAULT_STORE_ID

router = APIRouter()


@router.post("/v1/receiving/submit")
def receiving_submit(
    body: ReceivingSubmitBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    enforce_action(auth, "receiving_submit")
    store = runtime.hub.get_store(sid)

    batch_id = body.batch_id or new_batch_id(sid)
    var = variance_pct(body.weight_kg, body.po_weight_kg)
    batch = {
        "batch_id": batch_id,
        "po_id": body.po_id,
        "sku": body.sku,
        "weight_kg": body.weight_kg,
        "po_weight_kg": body.po_weight_kg,
        "variance_pct": var,
        "vlm_grade": body.vlm_grade,
        "temp_c": body.temp_c,
        "status": "submitted",
    }
    signatures = [s.model_dump() for s in body.signatures]

    try:
        result = receiving_store(runtime.db).submit(sid, batch, signatures)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    level = "warn" if var is not None and abs(var) > 3 else "info"
    event = store.add_event(
        {
            "event_type": "receiving_submitted",
            "source": "system",
            "level": level,
            "message": f"收货 {body.sku} {body.weight_kg}kg 已入库（{batch_id}）",
            "metadata": {
                "batch_id": batch_id,
                "po_id": body.po_id,
                "sku": body.sku,
                "weight_kg": body.weight_kg,
                "variance_pct": var,
                "vlm_grade": body.vlm_grade,
                "signatures": signatures,
            },
        }
    )
    _append_cost_item(store, {**batch, "created_at": result["created_at"]}, signatures)

    return {
        "ok": True,
        "batch_id": batch_id,
        "store_id": sid,
        "variance_pct": var,
        "event_id": event.get("event_id"),
        "signatures": signatures,
    }


@router.get("/v1/receiving/batches")
def receiving_batches(
    request: Request,
    store_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    batches = receiving_store(runtime.db).list_batches(sid, limit=limit)
    return {"store_id": sid, "batches": batches, "count": len(batches)}


@router.get("/v1/audit/signatures")
def audit_signatures(
    request: Request,
    store_id: Optional[str] = Query(None),
    batch_id: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    signatures = receiving_store(runtime.db).list_signatures(sid, batch_id=batch_id, limit=limit)
    return {"store_id": sid, "signatures": signatures, "count": len(signatures)}
