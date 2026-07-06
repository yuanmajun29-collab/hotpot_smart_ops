"""LLM forecast wiring for loss-budget — source rule→rule+llm (LOSS-505+).

Frozen contract: docs/kitchen_loss_budget_solution.md §2.1 — when the LLM forecast
is available it fills forecast_qty and source becomes "rule+llm"; on failure /
no key it degrades to source="rule", forecast_qty=null. LLM call is injected
(chat_fn) so tests never hit a real API.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


_COST = {
    "store_id": "store_yuhuan",
    "items": [{"batch_id": "B1", "sku": "毛肚", "variance_pct": -6.0, "vlm_grade": "D",
               "weight_kg": 10.0, "po_weight_kg": 11.0, "unit_price": 80.0}],
}


# ---- domain ----------------------------------------------------------------

def test_compute_loss_budget_applies_forecasts():
    from platform.cloud.event_hub.domain.loss_budget import compute_loss_budget
    base = compute_loss_budget(_COST, limit=10)
    assert base["forecasted"] is False
    assert base["items"][0]["forecast_qty"] is None

    fc = {"B1": {"forecast_qty": 15.0, "forecast_unit": "份", "reason": "近7天均耗13+雨天"}}
    out = compute_loss_budget(_COST, limit=10, forecasts=fc)
    assert out["forecasted"] is True
    it = out["items"][0]
    assert it["forecast_qty"] == 15.0
    assert it["forecast_unit"] == "份"
    assert "雨天" in it["reason"]  # forecast reason merged


def test_compute_loss_budget_rejects_unsafe_forecasts():
    from platform.cloud.event_hub.domain.loss_budget import compute_loss_budget
    bad = compute_loss_budget(
        _COST,
        limit=10,
        forecasts={"B1": {"forecast_qty": -1, "forecast_unit": "份", "reason": "bad"}},
    )
    assert bad["forecasted"] is False
    assert bad["items"][0]["forecast_qty"] is None

    good = compute_loss_budget(
        _COST,
        limit=10,
        forecasts={"B1": {"forecast_qty": "12.5", "reason": "模型建议"}},
    )
    assert good["forecasted"] is True
    assert good["items"][0]["forecast_qty"] == 12.5
    assert good["items"][0]["forecast_unit"] == "份"


# ---- agents ----------------------------------------------------------------

def test_rule_forecast_agent_returns_empty():
    from platform.cloud.llm_report.forecast_agent import RuleForecastAgent
    assert RuleForecastAgent().forecast([{"ref_id": "B1", "sku": "毛肚"}], store_id="store_yuhuan") == {}


def test_llm_forecast_agent_parses_response():
    from platform.cloud.llm_report.forecast_agent import LLMForecastAgent
    def fake_chat(_prompt):
        return (
            '这里是结果：\n```json\n'
            '{"B1": {"forecast_qty": 15, "forecast_unit": "份", "reason": "近7天均耗13"},'
            ' "BAD": {"forecast_qty": -2, "forecast_unit": "份", "reason": "bad"}}\n```'
        )
    fc = LLMForecastAgent(chat_fn=fake_chat).forecast(
        [{"ref_id": "B1", "sku": "毛肚", "budget_loss_amount": 160}],
        store_id="store_yuhuan", date="2026-06-21")
    assert fc["B1"]["forecast_qty"] == 15
    assert fc["B1"]["forecast_unit"] == "份"
    assert "BAD" not in fc


def test_llm_forecast_agent_graceful_on_error_or_bad_json():
    from platform.cloud.llm_report.forecast_agent import LLMForecastAgent
    def boom(_p):
        raise RuntimeError("api down")
    assert LLMForecastAgent(chat_fn=boom).forecast([{"ref_id": "B1"}], store_id="s") == {}
    assert LLMForecastAgent(chat_fn=lambda _p: "not json").forecast([{"ref_id": "B1"}], store_id="s") == {}


# ---- endpoint --------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    monkeypatch.setenv("HOTPOT_DB", str(db_path))
    monkeypatch.setenv("HOTPOT_AUTH_MODE", "strict")
    monkeypatch.delenv("HOTPOT_SEED_DIR", raising=False)
    monkeypatch.delenv("HOTPOT_DATABASE_URL", raising=False)
    from platform.cloud.event_hub import app as m
    from platform.cloud.event_hub.db import create_hub_database
    from platform.cloud.event_hub import runtime
    dbo = create_hub_database(db_path)
    runtime.init(m.MultiTenantHub(on_persist=dbo.on_persist), dbo, m.AlertGateway(db_path))
    with TestClient(m.app) as c:
        yield c


def _tok(c, user, role, store="store_yuhuan"):
    r = c.post("/auth/token", json={"username": user, "password": "demo", "role": role, "store_id": store})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _seed(c, h):
    c.post("/v1/receiving/quality-tap", json={"batch_id": "B1", "sku": "毛肚", "grade": "poor"}, headers=h)


def test_loss_budget_endpoint_source_rule_without_llm(client):
    h = _tok(client, "zhangdian", "店长")
    _seed(client, h)
    r = client.get("/v1/cost/loss-budget", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "rule"
    assert all(i["forecast_qty"] is None for i in body["items"])


def test_loss_budget_endpoint_source_rule_plus_llm_with_agent(client, monkeypatch):
    h = _tok(client, "zhangdian", "店长")
    _seed(client, h)

    class FakeAgent:
        def forecast(self, items, *, store_id, date=None, **ctx):
            return {it["ref_id"]: {"forecast_qty": 15.0, "forecast_unit": "份", "reason": "雨天+10%"}
                    for it in items if it.get("ref_id")}

    monkeypatch.setattr("cloud.event_hub.routers.cost.make_forecast_agent", lambda: FakeAgent())
    r = client.get("/v1/cost/loss-budget", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "rule+llm"
    item = next(i for i in body["items"] if i["ref_id"] == "B1")
    assert item["forecast_qty"] == 15.0
    assert item["forecast_unit"] == "份"


def test_loss_budget_endpoint_degrades_when_agent_raises(client, monkeypatch):
    h = _tok(client, "zhangdian", "店长")
    _seed(client, h)

    class BoomAgent:
        def forecast(self, items, *, store_id, date=None, **ctx):
            raise RuntimeError("llm down")

    monkeypatch.setattr("cloud.event_hub.routers.cost.make_forecast_agent", lambda: BoomAgent())
    r = client.get("/v1/cost/loss-budget", headers=h)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "rule"
    assert all(i["forecast_qty"] is None for i in body["items"])
