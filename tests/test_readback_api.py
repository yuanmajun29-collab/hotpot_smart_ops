"""GET read-back endpoints: tables (F-T01), sop (F-S03), cost (F-C01), empty summary (F-H02)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

STORE = "store_yuhuan"


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    monkeypatch.setenv("HOTPOT_DB", str(db_path))
    monkeypatch.setenv("HOTPOT_AUTH_MODE", "demo")
    monkeypatch.delenv("HOTPOT_SEED_DIR", raising=False)
    monkeypatch.delenv("HOTPOT_DATABASE_URL", raising=False)

    from cloud.event_hub import app as hub_app_module
    from cloud.event_hub import runtime
    from cloud.event_hub.db import create_hub_database

    db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=db.on_persist),
        db,
        hub_app_module.AlertGateway(db_path),
    )
    with TestClient(hub_app_module.app) as c:
        yield c


def test_get_tables_returns_states(client):
    """F-T01: posted table states are read back via GET /v1/tables."""
    client.post(
        f"/v1/tables?store_id={STORE}",
        json={"tables": [
            {"table_id": "T01", "state": "need_clean"},
            {"table_id": "T02", "state": "checkout"},
        ]},
    )
    r = client.get(f"/v1/tables?store_id={STORE}")
    assert r.status_code == 200
    states = {t["table_id"]: t["state"] for t in r.json()}
    assert states["T01"] == "need_clean"
    assert states["T02"] == "checkout"


def test_get_sop_returns_compliance(client):
    """F-S03: posted SOP stats are read back with compliance rate."""
    client.post(f"/v1/sop?store_id={STORE}", json={"compliance_rate": 92.0, "results": []})
    r = client.get(f"/v1/sop?store_id={STORE}")
    assert r.status_code == 200
    assert r.json().get("compliance_rate") == 92.0


def test_get_cost_returns_items(client):
    """F-C01: posted cost stats are read back with items."""
    client.post(
        f"/v1/cost?store_id={STORE}",
        json={"items": [{"sku": "毛肚", "variance_pct": -5.0}], "variance_rate_pct": -5.0},
    )
    r = client.get(f"/v1/cost?store_id={STORE}")
    assert r.status_code == 200
    body = r.json()
    assert body["items"]
    assert body["items"][0]["sku"] == "毛肚"


def test_empty_store_summary_is_zero(client):
    """F-H02 boundary: a fresh store summary returns zeroed KPIs, no error."""
    r = client.get(f"/v1/summary?store_id={STORE}")
    assert r.status_code == 200
    assert r.json().get("total_events", 0) == 0
