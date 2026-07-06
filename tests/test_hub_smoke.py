"""Smoke tests for Event Hub (DEV-107)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ.pop("HOTPOT_SEED_DIR", None)
    os.environ.pop("HOTPOT_DATABASE_URL", None)

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


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert data["multi_tenant"] is True


def test_post_event_and_summary(client):
    event = {
        "event_type": "table_empty",
        "source": "vision",
        "level": "info",
        "store_id": "store_yuhuan",
        "message": "test table empty",
        "table_id": "T01",
    }
    r = client.post("/events?store_id=store_yuhuan", json=event)
    assert r.status_code == 200
    summary = client.get("/summary?store_id=store_yuhuan").json()
    assert summary["store_id"] == "store_yuhuan"
    assert summary["total_events"] >= 1


def test_tenant_isolation(client):
    client.post(
        "/events?store_id=store_yuhuan",
        json={
            "event_type": "test_yuhuan",
            "source": "system",
            "level": "info",
            "store_id": "store_yuhuan",
            "message": "yuhuan only",
        },
    )
    client.post(
        "/events?store_id=store_jiaojiang",
        json={
            "event_type": "test_jiaojiang",
            "source": "system",
            "level": "info",
            "store_id": "store_jiaojiang",
            "message": "jiaojiang only",
        },
    )
    y = client.get("/summary?store_id=store_yuhuan").json()
    j = client.get("/summary?store_id=store_jiaojiang").json()
    assert y["store_id"] != j["store_id"]


def test_benchmark_empty(client):
    r = client.get("/benchmark")
    assert r.status_code == 200
    assert "stores" in r.json()


def test_auth_token(client):
    r = client.post(
        "/auth/token",
        json={"username": "zhangdian", "password": "demo", "store_id": "store_yuhuan"},
    )
    assert r.status_code == 200
    assert "access_token" in r.json()


def test_metrics(client):
    client.post(
        "/events?store_id=store_yuhuan",
        json={
            "event_type": "kitchen_smoke",
            "source": "vision",
            "level": "critical",
            "store_id": "store_yuhuan",
            "message": "smoke test",
        },
    )
    r = client.get("/metrics")
    assert r.status_code == 200
    data = r.json()
    assert data["store_count"] >= 0
    assert "uptime_sec" in data


def test_sop_ask(client):
    r = client.post("/sop/ask", json={"question": "来料收货要注意什么", "backend": "rule"})
    assert r.status_code == 200
    data = r.json()
    assert "answer" in data
    assert data.get("sources") is not None
