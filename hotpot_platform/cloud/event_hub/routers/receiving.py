"""Receiving routes."""
from __future__ import annotations

import os
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

# ── 缺斤少两阈值配置 ──
WEIGHT_ALERT_THRESHOLD_PCT = float(os.environ.get("HOTPOT_WEIGHT_ALERT_PCT", "5.0"))    # 告警阈值 (%)
WEIGHT_REJECT_THRESHOLD_PCT = float(os.environ.get("HOTPOT_WEIGHT_REJECT_PCT", "10.0"))  # 拒收阈值 (%)

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

    # ── 缺斤少两自动拦截（K-004）──
    alert_reason = None
    reject_reason = None
    status = "ok"

    if var is not None:
        abs_var = abs(var)
        if abs_var >= WEIGHT_REJECT_THRESHOLD_PCT:
            status = "rejected"
            reject_reason = f"重量偏差{var:+.1f}%，超出容忍上限{WEIGHT_REJECT_THRESHOLD_PCT}%"
        elif abs_var >= WEIGHT_ALERT_THRESHOLD_PCT:
            status = "alert"
            alert_reason = f"重量偏差{var:+.1f}%"

    # Determine event level
    if status == "rejected":
        level = "critical"
    elif status == "alert":
        level = "warn"
    elif var is not None and abs(var) > 3:
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
    event_msg = f"进货口检测: {total_items}件, {len(ingredient_classes)}类食材" + \
                (f", 偏差{var:+.1f}%" if var is not None else "")
    if reject_reason:
        event_msg += f" — 已拒收({reject_reason})"
    elif alert_reason:
        event_msg += f" — 需审核({alert_reason})"

    event = store.add_event({
        "event_type": "receiving_checkin",
        "source": body.source,
        "level": level,
        "message": event_msg,
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

    # ── 告警级别自动推送给 AlertGateway ──
    if status == "alert":
        try:
            runtime.alert_gateway.create_alert(
                store_id=sid,
                event_id=event.get("event_id", ""),
                alert_type="receiving_weight_variance",
                level="warn",
                message=alert_reason or "重量偏差超告警阈值",
                metadata={
                    "checkin_id": checkin_id,
                    "variance_pct": var,
                    "batch_ref": body.batch_ref,
                },
            )
        except Exception:
            pass  # 告警推送失败不影响主流程

    return {
        "ok": status != "rejected",
        "status": status,
        "checkin_id": checkin_id,
        "store_id": sid,
        "batch_id": batch_id,
        "variance_pct": var,
        "event_id": event.get("event_id"),
        "alert_reason": alert_reason,
        "reject_reason": reject_reason,
        "auto_review": status == "alert",
        "blocked": status == "rejected",
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


@router.get("/api/v1/receiving/supplier-stats")
def receiving_supplier_stats(
    request: Request,
    store_id: Optional[str] = Query(None, description="门店 ID"),
    supplier_id: str = Query(..., description="供应商 ID"),
    limit: int = Query(50, ge=1, le=200, description="查询最近 N 批"),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    """查询供应商历史合格率统计。

    返回该供应商历史上所有批次的统计：
    - total_batches: 总批次数
    - pass_rate: 合格率（偏差 < alert_threshold 的批次占比）
    - avg_variance_pct: 平均重量偏差
    - recent_batches: 最近批次明细
    """
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    batches = receiving_store(runtime.db).list_batches(sid, limit=500)
    supplier_batches = [b for b in batches if b.get("supplier_id") == supplier_id]

    if not supplier_batches:
        return {
            "store_id": sid,
            "supplier_id": supplier_id,
            "total_batches": 0,
            "pass_rate": None,
            "avg_variance_pct": None,
            "message": "该供应商暂无历史记录",
        }

    total = len(supplier_batches)
    threshold = WEIGHT_ALERT_THRESHOLD_PCT
    passed = sum(
        1 for b in supplier_batches
        if b.get("variance_pct") is not None and abs(b["variance_pct"]) < threshold
    )
    variances = [
        b["variance_pct"]
        for b in supplier_batches
        if b.get("variance_pct") is not None
    ]
    avg_var = round(sum(variances) / len(variances), 2) if variances else None

    return {
        "store_id": sid,
        "supplier_id": supplier_id,
        "total_batches": total,
        "pass_rate": round(passed / total * 100, 1),
        "alert_threshold_pct": threshold,
        "avg_variance_pct": avg_var,
        "passed_count": passed,
        "failed_count": total - passed,
        "recent_batches": supplier_batches[:limit],
    }
