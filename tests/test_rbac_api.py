"""RBAC action enforcement tests (DEV-425/426 / BL-07)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def strict_client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "strict"
    os.environ.pop("HOTPOT_SEED_DIR", None)
    os.environ.pop("HOTPOT_DATABASE_URL", None)

    from cloud.event_hub import app as hub_app_module
    from cloud.event_hub.db import create_hub_database

    hub_app_module.db = create_hub_database(db_path)
    hub_app_module.hub = hub_app_module.MultiTenantHub(on_persist=hub_app_module.db.on_persist)
    hub_app_module.alert_gateway = hub_app_module.AlertGateway(db_path)

    with TestClient(hub_app_module.app) as c:
        yield c


def _token(client: TestClient, username: str, role: str, store_id: str = "store_yuhuan") -> str:
    r = client.post(
        "/auth/token",
        json={"username": username, "password": "demo", "role": role, "store_id": store_id},
    )
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_login_without_role_uses_demo_user_role(strict_client):
    r = strict_client.post(
        "/auth/token",
        json={"username": "lingban", "password": "demo", "store_id": "store_yuhuan"},
    )
    assert r.status_code == 200
    assert r.json()["user"]["role"] == "前厅领班"


def _receiving_body(**overrides):
    body = {
        "store_id": "store_yuhuan",
        "po_id": "PO-RBAC-001",
        "sku": "毛肚",
        "weight_kg": 19.2,
        "po_weight_kg": 20.0,
        "vlm_grade": "A",
        "temp_c": -18.5,
        "signatures": [
            {"role": "receiver", "signed_by": "shouhuo"},
            {"role": "chef", "signed_by": "chushi"},
        ],
    }
    body.update(overrides)
    return body


def test_receiving_submit_allowed_for_receiver(strict_client):
    token = _token(strict_client, "shouhuo", "收货员")
    r = strict_client.post(
        "/v1/receiving/submit",
        json=_receiving_body(batch_id="RCV-RBAC-RECV"),
        headers=_auth(token),
    )
    assert r.status_code == 200


def test_receiving_submit_forbidden_for_lingban(strict_client):
    token = _token(strict_client, "lingban", "前厅领班")
    r = strict_client.post(
        "/v1/receiving/submit",
        json=_receiving_body(batch_id="RCV-RBAC-DENY"),
        headers=_auth(token),
    )
    assert r.status_code == 403
    assert "receiving_submit" in r.json()["detail"]


def test_ack_allowed_for_lingban_forbidden_for_receiver(strict_client):
    lingban = _token(strict_client, "lingban", "前厅领班")
    r_ok = strict_client.post(
        "/alerts/ack",
        json={"event_id": "evt-rbac-1", "store_id": "store_yuhuan", "ack_by": "lingban"},
        headers=_auth(lingban),
    )
    assert r_ok.status_code == 200

    shouhuo = _token(strict_client, "shouhuo", "收货员")
    r_deny = strict_client.post(
        "/alerts/ack",
        json={"event_id": "evt-rbac-2", "store_id": "store_yuhuan", "ack_by": "shouhuo"},
        headers=_auth(shouhuo),
    )
    assert r_deny.status_code == 403
    assert "ack" in r_deny.json()["detail"]


def test_sop_assign_forbidden_for_lingban(strict_client):
    token = _token(strict_client, "lingban", "前厅领班")
    r = strict_client.post(
        "/v1/sop/assign",
        json={
            "store_id": "store_yuhuan",
            "sop_id": "SOP-RBAC",
            "sop_name": "测试指派",
            "assignee": "厨师长",
        },
        headers=_auth(token),
    )
    assert r.status_code == 403
    assert "sop_assign" in r.json()["detail"]


def test_table_correct_forbidden_for_receiver(strict_client):
    token = _token(strict_client, "shouhuo", "收货员")
    r = strict_client.post(
        "/tables?store_id=store_yuhuan",
        json={"tables": [{"table_id": "T01", "state": "empty"}]},
        headers=_auth(token),
    )
    assert r.status_code == 403
    assert "table_correct" in r.json()["detail"]


def test_report_generate_forbidden_for_decision_maker(strict_client):
    token = _token(strict_client, "laoban", "集团决策者")
    r = strict_client.post(
        "/v1/reports/daily/generate",
        json={"store_id": "store_yuhuan", "push": False},
        headers=_auth(token),
    )
    assert r.status_code == 403
    assert "report_generate" in r.json()["detail"]
