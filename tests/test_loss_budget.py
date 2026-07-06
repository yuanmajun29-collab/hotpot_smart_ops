"""GET /v1/cost/loss-budget — 损耗预算 (LOSS-505).

Frozen contract: docs/kitchen_loss_budget_solution.md §2.1.
Builds on the loss-risk rule baseline; with no LLM forecast available it degrades to
source="rule", forecast_qty=null. actual/variance are next-day backfill (null on same-day).
Store-scoped (ADR-009).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


# ---- pure domain: variance computation -------------------------------------

_COST = {
    "store_id": "store_yuhuan",
    "items": [
        {"batch_id": "B1", "sku": "毛肚", "variance_pct": -6.0, "vlm_grade": "D",
         "weight_kg": 10.0, "po_weight_kg": 11.0, "unit_price": 80.0},
    ],
}


def test_compute_loss_budget_variance_when_actual_given():
    from hotpot_platform.cloud.event_hub.domain.loss_budget import compute_loss_budget
    base = compute_loss_budget(_COST, limit=10)
    budget = base["items"][0]["budget_loss_amount"]
    assert budget > 0
    assert base["items"][0]["forecast_qty"] is None  # no forecast supplied
    assert base["items"][0]["variance_pct"] is None  # same-day, no actual
    # supply an actual = 1.5x budget → variance +50%
    key = base["items"][0]["ref_id"]
    withact = compute_loss_budget(_COST, limit=10, actuals={key: round(budget * 1.5, 2)})
    assert withact["items"][0]["variance_pct"] == 50.0
    assert withact["actual_loss_amount_total"] == round(budget * 1.5, 2)


# ---- endpoint --------------------------------------------------------------

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


def test_loss_budget_source_rule_and_fields(client):
    h = _tok(client, "zhangdian", "店长")
    # seed a low-grade batch via quality-tap so there is a risk to budget
    client.post("/v1/receiving/quality-tap",
                json={"batch_id": "B9", "sku": "毛肚", "grade": "poor"}, headers=h)
    r = client.get("/v1/cost/loss-budget", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "rule"  # no LLM forecast available
    assert body["store_id"] == "store_yuhuan"
    assert body["date"]
    assert body["generated_at"]
    assert "budget_loss_amount_total" in body
    assert body["actual_loss_amount_total"] is None  # same-day
    item = next(i for i in body["items"] if i["ref_id"] == "B9")
    for f in ("sku", "forecast_qty", "forecast_unit", "budget_loss_amount",
              "actual_loss_amount", "variance_pct", "reason", "suggested_action",
              "ref_type", "ref_id"):
        assert f in item, f"missing field {f}"
    assert item["forecast_qty"] is None
    assert item["actual_loss_amount"] is None


def test_loss_budget_cross_store_403(client):
    h = _tok(client, "zhangdian", "店长", store="store_yuhuan")
    r = client.get("/v1/cost/loss-budget?store_id=store_jiaojiang", headers=h)
    assert r.status_code == 403, r.text
