"""Phase 1 invariant: cross-store isolation is enforced for authenticated users,
even in demo mode — not deferred to strict/P2 (Codex PK item).

Only the anonymous demo-convenience principal (store_id='*') is exempt; any
account-scoped JWT user is blocked from another store's data (read and write).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

YUHUAN = "store_yuhuan"
JIAOJIANG = "store_jiaojiang"


@pytest.fixture()
def client(monkeypatch):
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    monkeypatch.setenv("HOTPOT_DB", str(db_path))
    monkeypatch.setenv("HOTPOT_AUTH_MODE", "demo")  # default mode — isolation must still hold
    monkeypatch.delenv("HOTPOT_SEED_DIR", raising=False)
    monkeypatch.delenv("HOTPOT_DATABASE_URL", raising=False)

    from platform.cloud.event_hub import app as hub_app_module
    from platform.cloud.event_hub import runtime
    from platform.cloud.event_hub.db import create_hub_database

    db = create_hub_database(db_path)
    runtime.init(
        hub_app_module.MultiTenantHub(on_persist=db.on_persist),
        db,
        hub_app_module.AlertGateway(db_path),
    )
    with TestClient(hub_app_module.app) as c:
        yield c


def _token(client: TestClient, username: str, store_id: str) -> dict:
    r = client.post(
        "/auth/token",
        json={"username": username, "password": "demo", "store_id": store_id},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_store_scoped_user_reads_own_store(client):
    h = _token(client, "zhangdian", YUHUAN)
    assert client.get(f"/v1/summary?store_id={YUHUAN}", headers=h).status_code == 200


def test_store_scoped_user_cannot_read_other_store(client):
    """Authenticated 店长(玉环) is forbidden from reading 椒江 — in demo mode."""
    h = _token(client, "zhangdian", YUHUAN)
    r = client.get(f"/v1/summary?store_id={JIAOJIANG}", headers=h)
    assert r.status_code == 403
    assert JIAOJIANG in r.json()["detail"]


def test_store_scoped_user_cannot_write_other_store(client):
    """Authenticated 前厅领班(玉环) cannot correct tables in 椒江."""
    h = _token(client, "lingban", YUHUAN)
    r = client.post(
        f"/v1/tables?store_id={JIAOJIANG}",
        json={"tables": [{"table_id": "T1", "state": "empty"}]},
        headers=h,
    )
    assert r.status_code == 403
    assert JIAOJIANG in r.json()["detail"]


def test_region_scope_user_may_read_across_stores(client):
    """区域督导 (data_scope=region, store_id='*') may read any store in scope."""
    h = _token(client, "quyududao", "*")
    assert client.get(f"/v1/summary?store_id={YUHUAN}", headers=h).status_code == 200
    assert client.get(f"/v1/summary?store_id={JIAOJIANG}", headers=h).status_code == 200
