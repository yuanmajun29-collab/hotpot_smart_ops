"""Task-supervision engine tests (DEV-521 / ADR-010)."""
from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---- unit: state machine on TaskStore directly -----------------------------

@pytest.fixture()
def store():
    from cloud.event_hub.db import create_hub_database
    from cloud.event_hub.task_store import task_store

    tmp = tempfile.mkdtemp()
    db = create_hub_database(Path(tmp) / "t.db")
    return task_store(db)


def test_happy_path_pending_to_closed(store):
    t = store.create("store_yuhuan", task_type="adhoc", title="擦桌", created_by="zhangdian",
                     assignee_id="banzu")
    assert t["status"] == "pending" and t["assignee_status"] == "assigned"
    tid = t["task_id"]
    assert store.transition(tid, "store_yuhuan", "start", actor_id="banzu")["status"] == "in_progress"
    assert store.transition(tid, "store_yuhuan", "submit", actor_id="banzu")["status"] == "submitted"
    assert store.transition(tid, "store_yuhuan", "verify", actor_id="zhangdian")["status"] == "closed"
    # timeline records every transition
    types = [e["event_type"] for e in store.timeline(tid)]
    assert types == ["create", "start", "submit", "verify"]


def test_illegal_transition_rejected(store):
    from cloud.event_hub.task_store import TaskError
    t = store.create("store_yuhuan", task_type="adhoc", title="x", created_by="z")
    # cannot verify a pending task
    with pytest.raises(TaskError):
        store.transition(t["task_id"], "store_yuhuan", "verify", actor_id="z")


def test_reopen_returns_to_pending(store):
    t = store.create("store_yuhuan", task_type="adhoc", title="x", created_by="z", assignee_id="a")
    tid = t["task_id"]
    store.transition(tid, "store_yuhuan", "submit", actor_id="a")
    store.transition(tid, "store_yuhuan", "verify", actor_id="z")
    reopened = store.transition(tid, "store_yuhuan", "reopen", actor_id="z", reason="漏项")
    assert reopened["status"] == "pending"


def test_reassign_requires_sla_policy_and_logs(store):
    from cloud.event_hub.task_store import TaskError
    t = store.create("store_yuhuan", task_type="adhoc", title="x", created_by="z", assignee_id="a")
    tid = t["task_id"]
    r = store.transition(tid, "store_yuhuan", "reassign", actor_id="z",
                         assignee_id="b", sla_policy="keep_original_due_at")
    assert r["assignee_id"] == "b" and r["status"] == "pending"
    with pytest.raises(TaskError):
        store.transition(tid, "store_yuhuan", "reassign", actor_id="z",
                         assignee_id="c", sla_policy="bogus")
    ev = [e for e in store.timeline(tid) if e["event_type"] == "reassign"][0]
    assert ev["to_assignee"] == "b" and ev["sla_policy"] == "keep_original_due_at"


def test_overdue_is_derived(store):
    past = (datetime.now(timezone.utc) - timedelta(hours=1)).replace(microsecond=0).isoformat()
    t = store.create("store_yuhuan", task_type="adhoc", title="x", created_by="z", due_at=past)
    assert store.get(t["task_id"], "store_yuhuan")["is_overdue"] is True
    # closed tasks are never overdue
    store.transition(t["task_id"], "store_yuhuan", "submit", actor_id="z")
    store.transition(t["task_id"], "store_yuhuan", "verify", actor_id="boss")
    assert store.get(t["task_id"], "store_yuhuan")["is_overdue"] is False


def test_blank_assignee_needs_triage(store):
    t = store.create("store_yuhuan", task_type="sop_violation", title="x", created_by="z")
    assert t["assignee_status"] == "needs_triage"


# ---- API: auth + no-self-verify + illegal transition ------------------------

@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    monkeypatch.setenv("HOTPOT_DB", str(db_path))
    monkeypatch.setenv("HOTPOT_AUTH_MODE", "strict")
    monkeypatch.delenv("HOTPOT_SEED_DIR", raising=False)
    monkeypatch.delenv("HOTPOT_DATABASE_URL", raising=False)
    from cloud.event_hub import app as m
    from cloud.event_hub.db import create_hub_database
    from cloud.event_hub import runtime
    db = create_hub_database(db_path)
    runtime.init(m.MultiTenantHub(on_persist=db.on_persist), db, m.AlertGateway(db_path))
    with TestClient(m.app) as c:
        yield c


def _tok(c, user, role, store="store_yuhuan"):
    r = c.post("/auth/token", json={"username": user, "password": "demo", "role": role, "store_id": store})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_api_create_and_list(client):
    h = _tok(client, "zhangdian", "店长")
    r = client.post("/v1/tasks", json={"task_type": "adhoc", "title": "擦桌", "assignee_id": "banzu"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["task"]["status"] == "pending"
    lst = client.get("/v1/tasks", headers=h)
    assert lst.status_code == 200 and lst.json()["count"] == 1


def test_api_no_self_verify(client):
    h = _tok(client, "zhangdian", "店长")
    tid = client.post("/v1/tasks", json={"task_type": "adhoc", "title": "x", "assignee_id": "zhangdian"},
                      headers=h).json()["task"]["task_id"]
    client.post(f"/v1/tasks/{tid}/submit", json={}, headers=h)  # 店长 submits
    # same actor tries to verify -> 403
    r = client.post(f"/v1/tasks/{tid}/verify", json={}, headers=h)
    assert r.status_code == 403, r.text


def test_api_illegal_transition_409(client):
    h = _tok(client, "zhangdian", "店长")
    tid = client.post("/v1/tasks", json={"task_type": "adhoc", "title": "x"}, headers=h).json()["task"]["task_id"]
    r = client.post(f"/v1/tasks/{tid}/verify", json={}, headers=h)  # pending -> verify illegal
    assert r.status_code == 409, r.text


def test_api_forbidden_action_for_finance_audit(client):
    # 财务审计 is read-only: no task_create permission -> 403
    h = _tok(client, "caiwu", "财务审计", store="*")
    r = client.post("/v1/tasks", json={"task_type": "adhoc", "title": "x"}, headers=h)
    assert r.status_code == 403, r.text
