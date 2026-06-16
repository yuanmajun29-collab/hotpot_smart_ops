"""Tests for SOP assign API (DEV-421 / BL-05)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ.pop("HOTPOT_SEED_DIR", None)
    os.environ.pop("HOTPOT_DATABASE_URL", None)

    from cloud.event_hub import app as hub_app_module
    from cloud.event_hub.db import create_hub_database

    hub_app_module.db = create_hub_database(db_path)
    hub_app_module.hub = hub_app_module.MultiTenantHub(on_persist=hub_app_module.db.on_persist)
    hub_app_module.alert_gateway = hub_app_module.AlertGateway(db_path)

    with TestClient(hub_app_module.app) as c:
        yield c


def test_sop_assign_create_and_list(client):
    r = client.post(
        "/v1/sop/assign",
        json={
            "store_id": "store_yuhuan",
            "sop_id": "SOP-K01",
            "sop_name": "冷链温度检查",
            "assignee": "厨师长",
            "note": "冷库超温",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["assignment"]["assignment_id"].startswith("SOP-")
    assert data["assignment"]["status"] == "open"

    listed = client.get("/v1/sop/assignments?store_id=store_yuhuan&status=open").json()
    assert listed["count"] >= 1
    assert any(a["sop_id"] == "SOP-K01" for a in listed["assignments"])


def test_sop_assign_status_update(client):
    created = client.post(
        "/v1/sop/assign",
        json={
            "store_id": "store_yuhuan",
            "sop_id": "SOP-K02",
            "assignee": "领班",
        },
    ).json()
    aid = created["assignment"]["assignment_id"]

    r = client.put(
        f"/v1/sop/assignments/{aid}/status",
        json={"store_id": "store_yuhuan", "status": "done"},
    )
    assert r.status_code == 200
    assert r.json()["assignment"]["status"] == "done"

    open_only = client.get("/v1/sop/assignments?store_id=store_yuhuan&status=open").json()
    assert not any(a["assignment_id"] == aid for a in open_only["assignments"])


def test_audit_acks_includes_sop_assignments(client):
    client.post(
        "/v1/sop/assign",
        json={"store_id": "store_yuhuan", "sop_id": "SOP-X", "assignee": "厨师长"},
    )
    data = client.get("/v1/audit/acks?store_id=store_yuhuan").json()
    assert data["sop_assignment_count"] >= 1
