"""Analytics layer tests."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import date as date_type, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ["HOTPOT_DAILY_REPORT_SCHEDULER"] = "0"
    os.environ.pop("HOTPOT_DATABASE_URL", None)
    os.environ.pop("HOTPOT_SEED_DIR", None)

    from hotpot_platform.cloud.event_hub import app as hub_app_module
    from hotpot_platform.cloud.event_hub import runtime
    from hotpot_platform.cloud.event_hub.db import create_hub_database

    db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=db.on_persist),
        db,
        hub_app_module.AlertGateway(db_path),
    )
    with TestClient(hub_app_module.app) as c:
        registry = json.loads((Path(__file__).resolve().parents[1] / "demo" / "data" / "stores.json").read_text())
        runtime.hub.reload_registry_from(registry)
        yield c


def test_analytics_router_import():
    from hotpot_platform.analytics import StoreCompareEngine, SuggestionEngine, TrendEngine
    from hotpot_platform.cloud.event_hub.routers.analytics import router

    assert StoreCompareEngine is not None
    assert TrendEngine is not None
    assert SuggestionEngine is not None
    assert router is not None


def test_compare_handles_empty_stores(client):
    r = client.get("/api/analytics/compare?zone_id=zone_east_china&days=7")
    assert r.status_code == 200
    data = r.json()
    assert data["scope"]["store_count"] == 2
    assert len(data["rows"]) == 2
    assert set(data["metrics"]) == {"waste_rate", "table_turnover", "sop_compliance", "food_safety_alerts"}
    assert "comparison_grids" in data


def test_trend_and_dashboard_endpoints(client):
    r = client.get("/api/analytics/trends/store_yuhuan?metric=waste&days=5")
    assert r.status_code == 200
    data = r.json()
    assert data["metric"] == "waste_rate"
    assert len(data["daily"]) == 5
    assert "weekly" in data
    assert "monthly" in data

    dash = client.get("/api/analytics/dashboard/zone_east_china?days=7")
    assert dash.status_code == 200
    assert dash.json()["store_count"] == 2


def test_suggestions_lifecycle_persisted(client):
    from hotpot_platform.cloud.event_hub import runtime

    store = runtime.hub.get_store("store_yuhuan")
    store.set_sop_stats({"compliance_rate": 70})
    today = date_type.today()
    for offset, count in [(3, 10), (2, 10), (1, 10), (0, 20)]:
        day = (today - timedelta(days=offset)).isoformat()
        runtime.db.upsert_waste_timeseries("store_yuhuan", day, count, 1, [])

    r = client.get("/api/analytics/suggestions/store_yuhuan?days=4")
    assert r.status_code == 200
    suggestions = r.json()["suggestions"]
    assert suggestions
    suggestion_id = suggestions[0]["suggestion_id"]

    status = client.post(
        f"/api/analytics/suggestions/store_yuhuan/{suggestion_id}/status",
        json={"status": "acknowledged"},
    )
    assert status.status_code == 200
    assert status.json()["suggestion"]["status"] == "acknowledged"

    snap = runtime.db.get_snapshot("store_yuhuan", "analytics_suggestions")
    assert snap["suggestions"][0]["status"] == "acknowledged"
