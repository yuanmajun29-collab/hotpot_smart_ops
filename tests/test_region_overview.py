"""Tests for regional overview API (F-HQ06 / F-HQ07)."""

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
    os.environ["HOTPOT_DAILY_REPORT_SCHEDULER"] = "0"
    os.environ["HOTPOT_SEED_DIR"] = str(Path(__file__).resolve().parents[1] / "demo" / "data" / "stores")
    os.environ.pop("HOTPOT_DATABASE_URL", None)

    from hotpot_platform.cloud.event_hub import app as hub_app_module
    from hotpot_platform.cloud.event_hub.db import create_hub_database
    from hotpot_platform.cloud.event_hub.hub_core import seed_from_directory

    from hotpot_platform.cloud.event_hub import runtime
    _db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=_db.on_persist),
        _db,
        hub_app_module.AlertGateway(db_path),
    )
    seed_from_directory(hub_app_module.hub, Path(os.environ["HOTPOT_SEED_DIR"]))

    with TestClient(hub_app_module.app) as c:
        yield c


def test_zone_east_china_rollup(client):
    r = client.get("/v1/region/overview?region_id=zone_east_china")
    assert r.status_code == 200
    data = r.json()
    assert data["level"] == "zone"
    assert data["region_id"] == "zone_east_china"
    assert data["region_name"] == "华东大区"
    assert len(data.get("child_regions", [])) == 3
    assert data["rollup"]["store_count"] >= 1
    taizhou = next(c for c in data["child_regions"] if c["region_id"] == "region_taizhou")
    assert taizhou["connected_stores"] >= 1
    assert taizhou["rollup"]["store_count"] >= 1


def test_default_overview_is_zone(client):
    data = client.get("/v1/region/overview").json()
    assert data["level"] == "zone"
    assert data["region_id"] == "zone_east_china"


def test_region_overview_structure(client):
    r = client.get("/v1/region/overview?region_id=region_taizhou")
    assert r.status_code == 200
    data = r.json()
    assert data["region_id"] == "region_taizhou"
    assert "rollup" in data
    assert "health_matrix" in data
    assert "anomaly_stores" in data
    assert "regions" in data
    assert len(data["regions"]) >= 3
    assert data["rollup"]["store_count"] >= 1


def test_region_overview_health_fields(client):
    data = client.get("/v1/region/overview").json()
    for store in data.get("stores", []):
        assert "health" in store
        assert store["health"]["status"] in ("ok", "warn", "critical")
        assert "score" in store["health"]


def test_benchmark_alias(client):
    r = client.get("/benchmark?region_id=region_taizhou")
    assert r.status_code == 200
    assert r.json()["region_id"] == "region_taizhou"


def test_compute_store_health_critical():
    from hotpot_platform.cloud.event_hub.hub_core import compute_store_health

    h = compute_store_health({"critical_alerts": 2, "sop_compliance_rate": 90, "need_clean": 0})
    assert h["status"] == "critical"
    assert h["reasons"]
