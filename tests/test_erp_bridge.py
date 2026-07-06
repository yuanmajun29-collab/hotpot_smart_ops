"""Tests for ERP bridge (DEV-305)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def hub_client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ.pop("HOTPOT_DATABASE_URL", None)

    from platform.cloud.event_hub import app as hub_app_module
    from platform.cloud.event_hub.db import create_hub_database

    from platform.cloud.event_hub import runtime
    _db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=_db.on_persist),
        _db,
        hub_app_module.AlertGateway(db_path),
    )

    with TestClient(hub_app_module.app) as c:
        yield c


def test_get_erp_empty(hub_client):
    r = hub_client.get("/erp?store_id=store_yuhuan")
    assert r.status_code == 200
    assert r.json()["store_id"] == "store_yuhuan"


def test_post_erp(hub_client):
    payload = {
        "store_id": "store_yuhuan",
        "order_count": 2,
        "orders": [{"po_id": "PO-1", "sku": "毛肚"}],
        "receiving_records": [],
    }
    r = hub_client.post("/erp?store_id=store_yuhuan", json=payload)
    assert r.status_code == 200
    get_r = hub_client.get("/erp?store_id=store_yuhuan")
    assert get_r.json()["order_count"] == 2


def test_fetch_po_orders():
    from platform.cloud.integrations.erp_bridge import fetch_po_orders, merge_with_actuals

    project = Path(__file__).resolve().parents[1]
    erp_file = project / "demo" / "data" / "erp_po_orders.json"
    orders = fetch_po_orders("store_yuhuan", mode="file", erp_file=erp_file)
    assert len(orders) >= 1
    records = merge_with_actuals(orders, project / "demo" / "data" / "incoming_materials.json")
    assert records[0]["sku"]
    assert "po_qty_kg" in records[0]
