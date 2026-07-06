"""Admin console + pipeline stub API tests (DEV-502)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_REGISTRY = PROJECT_ROOT / "demo" / "data" / "stores.json"


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    registry_path = Path(tmp) / "stores.json"
    shutil.copy(SRC_REGISTRY, registry_path)

    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_STORES_REGISTRY"] = str(registry_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ.pop("HOTPOT_SEED_DIR", None)
    os.environ.pop("HOTPOT_DATABASE_URL", None)

    from platform.cloud.event_hub import app as hub_app_module
    from platform.cloud.event_hub.db import create_hub_database
    from platform.cloud.event_hub.org_registry import OrgRegistry

    reg = OrgRegistry(registry_path)
    from platform.cloud.event_hub import runtime
    _db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=_db.on_persist),
        _db,
        hub_app_module.AlertGateway(db_path),
    )
    runtime.org_registry = reg
    reg.apply_to_hub(runtime.hub)

    with TestClient(hub_app_module.app) as c:
        yield c, registry_path


def _pmo_token(client: TestClient) -> str:
    r = client.post(
        "/auth/token",
        json={"username": "zongbu", "password": "demo", "role": "总部PMO"},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


def test_auth_me(client):
    c, _ = client
    headers = {"Authorization": f"Bearer {_pmo_token(c)}"}
    r = c.get("/v1/auth/me", headers=headers)
    assert r.status_code == 200
    assert r.json()["can_admin"] is True
    assert r.json()["data_scope"] == "national"


def test_admin_stores_and_org_tree(client):
    c, _ = client
    headers = {"Authorization": f"Bearer {_pmo_token(c)}"}
    r = c.get("/v1/admin/org-tree", headers=headers)
    assert r.status_code == 200
    assert "parent_regions" in r.json()

    r = c.get("/v1/admin/stores", headers=headers)
    assert r.status_code == 200
    stores = r.json()["stores"]
    assert len(stores) >= 2


def test_pipeline_tick_inprocess(client):
    c, _ = client
    headers = {"Authorization": f"Bearer {_pmo_token(c)}"}
    r = c.post("/v1/admin/pipeline/tick", headers=headers, json={"mode": "inprocess"})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert len(data["results"]) >= 2

    r = c.get("/v1/admin/pipeline/status", headers=headers)
    status = r.json()
    assert status["summary"]["avg_pipeline_pct"] > 0
    for row in status["stores"]:
        if row["store_id"] in ("store_yuhuan", "store_jiaojiang"):
            assert row["layers"]["pos"] is True
            assert row["layers"]["vision"] is True


def test_national_overview_after_tick(client):
    c, _ = client
    headers = {"Authorization": f"Bearer {_pmo_token(c)}"}
    c.post("/v1/admin/pipeline/tick", headers=headers, json={})
    r = c.get("/v1/national/overview", headers=headers)
    assert r.status_code == 200
    data = r.json()
    assert data["level"] == "national"
    assert data["rollup"]["store_count"] >= 2


def test_admin_create_store(client):
    c, registry_path = client
    headers = {"Authorization": f"Bearer {_pmo_token(c)}"}
    before = len(c.get("/v1/admin/stores", headers=headers).json()["stores"])
    r = c.post(
        "/v1/admin/stores",
        headers=headers,
        json={
            "store_name": "冯校长火锅·测试店",
            "region_id": "region_taizhou",
            "city": "测试市",
            "status": "preparing",
        },
    )
    assert r.status_code == 200
    store = r.json()["store"]
    assert store["store_id"].startswith("store_")
    after = len(c.get("/v1/admin/stores", headers=headers).json()["stores"])
    assert after == before + 1

    saved = json.loads(registry_path.read_text(encoding="utf-8"))
    ids = [s["store_id"] for s in saved["pilot_stores"]]
    assert store["store_id"] in ids

    summary = c.get(f"/summary?store_id={store['store_id']}", headers=headers)
    assert summary.status_code == 200
    assert summary.json().get("total_events", 0) > 0


def test_admin_forbidden_for_store_manager(client):
    c, _ = client
    r = c.post("/auth/token", json={"username": "zhangdian", "password": "demo", "role": "店长"})
    token = r.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    r = c.get("/v1/admin/stores", headers=headers)
    assert r.status_code == 403


def test_admin_users_list(client):
    """F-HQ09: admin can list users with role + data_scope (demo stub)."""
    c, _ = client
    headers = {"Authorization": f"Bearer {_pmo_token(c)}"}
    r = c.get("/v1/admin/users", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(body["users"])
    assert body["count"] >= 7
    by_role = {u["username"]: u for u in body["users"]}
    assert by_role["laoban"]["role"] == "集团决策者"
    assert by_role["laoban"]["data_scope"] == "national"
    assert by_role["zhangdian"]["data_scope"] == "store"


def test_admin_users_forbidden_for_store_manager(client):
    """F-HQ09 RBAC: a store manager cannot list users."""
    c, _ = client
    token = c.post(
        "/auth/token", json={"username": "zhangdian", "password": "demo", "role": "店长"}
    ).json()["access_token"]
    r = c.get("/v1/admin/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403


def test_admin_audit_logs_record_store_creation(client):
    """F-HQ11: creating a store produces a retrievable audit log entry."""
    c, _ = client
    headers = {"Authorization": f"Bearer {_pmo_token(c)}"}
    before = c.get("/v1/admin/audit-logs", headers=headers).json()["count"]

    c.post(
        "/v1/admin/stores",
        headers=headers,
        json={"store_name": "冯校长火锅·审计店", "region_id": "region_taizhou", "status": "preparing"},
    )

    r = c.get("/v1/admin/audit-logs", headers=headers)
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == len(body["logs"])
    assert body["count"] > before
