"""GET/POST /v1/cost/loss-features — LOSS-504 HTTP API."""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


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


def _tok(c, user="zhangdian", role="店长", store="store_yuhuan"):
    r = c.post("/auth/token", json={"username": user, "password": "demo", "role": role, "store_id": store})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_loss_features_empty_before_rebuild(client):
    h = _tok(client)
    r = client.get("/v1/cost/loss-features", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["store_id"] == "store_yuhuan"
    assert body["source"] == "empty"
    assert body["items"] == []


def test_loss_features_rebuild_from_cost_snapshot(client):
    h = _tok(client)
    client.post(
        "/v1/receiving/quality-tap",
        json={"batch_id": "LF-001", "sku": "毛肚", "grade": "poor"},
        headers=h,
    )
    rb = client.post("/v1/cost/loss-features/rebuild", headers=h)
    assert rb.status_code == 200, rb.text
    rebuilt = rb.json()
    assert rebuilt["ok"] is True
    assert rebuilt["sku_count"] >= 1
    assert any(i.get("batch_id") == "LF-001" for i in rebuilt["items"])

    got = client.get("/v1/cost/loss-features", headers=h)
    assert got.status_code == 200
    assert got.json()["sku_count"] == rebuilt["sku_count"]


def test_loss_features_rebuild_cross_store_forbidden(client):
    h = _tok(client, store="store_yuhuan")
    r = client.post("/v1/cost/loss-features/rebuild?store_id=store_jiaojiang", headers=h)
    assert r.status_code == 403


def test_loss_features_read_cross_store_forbidden(client):
    h = _tok(client, store="store_yuhuan")
    r = client.get("/v1/cost/loss-features?store_id=store_jiaojiang", headers=h)
    assert r.status_code == 403
