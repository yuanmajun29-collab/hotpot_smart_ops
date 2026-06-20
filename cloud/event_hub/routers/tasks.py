"""Task-supervision routes (DEV-521 / ADR-010)."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from cloud.event_hub import runtime
from cloud.event_hub.auth import AuthContext, get_auth_context, enforce_store_write, enforce_action
from cloud.event_hub.routers._deps import resolve_store_id as _resolve_store_id
from cloud.event_hub.task_store import task_store, TaskError
from cloud.event_hub.hub_core import DEFAULT_STORE_ID

router = APIRouter()


class TaskCreateBody(BaseModel):
    task_type: str
    title: str
    store_id: Optional[str] = None
    priority: str = "P1"
    ref_type: Optional[str] = None
    ref_id: Optional[str] = None
    assignee_id: Optional[str] = None
    assignee_group: Optional[str] = None
    detail: str = ""
    due_at: Optional[str] = None
    source: str = "manual"


class TaskActionBody(BaseModel):
    store_id: Optional[str] = None
    assignee_id: Optional[str] = None
    sla_policy: Optional[str] = None
    reason: str = ""
    detail: Optional[str] = None


# action -> required RBAC permission
_ACTION_PERM = {
    "assign": "task_reassign", "accept": "task_ack", "start": "task_ack",
    "submit": "task_ack", "verify": "task_verify", "reject": "task_verify",
    "reassign": "task_reassign", "cancel": "task_cancel", "reopen": "task_reopen",
}


def _actor(auth: AuthContext) -> str:
    return auth.sub or auth.role or "user"


@router.post("/v1/tasks")
def create_task(body: TaskCreateBody, auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    enforce_action(auth, "task_create")
    row = task_store(runtime.db).create(
        sid, task_type=body.task_type, title=body.title, created_by=_actor(auth),
        priority=body.priority, source=body.source, ref_type=body.ref_type, ref_id=body.ref_id,
        assignee_id=body.assignee_id, assignee_group=body.assignee_group,
        detail=body.detail, due_at=body.due_at,
    )
    # 派单推送（DEV-526，best-effort）：新任务即时推给责任人/班组
    pushed = False
    try:
        if runtime.alert_gateway is not None:
            pushed = runtime.alert_gateway.push_task_card(row, sid, "dispatch").get("pushed", False)
    except Exception:  # noqa: BLE001 - 推送失败不应阻断建单
        pushed = False
    return {"ok": True, "task": row, "dispatch_pushed": pushed}


class TaskIngestBody(BaseModel):
    store_id: Optional[str] = None
    event: Dict[str, Any]


@router.post("/v1/tasks/ingest")
def ingest_event(body: TaskIngestBody, auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    """收口入口：把告警/清台/IoT/SOP 事件经 task_factory 幂等转工单（DEV-522）。"""
    from cloud.event_hub import task_factory

    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    enforce_action(auth, "task_create")
    task = task_factory.spawn_task_for_event(runtime.db, sid, body.event)
    return {"ok": True, "spawned": bool(task), "task": task}


@router.get("/v1/tasks")
def list_tasks(
    request: Request,
    store_id: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    task_type: Optional[str] = Query(None),
    assignee: Optional[str] = Query(None),
    overdue: Optional[bool] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    auth: AuthContext = Depends(get_auth_context),
) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    items = task_store(runtime.db).list_tasks(
        sid, status=status, task_type=task_type, assignee_id=assignee, overdue=overdue, limit=limit)
    return {"store_id": sid, "tasks": items, "count": len(items)}


@router.get("/v1/tasks/{task_id}")
def get_task(task_id: str, request: Request, store_id: Optional[str] = Query(None),
             auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    sid = _resolve_store_id(store_id, None, request.headers.get("X-Store-Id"), auth)
    store = task_store(runtime.db)
    row = store.get(task_id, sid)
    if not row:
        raise HTTPException(status_code=404, detail="任务不存在")
    return {"task": row, "timeline": store.timeline(task_id)}


@router.post("/v1/tasks/{task_id}/{action}")
def task_action(task_id: str, action: str, body: TaskActionBody,
                auth: AuthContext = Depends(get_auth_context)) -> Dict[str, Any]:
    if action not in _ACTION_PERM:
        raise HTTPException(status_code=404, detail=f"未知动作: {action}")
    sid = body.store_id or auth.store_id or DEFAULT_STORE_ID
    enforce_store_write(auth, sid)
    enforce_action(auth, _ACTION_PERM[action])
    store = task_store(runtime.db)

    # no-self-verify: verifier must differ from the last submitter
    if action == "verify":
        submit_actor = next((e["actor_id"] for e in reversed(store.timeline(task_id))
                             if e["event_type"] == "submit"), None)
        if submit_actor and submit_actor == _actor(auth):
            raise HTTPException(status_code=403, detail="复核人不能是提交人（禁止自审自关）")
    try:
        row = store.transition(
            task_id, sid, action, actor_id=_actor(auth),
            assignee_id=body.assignee_id, sla_policy=body.sla_policy,
            reason=body.reason, detail=body.detail)
    except TaskError as exc:
        msg = str(exc)
        code = 404 if "not found" in msg else 409 if "illegal" in msg else 400
        raise HTTPException(status_code=code, detail=msg) from exc
    return {"ok": True, "task": row}
