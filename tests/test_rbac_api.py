"""RBAC action enforcement tests (DEV-425/426 / BL-07)."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def strict_client(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    monkeypatch.setenv("HOTPOT_DB", str(db_path))
    monkeypatch.setenv("HOTPOT_AUTH_MODE", "strict")
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


def test_login_rejects_role_mismatch(strict_client):
    r = strict_client.post(
        "/auth/token",
        json={
            "username": "lingban",
            "password": "demo",
            "store_id": "store_yuhuan",
            "role": "总部PMO",
        },
    )
    assert r.status_code == 403
    assert "Role does not match account" in r.json()["detail"]


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


def test_table_correct_allowed_for_lingban(strict_client):
    """F-T06: 前厅领班 has table_correct; manual correction succeeds and persists."""
    token = _token(strict_client, "lingban", "前厅领班")
    r = strict_client.post(
        "/v1/tables?store_id=store_yuhuan",
        json={"tables": [{"table_id": "T09", "state": "need_clean"}]},
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    assert r.json()["ok"] is True

    got = strict_client.get("/v1/tables?store_id=store_yuhuan", headers=_auth(token))
    assert got.status_code == 200
    states = {t["table_id"]: t["state"] for t in got.json()}
    assert states.get("T09") == "need_clean"


def test_store_user_cannot_read_other_store_summary(strict_client):
    token = _token(strict_client, "zhangdian", "店长", store_id="store_yuhuan")
    r = strict_client.get("/v1/summary?store_id=store_jiaojiang", headers=_auth(token))
    assert r.status_code == 403
    assert "store_jiaojiang" in r.json()["detail"]


def test_store_user_store_list_is_scoped(strict_client):
    token = _token(strict_client, "zhangdian", "店长", store_id="store_yuhuan")
    r = strict_client.get("/v1/stores", headers=_auth(token))
    assert r.status_code == 200
    ids = {s["store_id"] for s in r.json()["stores"]}
    assert "store_yuhuan" in ids
    assert "store_jiaojiang" not in ids


def test_store_user_alert_routes_are_scoped(strict_client):
    token = _token(strict_client, "zhangdian", "店长", store_id="store_yuhuan")
    r = strict_client.get("/v1/alerts/routes", headers=_auth(token))
    assert r.status_code == 200
    ids = {route["store_id"] for route in r.json()["routes"]}
    assert "store_yuhuan" in ids
    assert "store_jiaojiang" not in ids


def test_store_user_metrics_are_scoped(strict_client):
    token = _token(strict_client, "zhangdian", "店长", store_id="store_yuhuan")
    r = strict_client.get("/metrics", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["store_count"] == 1


def test_store_user_forbidden_from_rollup_overviews(strict_client):
    token = _token(strict_client, "zhangdian", "店长", store_id="store_yuhuan")
    headers = _auth(token)

    for path in ("/v1/region/overview", "/v1/national/overview", "/v1/benchmark"):
        r = strict_client.get(path, headers=headers)
        assert r.status_code == 403
        assert "Rollup overview" in r.json()["detail"]
