"""POST /v1/vlm/waste-estimate — VLM 废料识别 mock-first (VLM-603 / TC-COST-09)."""
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
    monkeypatch.delenv("HOTPOT_VLM_WASTE", raising=False)
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


def test_waste_estimate_mock_with_image_ref(client):
    h = _tok(client)
    r = client.post(
        "/v1/vlm/waste-estimate",
        json={"image_ref": "rtsp://cam/waste-zone-a/frame-001.jpg", "zone": "备餐废弃区"},
        headers=h,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["source"] == "mock"
    assert body["store_id"] == "store_yuhuan"
    assert body["event_id"]
    assert len(body["items"]) >= 1
    assert body["items"][0]["confidence"] > 0
    assert body["items"][0]["unit"] == "份"


def test_waste_estimate_requires_image_or_stream(client):
    h = _tok(client)
    r = client.post("/v1/vlm/waste-estimate", json={"zone": "废弃区"}, headers=h)
    assert r.status_code == 422


def test_waste_estimate_cross_store_forbidden(client):
    h = _tok(client, store="store_yuhuan")
    r = client.post(
        "/v1/vlm/waste-estimate",
        json={"store_id": "store_jiaojiang", "stream_id": "cam-jj-waste-1"},
        headers=h,
    )
    assert r.status_code == 403


def test_waste_estimate_writes_loss_features(client):
    h = _tok(client)
    client.post(
        "/v1/vlm/waste-estimate",
        json={"image_ref": "file://sample/waste.jpg"},
        headers=h,
    )
    feats = client.get("/v1/cost/loss-features", headers=h)
    assert feats.status_code == 200, feats.text
    data = feats.json()
    assert data["waste_evidence"]
    assert data["source"] in ("mock", "vlm-shadow")
