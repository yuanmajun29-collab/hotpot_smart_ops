"""Tests for IoT door rule and readings API (BL-02 stub)."""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from edge.iot_mock.iot_rules import DoorTimeoutTracker, parse_door_open


def test_parse_door_open():
    assert parse_door_open(1) is True
    assert parse_door_open(0) is False
    assert parse_door_open("open") is True


def test_door_timeout_tracker_fires_after_threshold():
    tracker = DoorTimeoutTracker(timeout_sec=0.2)
    assert tracker.on_reading("door_1", 1, store_id="store_yuhuan") is None
    time.sleep(0.25)
    ev = tracker.on_reading("door_1", 1, store_id="store_yuhuan")
    assert ev is not None
    assert ev["event_type"] == "iot_door_open_timeout"
    assert ev["level"] == "warn"


def test_door_closes_clears_tracker():
    tracker = DoorTimeoutTracker(timeout_sec=0.1)
    tracker.on_reading("door_1", 1, store_id="store_yuhuan")
    time.sleep(0.15)
    assert tracker.on_reading("door_1", 0, store_id="store_yuhuan") is None
    time.sleep(0.15)
    assert tracker.on_reading("door_1", 1, store_id="store_yuhuan") is None


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ.pop("HOTPOT_SEED_DIR", None)
    os.environ.pop("HOTPOT_DATABASE_URL", None)

    from platform.cloud.event_hub import app as hub_app_module
    from platform.cloud.event_hub.db import create_hub_database

    from platform.cloud.event_hub import runtime
    _db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=_db.on_persist),
        _db,
        hub_app_module.AlertGateway(db_path),
    )

    with TestClient(hub_app_module.app) as c:
        yield c


def test_iot_readings_batch_and_query(client):
    body = {
        "store_id": "store_yuhuan",
        "readings": [
            {
                "sensor_id": "cold_storage_1",
                "sensor_type": "temperature",
                "value": -18.5,
                "unit": "C",
            },
            {
                "sensor_id": "door_cold_1",
                "sensor_type": "door",
                "value": 0,
                "unit": "bool",
            },
        ],
    }
    r = client.post("/v1/iot/readings/batch", json=body)
    assert r.status_code == 200
    assert r.json()["inserted"] == 2

    listed = client.get(
        "/v1/iot/readings?store_id=store_yuhuan&sensor_id=cold_storage_1&hours=24"
    ).json()
    assert listed["count"] >= 1
    assert listed["readings"][0]["sensor_id"] == "cold_storage_1"
