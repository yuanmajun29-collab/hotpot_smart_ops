"""Alerts API: level filtering (F-A02) and escalation of unacked criticals (F-A05)."""

from __future__ import annotations

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    monkeypatch.setenv("HOTPOT_DB", str(db_path))
    monkeypatch.setenv("HOTPOT_AUTH_MODE", "demo")
    monkeypatch.delenv("HOTPOT_SEED_DIR", raising=False)
    monkeypatch.delenv("HOTPOT_DATABASE_URL", raising=False)

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
        yield c


STORE = "store_yuhuan"


def _post_event(client: TestClient, level: str, message: str, *, age_minutes: int = 0) -> str:
    ts = (datetime.now(timezone.utc) - timedelta(minutes=age_minutes)).replace(microsecond=0).isoformat()
    body = {
        "store_id": STORE,
        "event_type": "kitchen_gas_leak" if level == "critical" else "info_note",
        "source": "iot",
        "level": level,
        "message": message,
        "timestamp": ts,
    }
    r = client.post(f"/v1/events?store_id={STORE}", json=body)
    assert r.status_code == 200, r.text
    return r.json()["event_id"]


def test_events_level_filter_returns_only_critical(client):
    """F-A02: /v1/events?level=critical returns only critical events."""
    _post_event(client, "info", "info one")
    _post_event(client, "critical", "gas leak")

    r = client.get(f"/v1/events?store_id={STORE}&level=critical")
    assert r.status_code == 200
    events = r.json()
    assert len(events) >= 1
    assert all(e["level"] == "critical" for e in events)


def test_escalation_counts_unacked_old_critical(client):
    """F-A05: an unacked critical older than threshold shows up as escalated."""
    eid = _post_event(client, "critical", "gas leak 40min ago", age_minutes=40)

    r = client.get(f"/v1/alerts/escalations?store_id={STORE}")
    assert r.status_code == 200
    body = r.json()
    assert body["store_id"] == STORE
    assert body["threshold_minutes"] == 30
    assert body["count"] >= 1
    assert any(e["event_id"] == eid for e in body["events"])


def test_recent_critical_not_escalated(client):
    """F-A05 boundary: a fresh critical (within threshold) is not escalated."""
    _post_event(client, "critical", "gas leak just now", age_minutes=0)

    r = client.get(f"/v1/alerts/escalations?store_id={STORE}")
    assert r.status_code == 200
    assert r.json()["count"] == 0


def test_ack_clears_escalation(client):
    """F-A03 + F-A05: acking an old critical removes it from escalations."""
    eid = _post_event(client, "critical", "gas leak to ack", age_minutes=45)
    assert client.get(f"/v1/alerts/escalations?store_id={STORE}").json()["count"] >= 1

    ack = client.post(
        "/v1/alerts/ack",
        json={"event_id": eid, "store_id": STORE, "ack_by": "zhangdian"},
    )
    assert ack.status_code == 200

    r = client.get(f"/v1/alerts/escalations?store_id={STORE}")
    assert r.status_code == 200
    assert all(e["event_id"] != eid for e in r.json()["events"])
