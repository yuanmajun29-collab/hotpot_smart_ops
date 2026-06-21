"""LOSS-402: /v1/cost/loss-risk rule-baseline stub (P1B 损耗预测切入)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from cloud.event_hub.domain.loss_risk import compute_loss_risk

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


# ---- pure domain ----

def test_compute_loss_risk_ranks_and_explains():
    cost = {
        "items": [
            {"batch_id": "B1", "sku": "毛肚", "variance_pct": -8.0, "vlm_grade": "D", "temp_c": -18.0},
            {"batch_id": "B2", "sku": "鸭肠", "variance_pct": -1.0, "vlm_grade": "A", "temp_c": -18.0},
            {"batch_id": "B3", "sku": "黄喉", "variance_pct": 0.0, "vlm_grade": "C", "temp_c": -8.0},
        ]
    }
    risks = compute_loss_risk(cost, limit=5)
    # B2 is clean -> excluded; B1 (short + grade D) outranks B3 (grade C + temp)
    ids = [r["batch_id"] for r in risks]
    assert ids == ["B1", "B3"]
    assert "短重" in risks[0]["reason"] and "品质等级 D" in risks[0]["reason"]
    assert risks[0]["suggested_action"]
    assert risks[0]["risk_score"] >= risks[1]["risk_score"]
    # contract fields (architecture_api_spec §3)
    assert risks[0]["ref_type"] == "receiving_batch"
    assert risks[0]["ref_id"] == "B1"
    assert "estimated_loss_amount" in risks[0]


def test_compute_loss_risk_empty():
    assert compute_loss_risk({"items": []}) == []
    assert compute_loss_risk({}) == []


# ---- API ----

def test_loss_risk_endpoint_reads_cost_snapshot(client):
    client.post(
        f"/v1/cost?store_id={STORE}",
        json={"items": [
            {"batch_id": "B1", "sku": "毛肚", "variance_pct": -9.0, "vlm_grade": "C"},
            {"batch_id": "B2", "sku": "鸭肠", "variance_pct": -0.5, "vlm_grade": "A"},
        ]},
    )
    r = client.get(f"/v1/cost/loss-risk?store_id={STORE}&limit=10")
    assert r.status_code == 200
    body = r.json()
    assert body["store_id"] == STORE
    assert body["date"]
    assert body["baseline"] == "rule"
    assert body["count"] == 1
    top = body["risks"][0]
    assert top["sku"] == "毛肚"
    assert top["ref_type"] == "receiving_batch" and top["ref_id"] == "B1"
    assert "estimated_loss_amount" in top
    assert "estimated_loss_amount_total" in body


def test_loss_risk_preserves_explicit_date(client):
    r = client.get(f"/v1/cost/loss-risk?store_id={STORE}&date=2026-06-21")
    assert r.status_code == 200
    assert r.json()["date"] == "2026-06-21"


def test_loss_risk_store_scoped(client):
    """Cross-store isolation applies to the new endpoint too."""
    tok = client.post(
        "/auth/token", json={"username": "zhangdian", "password": "demo", "store_id": STORE}
    ).json()["access_token"]
    r = client.get(
        "/v1/cost/loss-risk?store_id=store_jiaojiang",
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 403
