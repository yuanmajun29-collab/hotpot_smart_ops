"""Task督办 WeChat push tests (DEV-526 / ADR-010)."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def gw():
    from cloud.alert_gateway.gateway import AlertGateway
    tmp = tempfile.mkdtemp()
    return AlertGateway(Path(tmp) / "g.db")


_TASK = {"task_id": "T-yuhuan-20260616-AB12", "title": "B3 待清台", "priority": "P0",
         "assignee_id": "banzu", "store_id": "store_yuhuan"}


def test_card_dispatch(gw):
    c = gw.format_task_card(_TASK, "store_yuhuan", "dispatch")
    assert "任务·P0" in c["title"] and "B3 待清台" in c["title"]
    assert "责任人：banzu" in c["body"] and "tasks.html" in c["body"]


def test_card_accept_overdue(gw):
    c = gw.format_task_card(_TASK, "store_yuhuan", "accept_overdue", sla="5分钟")
    assert "督办" in c["title"] and "认领时限：5分钟" in c["body"]


def test_card_done_overdue(gw):
    c = gw.format_task_card(_TASK, "store_yuhuan", "done_overdue", overdue_minutes=42)
    assert "超时" in c["title"] and "已逾期：42 分钟" in c["body"]


def test_push_is_idempotent_per_kind(gw):
    a = gw.push_task_card(_TASK, "store_yuhuan", "dispatch")
    b = gw.push_task_card(_TASK, "store_yuhuan", "dispatch")
    assert a["pushed"] is True and b["pushed"] is False  # second is deduped
    # a different kind still pushes
    c = gw.push_task_card(_TASK, "store_yuhuan", "done_overdue", overdue_minutes=10)
    assert c["pushed"] is True


def test_escalation_level_at_least_warn(gw):
    low = {**_TASK, "priority": "P2"}
    r = gw.push_task_card(low, "store_yuhuan", "accept_overdue")
    assert r["level"] == "warn"  # info upgraded to warn for escalations


def test_dedup_token_allows_periodic_re_push(gw):
    # same (task, kind) but a new round token re-pushes with refreshed minutes
    a = gw.push_task_card(_TASK, "store_yuhuan", "done_overdue", overdue_minutes=42, dedup_token="r1")
    b = gw.push_task_card(_TASK, "store_yuhuan", "done_overdue", overdue_minutes=42, dedup_token="r1")
    c = gw.push_task_card(_TASK, "store_yuhuan", "done_overdue", overdue_minutes=90, dedup_token="r2")
    assert a["pushed"] is True and b["pushed"] is False  # same round deduped
    assert c["pushed"] is True  # next round re-pushes
    assert "已逾期：90 分钟" in c["card"]["body"]


def test_card_uses_group_when_no_assignee(gw):
    grp = {k: v for k, v in _TASK.items() if k != "assignee_id"}
    grp["assignee_group"] = "前厅班组"
    c = gw.format_task_card(grp, "store_yuhuan", "dispatch")
    assert "责任人：前厅班组" in c["body"]  # group shown, not 待派办


# ---- wiring: create_task triggers dispatch push -----------------------------

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
    dbo = create_hub_database(db_path)
    runtime.init(m.MultiTenantHub(on_persist=dbo.on_persist), dbo, m.AlertGateway(db_path))
    with TestClient(m.app) as c:
        yield c


def _tok(c, user, role, store="store_yuhuan"):
    r = c.post("/auth/token", json={"username": user, "password": "demo", "role": role, "store_id": store})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_create_task_triggers_dispatch_push(client):
    from cloud.event_hub import runtime
    h = _tok(client, "zhangdian", "店长")
    r = client.post("/v1/tasks", json={"task_type": "cleaning", "title": "B3 待清台",
                    "priority": "P1", "assignee_id": "banzu"}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json()["dispatch_pushed"] is True
    pushes = runtime.alert_gateway.list_pushes("store_yuhuan")
    assert any("待清台" in p.get("title", "") for p in pushes)


def test_create_task_survives_push_failure(client, monkeypatch):
    from cloud.event_hub import runtime

    def _boom(*a, **k):
        raise RuntimeError("webhook down")

    monkeypatch.setattr(runtime.alert_gateway, "push_task_card", _boom)
    h = _tok(client, "zhangdian", "店长")
    r = client.post("/v1/tasks", json={"task_type": "cleaning", "title": "B5 待清台",
                    "priority": "P1", "assignee_id": "banzu"}, headers=h)
    assert r.status_code == 200, r.text  # build not blocked by push failure
    assert r.json()["dispatch_pushed"] is False
