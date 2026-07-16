"""Receiving routes."""
from __future__ import annotations

from typing import Any, Dict, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from datetime import datetime, timezone

from hotpot_platform.cloud.event_hub import runtime
from hotpot_platform.cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_write, enforce_action
from hotpot_platform.cloud.event_hub.routers._deps import resolve_store_id as _resolve_store_id, ReceivingSubmitBody, ReceivingCheckinBody, _append_cost_item
from hotpot_platform.cloud.event_hub.receiving_store import new_batch_id, receiving_store, variance_pct
from hotpot_platform.cloud.event_hub.hub_core import DEFAULT_STORE_ID
import uuid

router = APIRouter()

# 师傅手动品质打分 → loss-risk 既有等级体系（poor=D 触发 _LOW_GRADES 风险）。
_GRADE_MAP = {"good": "A", "normal": "B", "poor": "D"}


class QualityTapBody(BaseModel):
    batch_id: str
    grade: Literal["good", "normal", "poor"]
    store_id: Optional[str] = None
    sku: Optional[str] = None
    actor_id: Optional[str] = None
    note: str = ""


def _upsert_cost_grade(store: Any, batch_id: str, sku: Optional[str], grade: str) -> None:
    """Set vlm_grade on the matching cost item (or append a minimal one) so the
    manual quality tap feeds /v1/cost/loss-risk."""
    cost = dict(store.cost_stats or {"store_id": store.store_id, "items": []})
    items = [dict(i) for i in cost.get("items", [])]
    for it in items:
        if it.get("batch_id") == batch_id:
            it["vlm_grade"] = grade
            if sku and not it.get("sku"):
                it["sku"] = sku
            break
    else:
        items.append({"batch_id": batch_id, "sku": sku, "vlm_grade": grade})
    cost["items"] = items
    store.set_cost_stats(cost)


