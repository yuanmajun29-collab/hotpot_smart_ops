"""Restock advice push (15:00 备货建议) + scheduler dispatch wiring (LOSS-507 runtime).

Per Codex review: dedicated AlertGateway.push_loss_restock_advice (event_id
loss-restock-{store}-{date}), reuse _record_push/_append_file_log/_post_webhook;
NOT push_daily_report, NOT task cards. Deterministic idempotency per (store,date).
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest


_BUDGET = {
    "source": "rule",
    "items": [
        {"sku": "毛肚", "forecast_qty": None, "forecast_unit": None,
         "budget_loss_amount": 160.0, "actual_loss_amount": None, "variance_pct": None,
         "reason": "短重 -6.0%；品质等级 D", "suggested_action": "复称并留证，必要时退货",
         "ref_type": "receiving_batch", "ref_id": "B1"},
    ],
    "budget_loss_amount_total": 160.0,
    "actual_loss_amount_total": None,
}


@pytest.fixture()
def gw():
    from hotpot_platform.cloud.alert_gateway.gateway import AlertGateway
    tmp = tempfile.mkdtemp()
    return AlertGateway(Path(tmp) / "g.db")


def test_format_loss_restock_card(gw):
    c = gw.format_loss_restock_card("store_yuhuan", "2026-06-21", _BUDGET)
    assert "备货" in c["title"]
    assert "毛肚" in c["body"]
    assert "复称" in c["body"]            # suggested_action surfaced
    assert "rule" in c["body"]            # source labelled


def test_push_loss_restock_idempotent_per_day(gw):
    a = gw.push_loss_restock_advice("store_yuhuan", "2026-06-21", _BUDGET)
    b = gw.push_loss_restock_advice("store_yuhuan", "2026-06-21", _BUDGET)
    assert a["pushed"] is True and b["pushed"] is False  # same store+date deduped
    assert a["event_id"] == "loss-restock-store_yuhuan-2026-06-21"
    pushes = gw.list_pushes("store_yuhuan")
    assert any("备货" in p.get("title", "") for p in pushes)
    # next day re-pushes
    c = gw.push_loss_restock_advice("store_yuhuan", "2026-06-22", _BUDGET)
    assert c["pushed"] is True


def test_push_restock_advice_for_store_builds_budget_and_pushes():
    from hotpot_platform.cloud.event_hub.daily_scheduler import push_restock_advice_for_store
    from hotpot_platform.cloud.event_hub.db import create_hub_database
    from hotpot_platform.cloud.event_hub.hub_core import MultiTenantHub
    from hotpot_platform.cloud.alert_gateway.gateway import AlertGateway

    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "h.db"
    dbo = create_hub_database(db_path)
    hub = MultiTenantHub(on_persist=dbo.on_persist)
    gw = AlertGateway(db_path)
    # seed a low-grade short-weight batch into the store's cost snapshot
    hub.get_store("store_yuhuan").set_cost_stats({
        "store_id": "store_yuhuan",
        "items": [{"batch_id": "B1", "sku": "毛肚", "variance_pct": -6.0, "vlm_grade": "D",
                   "weight_kg": 10.0, "po_weight_kg": 11.0, "unit_price": 80.0}],
    })

    res = push_restock_advice_for_store(hub, dbo, gw, "store_yuhuan", report_date="2026-06-21")
    assert res["pushed"] is True
    assert res["budget_loss_amount_total"] > 0
