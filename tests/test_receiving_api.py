"""Tests for receiving submit and audit API (DEV-420 / BL-05)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ.pop("HOTPOT_SEED_DIR", None)
    os.environ.pop("HOTPOT_DATABASE_URL", None)

    from cloud.event_hub import app as hub_app_module
    from cloud.event_hub.db import create_hub_database

    from cloud.event_hub import runtime
    _db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=_db.on_persist),
        _db,
        hub_app_module.AlertGateway(db_path),
    )

    with TestClient(hub_app_module.app) as c:
        yield c


def _submit_payload(**overrides):
    body = {
        "store_id": "store_yuhuan",
        "po_id": "PO-20260612-001",
        "sku": "毛肚",
        "weight_kg": 19.2,
        "po_weight_kg": 20.0,
        "vlm_grade": "A",
        "temp_c": -18.5,
        "signatures": [
            {"role": "receiver", "signed_by": "zhangdian"},
            {"role": "chef", "signed_by": "chushi"},
        ],
    }
    body.update(overrides)
    return body


def test_receiving_submit_success(client):
    r = client.post("/v1/receiving/submit", json=_submit_payload())
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["batch_id"].startswith("RCV-")
    assert data["variance_pct"] == -4.0
    assert data["event_id"]


def test_receiving_submit_requires_dual_signatures(client):
    r = client.post(
        "/v1/receiving/submit",
        json=_submit_payload(signatures=[{"role": "receiver", "signed_by": "zhangdian"}]),
    )
    assert r.status_code == 400
    assert "chef" in r.json()["detail"]


def test_receiving_batches_and_audit_signatures(client):
    payload = _submit_payload(batch_id="RCV-TEST-001")
    client.post("/v1/receiving/submit", json=payload)

    batches = client.get("/v1/receiving/batches?store_id=store_yuhuan").json()
    assert batches["count"] >= 1
    assert any(b["batch_id"] == "RCV-TEST-001" for b in batches["batches"])

    audit = client.get("/v1/audit/signatures?store_id=store_yuhuan").json()
    assert audit["count"] >= 2
    roles = {s["role"] for s in audit["signatures"] if s["batch_id"] == "RCV-TEST-001"}
    assert roles == {"receiver", "chef"}


def test_receiving_duplicate_batch_rejected(client):
    payload = _submit_payload(batch_id="RCV-DUP-001")
    assert client.post("/v1/receiving/submit", json=payload).status_code == 200
    r = client.post("/v1/receiving/submit", json=payload)
    assert r.status_code == 400
    assert "已存在" in r.json()["detail"]


def test_audit_acks_includes_receiving(client):
    client.post("/v1/receiving/submit", json=_submit_payload(batch_id="RCV-AUDIT-001"))
    client.post(
        "/alerts/ack",
        json={"event_id": "evt-test-1", "store_id": "store_yuhuan", "ack_by": "zhangdian"},
    )
    data = client.get("/v1/audit/acks?store_id=store_yuhuan").json()
    assert data["alert_ack_count"] >= 1
    assert data["receiving_signature_count"] >= 2


def test_receiving_updates_cost_snapshot(client):
    client.post("/v1/receiving/submit", json=_submit_payload(batch_id="RCV-COST-001"))
    cost = client.get("/cost?store_id=store_yuhuan").json()
    items = cost.get("items", [])
    assert any(i.get("batch_id") == "RCV-COST-001" for i in items)
