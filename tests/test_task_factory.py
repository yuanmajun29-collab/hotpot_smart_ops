"""Task factory tests (DEV-522 / ADR-010)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def db():
    from hotpot_platform.cloud.event_hub.db import create_hub_database
    tmp = tempfile.mkdtemp()
    return create_hub_database(Path(tmp) / "f.db")


# ---- classification --------------------------------------------------------

def test_classify_sop_violation():
    from hotpot_platform.cloud.event_hub.task_factory import classify
    spec = classify({"event_id": "e1", "event_type": "sop_violation", "level": "warn",
                     "metadata": {"sop_id": "s1", "sop_name": "后厨清洁", "assignee": "chushi"}})
    assert spec["task_type"] == "sop_violation" and spec["priority"] == "P1"
    assert spec["assignee_id"] == "chushi" and spec["ref_type"] == "sop"


def test_classify_safety_critical_is_p0():
    from hotpot_platform.cloud.event_hub.task_factory import classify
    spec = classify({"event_id": "e2", "event_type": "alert_smoke", "level": "critical",
                     "message": "后厨烟雾"})
    assert spec["task_type"] == "safety_alert" and spec["priority"] == "P0"


def test_classify_cleaning():
    from hotpot_platform.cloud.event_hub.task_factory import classify
    spec = classify({"event_id": "e3", "event_type": "table_need_clean", "table_id": "T05",
                     "message": "T05 待清台"})
    assert spec["task_type"] == "cleaning" and spec["priority"] == "P2"
    assert spec["ref_id"] == "T05" and spec["assignee_group"] == "fronthall"


def test_classify_no_rule_returns_none():
    from hotpot_platform.cloud.event_hub.task_factory import classify
    assert classify({"event_id": "e4", "event_type": "heartbeat", "level": "info"}) is None


# ---- idempotency -----------------------------------------------------------

def test_spawn_is_idempotent(db):
    from hotpot_platform.cloud.event_hub.task_factory import spawn_task_for_event
    ev = {"event_id": "dup1", "event_type": "alert_gas", "level": "critical", "message": "燃气"}
    a = spawn_task_for_event(db, "store_yuhuan", ev)
    b = spawn_task_for_event(db, "store_yuhuan", ev)
    assert a["task_id"] == b["task_id"]
    from hotpot_platform.cloud.event_hub.task_store import task_store
    assert len(task_store(db).list_tasks("store_yuhuan")) == 1


def test_helpers(db):
    from hotpot_platform.cloud.event_hub import task_factory
    t1 = task_factory.spawn_sop_violation(db, "store_yuhuan", sop_id="s9", sop_name="测温", assignee="chushi")
    assert t1["task_type"] == "sop_violation" and t1["assignee_id"] == "chushi"
    t2 = task_factory.spawn_cleaning(db, "store_yuhuan", table_id="B3")
    assert t2["task_type"] == "cleaning" and t2["ref_id"] == "B3"


# ---- wiring: sop_assign 收口 + /v1/tasks/ingest -----------------------------

@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    monkeypatch.setenv("HOTPOT_DB", str(db_path))
    monkeypatch.setenv("HOTPOT_AUTH_MODE", "strict")
    monkeypatch.delenv("HOTPOT_SEED_DIR", raising=False)
    monkeypatch.delenv("HOTPOT_DATABASE_URL", raising=False)
    from hotpot_platform.cloud.event_hub import app as m
    from hotpot_platform.cloud.event_hub.db import create_hub_database
    from hotpot_platform.cloud.event_hub import runtime
    dbo = create_hub_database(db_path)
    runtime.init(m.MultiTenantHub(on_persist=dbo.on_persist), dbo, m.AlertGateway(db_path))
    with TestClient(m.app) as c:
        yield c


def _tok(c, user, role, store="store_yuhuan"):
    r = c.post("/auth/token", json={"username": user, "password": "demo", "role": role, "store_id": store})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_sop_assign_spawns_task(client):
    h = _tok(client, "zhangdian", "店长")
    r = client.post("/v1/sop/assign", json={"sop_id": "sop_k", "sop_name": "后厨清洁",
                    "assignee": "chushi", "store_id": "store_yuhuan"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json().get("task_id")  # 收口：指派同时生成工单
    tasks = client.get("/v1/tasks", headers=h).json()["tasks"]
    assert any(t["task_type"] == "sop_violation" for t in tasks)


def test_ingest_endpoint_spawns(client):
    h = _tok(client, "zhangdian", "店长")
    r = client.post("/v1/tasks/ingest", json={"store_id": "store_yuhuan",
                    "event": {"event_id": "ing1", "event_type": "table_need_clean",
                              "table_id": "C2", "message": "C2 待清台"}}, headers=h)
    assert r.status_code == 200 and r.json()["spawned"] is True
    assert r.json()["task"]["task_type"] == "cleaning"
