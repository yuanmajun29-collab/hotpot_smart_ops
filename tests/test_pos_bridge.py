"""Tests for POS bridge (DEV-304)."""

from __future__ import annotations

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

    from hotpot_platform.cloud.event_hub import app as hub_app_module
    from hotpot_platform.cloud.event_hub.db import create_hub_database

    from hotpot_platform.cloud.event_hub import runtime
    _db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=_db.on_persist),
        _db,
        hub_app_module.AlertGateway(db_path),
    )

    with TestClient(hub_app_module.app) as c:
        yield c


def test_get_pos_empty(hub_client):
    r = hub_client.get("/pos?store_id=store_yuhuan")
    assert r.status_code == 200
    assert r.json()["store_id"] == "store_yuhuan"


def test_pos_sync_sim():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)

    # Start minimal in-process isn't needed — use TestClient via urllib mock
    # Instead test simulate_live_stats shape
    from hotpot_platform.cloud.integrations.pos_bridge import simulate_live_stats

    base = {"turnover_rate": 2.5, "daily_revenue": 50000, "dish_timeout_count": 2}
    out = simulate_live_stats(base, "store_yuhuan")
    assert out["store_id"] == "store_yuhuan"
    assert "turnover_rate" in out
    assert out["source"] == "simulated"


def test_load_sku_sales_csv_preserves_historical_dates(tmp_path):
    path = tmp_path / "sales.csv"
    path.write_text(
        "business_date,sku,sku_name,qty_sold,unit_price\n"
        "2026-04-28,SKU-001,鲜毛肚,12,68\n"
        "2026-04-29,SKU-001,鲜毛肚,15,68\n",
        encoding="utf-8",
    )
    from hotpot_platform.cloud.integrations.pos_bridge import load_sku_sales_csv
    records = load_sku_sales_csv(path, "store_jiaojiang")
    assert [item["business_date"] for item in records] == ["2026-04-28", "2026-04-29"]
    assert all(item["source"] == "pos_csv" for item in records)


def test_load_sku_sales_csv_rejects_missing_date(tmp_path):
    path = tmp_path / "missing-date.csv"
    path.write_text("sku,qty_sold\nSKU-001,12\n", encoding="utf-8")
    from hotpot_platform.cloud.integrations.pos_bridge import load_sku_sales_csv
    with pytest.raises(ValueError, match="business_date"):
        load_sku_sales_csv(path, "store_jiaojiang")


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