@router.post("/api/v1/receiving/quality-tap")
def receiving_quality_tap(
    body: QualityTapBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """师傅手动 3 按钮品质打分（LOSS-503）。契约见
    docs/kitchen_loss_budget_solution.md §2.2。"""
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    enforce_action(auth, "receiving_submit")
    store = runtime.hub.get_store(sid)
    mapped = _GRADE_MAP[body.grade]
    actor = body.actor_id or auth.sub or auth.role or "user"

    event = store.add_event(
        {
            "event_type": "receiving_quality_tap",
            "source": "manual",
            "level": "warn" if body.grade == "poor" else "info",
            "message": f"来料品质打分 {body.sku or body.batch_id}：{body.grade}（{mapped}）",
            "metadata": {
                "batch_id": body.batch_id,
                "sku": body.sku,
                "grade": body.grade,
                "mapped_grade": mapped,
                "actor_id": actor,
                "note": body.note,
                "ref_type": "receiving_batch",
                "ref_id": body.batch_id,
            },
        }
    )
    _upsert_cost_grade(store, body.batch_id, body.sku, mapped)

    return {
        "ok": True,
        "store_id": sid,
        "batch_id": body.batch_id,
        "grade": body.grade,
        "mapped_grade": mapped,
        "event_id": event.get("event_id"),
        "source": "real",
    }


@router.post("/api/v1/receiving/submit")
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


@router.post("/api/v1/receiving/checkin")
def receiving_checkin(
    body: ReceivingCheckinBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """Edge YOLO ingredient detection checkin at receiving dock.

    Creates a receiving_checkin event with ingredient details.
    Auto-creates a receiving batch if batch_ref is provided and not exists
    (with mock PO data for the receiving pipeline).
    """
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    enforce_action(auth, "receiving_submit")
    store = runtime.hub.get_store(sid)

    # Generate checkin ID
    day = datetime.now(timezone.utc).strftime("%Y%m%d")
    short = uuid.uuid4().hex[:6].upper()
    suffix = sid.replace("store_", "")[:8]
    checkin_id = f"CHK-{day}-{suffix}-{short}"

    # Calculate variance if weights provided
    var = variance_pct(body.weight_kg, body.po_weight_kg) if body.weight_kg is not None and body.po_weight_kg else None

    # Determine event level
    if var is not None and abs(var) > 10:
        level = "critical"
    elif var is not None and abs(var) > 5:
        level = "warn"
    else:
        level = "info"

    # Aggregate ingredient summary
    total_items = sum(i.count for i in body.ingredients)
    ingredient_classes = list({i.class_name for i in body.ingredients})

    # Auto-create batch if batch_ref provided
    batch_id = None
    if body.batch_ref:
        try:
            batch_id = body.batch_ref if receiving_store(runtime.db).batch_exists(body.batch_ref) else None
        except Exception:
            batch_id = None
        if not batch_id:
            # Create a simple batch entry via receiving_store
            batch_id = body.batch_ref
            try:
                batch = {
                    "batch_id": batch_id,
                    "po_id": body.batch_ref,
                    "sku": ", ".join(ingredient_classes) if ingredient_classes else "食材",
                    "weight_kg": body.weight_kg or 0,
                    "po_weight_kg": body.po_weight_kg,
                    "variance_pct": var,
                    "temp_c": body.temp_c,
                    "status": "submitted",
                }
                signatures = [
                    {"role": "receiver", "signed_by": f"edge-{body.device_id or 'yolo'}"},
                    {"role": "chef", "signed_by": "auto"},
                ]
                receiving_store(runtime.db).submit(sid, batch, signatures)
            except Exception:
                batch_id = body.batch_ref  # batch may have failed duplicate, still track

    # Create event
    event = store.add_event({
        "event_type": "receiving_checkin",
        "source": body.source,
        "level": level,
        "message": f"进货口检测: {total_items}件, {len(ingredient_classes)}类食材" +
                   (f", 偏差{var:+.1f}%" if var is not None else ""),
        "metadata": {
            "checkin_id": checkin_id,
            "batch_ref": body.batch_ref,
            "batch_id": batch_id,
            "ingredients": [i.model_dump() for i in body.ingredients],
            "total_items": total_items,
            "ingredient_classes": ingredient_classes,
            "weight_kg": body.weight_kg,
            "po_weight_kg": body.po_weight_kg,
            "variance_pct": var,
            "temp_c": body.temp_c,
            "image_ref": body.image_ref,
            "device_id": body.device_id,
        },
    })

    return {
        "ok": True,
        "checkin_id": checkin_id,
        "store_id": sid,
        "batch_id": batch_id,
        "variance_pct": var,
        "event_id": event.get("event_id"),
        "ingredient_summary": {
            "total_items": total_items,
            "classes": len(ingredient_classes),
        },
    }


@router.get("/api/v1/receiving/checkins")
def receiving_checkins(
    request: Request,
    store_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """List recent receiving checkins for a store."""
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    store = runtime.hub.get_store(sid)
    events = list(store.events)
    checkins = []
    for ev in events:
        if ev.get("event_type") == "receiving_checkin":
            checkins.append({
                "checkin_id": ev.get("metadata", {}).get("checkin_id"),
                "event_id": ev.get("event_id"),
                "timestamp": ev.get("timestamp"),
                "level": ev.get("level"),
                "message": ev.get("message"),
                "ingredients": ev.get("metadata", {}).get("ingredients", []),
                "total_items": ev.get("metadata", {}).get("total_items", 0),
                "variance_pct": ev.get("metadata", {}).get("variance_pct"),
                "weight_kg": ev.get("metadata", {}).get("weight_kg"),
                "batch_ref": ev.get("metadata", {}).get("batch_ref"),
            })
        if len(checkins) >= limit:
            break
    return {"store_id": sid, "checkins": checkins, "count": len(checkins)}


@router.get("/api/v1/receiving/batches")
def receiving_batches(
    request: Request,
    store_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    batches = receiving_store(runtime.db).list_batches(sid, limit=limit)
    return {"store_id": sid, "batches": batches, "count": len(batches)}


@router.get("/api/v1/audit/signatures")
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
