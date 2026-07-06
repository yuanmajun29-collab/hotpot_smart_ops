"""IoT device registry + health profile (LOSS-501)."""
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


def _tok(c, user="zhangdian", role="店长", store="store_yuhuan"):
    r = c.post("/auth/token", json={"username": user, "password": "demo", "role": role, "store_id": store})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_sensor_profile_has_protocol_topic_and_calibration():
    from shared.iot_sensors import sensor_profile

    p = sensor_profile("receiving_scale", "store_yuhuan")
    assert p["protocol"] == "modbus_rtu"
    assert p["topic"] == "hotpot/store_yuhuan/sensors/receiving_scale"
    assert p["health_max_age_sec"] == 300
    assert p["required_p1a"] is True
    assert p["calibration"]["tolerance_pct"] == 0.2


def test_iot_devices_health_summary_from_latest_readings(client):
    h = _tok(client)
    now = datetime.now(timezone.utc).replace(microsecond=0)
    stale = now - timedelta(minutes=10)
    body = {
        "store_id": "store_yuhuan",
        "readings": [
            {
                "sensor_id": "cold_storage_1",
                "sensor_type": "temperature",
                "value": -18.0,
                "unit": "C",
                "recorded_at": now.isoformat(),
            },
            {
                "sensor_id": "cold_storage_2",
                "sensor_type": "temperature",
                "value": 7.5,
                "unit": "C",
                "recorded_at": now.isoformat(),
            },
            {
                "sensor_id": "freezer_door_1",
                "sensor_type": "door",
                "value": 0,
                "unit": "state",
                "recorded_at": stale.isoformat(),
            },
        ],
    }
    r = client.post("/v1/iot/readings/batch", json=body, headers=h)
    assert r.status_code == 200, r.text

    r = client.get("/v1/iot/devices", headers=h)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["summary"] == {
        "total": 5,
        "online": 1,
        "offline": 3,
        "out_of_range": 1,
        "online_rate_pct": 20.0,
    }
    by_id = {d["sensor_id"]: d for d in data["devices"]}
    assert by_id["cold_storage_1"]["health"]["status"] == "online"
    assert by_id["cold_storage_2"]["health"]["status"] == "out_of_range"
    assert by_id["freezer_door_1"]["health"]["reason"] == "stale_reading"
    assert by_id["receiving_scale"]["health"]["reason"] == "missing_reading"


def test_iot_devices_cross_store_403(client):
    h = _tok(client, store="store_yuhuan")
    r = client.get("/v1/iot/devices?store_id=store_jiaojiang", headers=h)
    assert r.status_code == 403, r.text
