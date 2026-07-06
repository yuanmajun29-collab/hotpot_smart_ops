"""POST /v1/cost/loss-risk/{batch_id}/task — 风险一键转复称任务 (LOSS-506).

Converts a loss-risk batch into a 复称留证 (re-weigh) task via the existing task
engine. Idempotent per (store, batch) via source_id; traces back to the batch
(ref_type=receiving_batch, ADR-012). Store-scoped (ADR-009).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    monkeypatch.setenv("HOTPOT_DB", str(db_path))
    monkeypatch.setenv("HOTPOT_AUTH_MODE", "strict")
    monkeypatch.delenv("HOTPOT_SEED_DIR", raising=False)
    monkeypatch.delenv("HOTPOT_DATABASE_URL", raising=False)
    from platform.cloud.event_hub import app as m
    from platform.cloud.event_hub.db import create_hub_database
    from platform.cloud.event_hub import runtime
    dbo = create_hub_database(db_path)
    runtime.init(m.MultiTenantHub(on_persist=dbo.on_persist), dbo, m.AlertGateway(db_path))
    with TestClient(m.app) as c:
        yield c


def _tok(c, user, role, store="store_yuhuan"):
    r = c.post("/auth/token", json={"username": user, "password": "demo", "role": role, "store_id": store})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed_risk(c, h, batch_id="B1", sku="毛肚"):
    # quality-tap poor → cost item vlm_grade D → loss-risk for that batch
    r = c.post("/v1/receiving/quality-tap",
               json={"batch_id": batch_id, "sku": sku, "grade": "poor"}, headers=h)
    assert r.status_code == 200, r.text


def test_risk_to_task_creates_recheck_task(client):
    h = _tok(client, "zhangdian", "店长")
    _seed_risk(client, h, "B1", "毛肚")
    r = client.post("/v1/cost/loss-risk/B1/task", json={}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    task = body["task"]
    assert task["task_type"] == "recheck_weight"
    assert task["ref_type"] == "receiving_batch"
    assert task["ref_id"] == "B1"
    assert task["source"] == "loss_risk"
    assert "毛肚" in task["title"]
    assert task["priority"] == "P1"  # grade D → score 40 → P1
    assert body["risk"]["task_id"] == task["task_id"]
    assert body["risk"]["task_type"] == "recheck_weight"
    # traceable in the task list
    lst = client.get("/v1/tasks", headers=h)
    assert any(t["task_id"] == task["task_id"] for t in lst.json()["tasks"])


def test_risk_to_task_is_idempotent(client):
    h = _tok(client, "zhangdian", "店长")
    _seed_risk(client, h, "B2", "鸭肠")
    a = client.post("/v1/cost/loss-risk/B2/task", json={}, headers=h)
    b = client.post("/v1/cost/loss-risk/B2/task", json={}, headers=h)
    assert a.json()["task"]["task_id"] == b.json()["task"]["task_id"]


def test_loss_risk_surfaces_existing_recheck_task(client):
    h = _tok(client, "zhangdian", "店长")
    _seed_risk(client, h, "B3", "黄喉")
    created = client.post("/v1/cost/loss-risk/B3/task", json={}, headers=h).json()["task"]
    r = client.get("/v1/cost/loss-risk", headers=h)
    assert r.status_code == 200, r.text
    hit = next(item for item in r.json()["risks"] if item["ref_id"] == "B3")
    assert hit["task_id"] == created["task_id"]
    assert hit["task_status"] == "pending"
    assert hit["task_assignee_status"] == "needs_triage"
    assert hit["task_type"] == "recheck_weight"


def test_risk_to_task_group_assignment_is_assigned(client):
    h = _tok(client, "zhangdian", "店长")
    _seed_risk(client, h, "B4", "鲜鸭血")
    r = client.post("/v1/cost/loss-risk/B4/task",
                    json={"assignee_group": "后厨班组"}, headers=h)
    assert r.status_code == 200, r.text
    task = r.json()["task"]
    assert task["assignee_group"] == "后厨班组"
    assert task["assignee_status"] == "assigned"


def test_risk_to_task_404_when_no_risk(client):
    h = _tok(client, "zhangdian", "店长")
    r = client.post("/v1/cost/loss-risk/NOPE/task", json={}, headers=h)
    assert r.status_code == 404, r.text


def test_risk_to_task_cross_store_403(client):
    h = _tok(client, "zhangdian", "店长", store="store_yuhuan")
    r = client.post("/v1/cost/loss-risk/B1/task",
                    json={"store_id": "store_jiaojiang"}, headers=h)
    assert r.status_code == 403, r.text
