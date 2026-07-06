"""POST /v1/receiving/quality-tap — 师傅手动品质打分 (LOSS-503).

Frozen contract: docs/kitchen_loss_budget_solution.md §2.2.
grade good→A / normal→B / poor→D; poor feeds loss-risk via cost snapshot.
Store-scoped (ADR-009): cross-store write 403.
"""
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
    from hotpot_platform.cloud.event_hub import app as m
    from hotpot_platform.cloud.event_hub.db import create_hub_database
    from hotpot_platform.cloud.event_hub import runtime
    dbo = create_hub_database(db_path)
    runtime.init(m.MultiTenantHub(on_persist=dbo.on_persist), dbo, m.AlertGateway(db_path))
    with TestClient(m.app) as c:
        yield c


def _tok(c, user, role, store="store_yuhuan"):
    r = c.post("/auth/token", json={"username": user, "password": "demo", "role": role, "store_id": store})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_quality_tap_poor_maps_to_d(client):
    h = _tok(client, "zhangdian", "店长")
    r = client.post("/v1/receiving/quality-tap",
                    json={"batch_id": "RCV-T-001", "sku": "毛肚", "grade": "poor"}, headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ok"] is True
    assert body["mapped_grade"] == "D"
    assert body["grade"] == "poor"
    assert body["source"] == "real"
    assert body["event_id"]


def test_quality_tap_grade_mapping_good_normal(client):
    h = _tok(client, "zhangdian", "店长")
    good = client.post("/v1/receiving/quality-tap",
                       json={"batch_id": "RCV-T-002", "grade": "good"}, headers=h)
    normal = client.post("/v1/receiving/quality-tap",
                         json={"batch_id": "RCV-T-003", "grade": "normal"}, headers=h)
    assert good.json()["mapped_grade"] == "A"
    assert normal.json()["mapped_grade"] == "B"


def test_quality_tap_feeds_loss_risk(client):
    h = _tok(client, "zhangdian", "店长")
    client.post("/v1/receiving/quality-tap",
                json={"batch_id": "RCV-T-004", "sku": "鸭肠", "grade": "poor"}, headers=h)
    risk = client.get("/v1/cost/loss-risk", headers=h)
    assert risk.status_code == 200, risk.text
    risks = risk.json()["risks"]
    hit = next((x for x in risks if x.get("batch_id") == "RCV-T-004"), None)
    assert hit is not None, f"quality-tap batch not in loss-risk: {risks}"
    assert "品质等级 D" in hit["reason"]


def test_quality_tap_before_receiving_submit_merges_cost_item(client):
    h = _tok(client, "zhangdian", "店长")
    batch_id = "RCV-T-004B"
    client.post("/v1/receiving/quality-tap",
                json={"batch_id": batch_id, "sku": "毛肚", "grade": "poor"}, headers=h)
    submitted = client.post(
        "/v1/receiving/submit",
        json={
            "batch_id": batch_id,
            "po_id": "PO-T-004B",
            "sku": "毛肚",
            "weight_kg": 10.0,
            "po_weight_kg": 10.0,
            "signatures": [
                {"role": "receiver", "signed_by": "赵收货"},
                {"role": "chef", "signed_by": "王厨师长"},
            ],
        },
        headers=h,
    )
    assert submitted.status_code == 200, submitted.text

    risk = client.get("/v1/cost/loss-risk", headers=h)
    risks = [x for x in risk.json()["risks"] if x.get("batch_id") == batch_id]
    assert len(risks) == 1, risks
    assert risks[0]["vlm_grade"] == "D"
    assert "品质等级 D" in risks[0]["reason"]
    assert risks[0]["estimated_loss_amount"] > 0


def test_quality_tap_cross_store_403(client):
    h = _tok(client, "zhangdian", "店长", store="store_yuhuan")
    r = client.post("/v1/receiving/quality-tap",
                    json={"store_id": "store_jiaojiang", "batch_id": "RCV-T-005", "grade": "poor"},
                    headers=h)
    assert r.status_code == 403, r.text


def test_quality_tap_invalid_grade_422(client):
    h = _tok(client, "zhangdian", "店长")
    r = client.post("/v1/receiving/quality-tap",
                    json={"batch_id": "RCV-T-006", "grade": "excellent"}, headers=h)
    assert r.status_code == 422, r.text
