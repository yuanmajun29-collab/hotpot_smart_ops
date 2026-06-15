"""Tests for POS bridge (DEV-304)."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def hub_client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ.pop("HOTPOT_DATABASE_URL", None)
    os.environ.pop("HOTPOT_SEED_DIR", None)

    from cloud.event_hub import app as hub_app_module
    from cloud.event_hub.db import create_hub_database

    hub_app_module.db = create_hub_database(db_path)
    hub_app_module.hub = hub_app_module.MultiTenantHub(on_persist=hub_app_module.db.on_persist)
    hub_app_module.alert_gateway = hub_app_module.AlertGateway(db_path)

    with TestClient(hub_app_module.app) as c:
        yield c


def test_get_pos_empty(hub_client):
    r = hub_client.get("/pos?store_id=store_yuhuan")
    assert r.status_code == 200
    assert r.json()["store_id"] == "store_yuhuan"


def test_pos_sync_sim():
    from cloud.integrations.pos_bridge import sync_pos

    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)

    # Start minimal in-process isn't needed — use TestClient via urllib mock
    # Instead test simulate_live_stats shape
    from cloud.integrations.pos_bridge import simulate_live_stats

    base = {"turnover_rate": 2.5, "daily_revenue": 50000, "dish_timeout_count": 2}
    out = simulate_live_stats(base, "store_yuhuan")
    assert out["store_id"] == "store_yuhuan"
    assert "turnover_rate" in out
    assert out["source"] == "simulated"


def test_post_pos_and_get(hub_client):
    stats = {
        "store_id": "store_yuhuan",
        "turnover_rate": 2.8,
        "daily_revenue": 52000,
        "dish_timeout_count": 3,
    }
    hub_client.post("/pos?store_id=store_yuhuan", json=stats)
    r = hub_client.get("/pos?store_id=store_yuhuan")
    assert r.status_code == 200
    assert r.json()["turnover_rate"] == 2.8
