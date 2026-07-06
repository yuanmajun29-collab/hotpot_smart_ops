"""Cockpit + 集团决策者 role tests (F-EXEC01)."""

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

    from hotpot_platform.cloud.event_hub import app as hub_app_module
    from hotpot_platform.cloud.event_hub.db import create_hub_database

    from hotpot_platform.cloud.event_hub import runtime
    _db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=_db.on_persist),
        _db,
        hub_app_module.AlertGateway(db_path),
    )

    with TestClient(hub_app_module.app) as c:
        yield c


def _token(client: TestClient, username: str, role: str) -> str:
    r = client.post(
        "/auth/token",
        json={"username": username, "password": "demo", "role": role},
    )
    assert r.status_code == 200
    return r.json()["access_token"]


def test_laoban_login_and_national_overview(client):
    tok = _token(client, "laoban", "集团决策者")
    headers = {"Authorization": f"Bearer {tok}"}
    me = client.get("/v1/auth/me", headers=headers).json()
    assert me["role"] == "集团决策者"
    assert me["data_scope"] == "national"
    assert me["can_admin"] is False

    r = client.get("/v1/national/overview", headers=headers)
    assert r.status_code == 200
    assert r.json()["level"] == "national"


def test_laoban_cannot_access_admin(client):
    tok = _token(client, "laoban", "集团决策者")
    headers = {"Authorization": f"Bearer {tok}"}
    assert client.get("/v1/admin/stores", headers=headers).status_code == 403
