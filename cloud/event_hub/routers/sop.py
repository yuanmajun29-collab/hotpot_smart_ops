"""SOP routes."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_write, enforce_action
from cloud.event_hub.routers._deps import resolve_store_id as _resolve_store_id, SopAssignBody, SopAssignStatusBody, SopAskBody
from cloud.event_hub.sop_assign_store import sop_assign_store
from cloud.event_hub.hub_core import DEFAULT_STORE_ID

router = APIRouter()


@router.post("/v1/sop/assign")
def sop_assign(
    body: SopAssignBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    enforce_action(auth, "sop_assign")
    store = runtime.hub.get_store(sid)

    assigned_by = auth.sub or auth.role or "店长"
    row = sop_assign_store(runtime.db).create(
        sid,
        sop_id=body.sop_id,
        sop_name=body.sop_name,
        assignee=body.assignee,
        assigned_by=assigned_by,
        event_id=body.event_id,
        note=body.note or "",
        due_at=body.due_at,
    )

    event = store.add_event(
        {
            "event_type": "sop_assigned",
            "source": "system",
            "level": "info",
            "message": f"SOP 已指派：{row['sop_name']} → {body.assignee}",
            "metadata": {
                "assignment_id": row["assignment_id"],
                "sop_id": body.sop_id,
                "assignee": body.assignee,
                "assigned_by": assigned_by,
            },
        }
    )

    return {
        "ok": True,
        "assignment": row,
        "event_id": event.get("event_id"),
    }


@router.get("/v1/sop/assignments")
def sop_assignments(
    request: Request,
    store_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    items = sop_assign_store(runtime.db).list_assignments(sid, status=status, limit=limit)
    return {"store_id": sid, "assignments": items, "count": len(items)}


@router.put("/v1/sop/assignments/{assignment_id}/status")
def sop_assignment_status(
    assignment_id: str,
    body: SopAssignStatusBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    try:
        row = sop_assign_store(runtime.db).update_status(assignment_id, sid, body.status)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not row:
        raise HTTPException(status_code=404, detail="工单不存在")
    return {"ok": True, "assignment": row}


@router.post("/sop/ask")
def sop_ask(
    body: SopAskBody,
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    from cloud.llm_report.sop_rag import create_sop_agent

    agent = create_sop_agent(body.backend or "rule")
    if hasattr(agent, "answer") and body.backend == "openai":
        result = agent.answer(body.question, body.top_k)
    else:
        result = agent.answer_rule(body.question, body.top_k)
    return result
