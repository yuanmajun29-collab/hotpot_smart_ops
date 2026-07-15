"""Device registry + module config persistence."""

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
    monkeypatch.setenv("HOTPOT_AUTH_MODE", "demo")
    monkeypatch.delenv("HOTPOT_SEED_DIR", raising=False)
    monkeypatch.delenv("HOTPOT_DATABASE_URL", raising=False)

    from hotpot_platform.cloud.event_hub import app as hub_app_module
    from hotpot_platform.cloud.event_hub.db import create_hub_database
    from hotpot_platform.cloud.event_hub import runtime

    db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=db.on_persist),
        db,
        hub_app_module.AlertGateway(db_path),
    )

    with TestClient(hub_app_module.app) as c:
        yield c, db_path


def test_device_config_persists_and_loads_after_runtime_reinit(client):
    c, db_path = client
    register = {
        "device_id": "jetson-yuhuan-01",
        "store_id": "store_yuhuan",
        "ip": "10.0.0.8",
        "device_type": "jetson",
        "active_modules": [],
    }
    r = c.post("/v1/devices/register", json=register)
    assert r.status_code == 200, r.text

    config = {
        "modules": {
            "kitchen": {
                "enabled": True,
                "cameras": ["rtsp://cam/kitchen"],
                "inference_interval": 15,
                "rules": {"zone": "waste"},
            }
        }
    }
    r = c.put("/v1/devices/jetson-yuhuan-01/config", json=config)
    assert r.status_code == 200, r.text

    from hotpot_platform.cloud.event_hub import app as hub_app_module
    from hotpot_platform.cloud.event_hub.db import create_hub_database
    from hotpot_platform.cloud.event_hub import runtime

    db2 = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=db2.on_persist),
        db2,
        hub_app_module.AlertGateway(db_path),
    )

    r = c.get("/v1/devices/jetson-yuhuan-01")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["device_id"] == "jetson-yuhuan-01"
    assert body["config"]["modules"]["kitchen"]["cameras"] == ["rtsp://cam/kitchen"]
    assert body["config"]["modules"]["kitchen"]["inference_interval"] == 15
