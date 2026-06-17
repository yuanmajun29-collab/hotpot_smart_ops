import os, tempfile
from pathlib import Path
import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "t.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ.pop("HOTPOT_SEED_DIR", None)
    os.environ.pop("HOTPOT_DATABASE_URL", None)
    from cloud.event_hub import app as m
    from cloud.event_hub import runtime
    _db = m.create_hub_database(db_path)
    runtime.init(m.MultiTenantHub(on_persist=_db.on_persist), _db, m.AlertGateway(db_path))
    return TestClient(m.app)


def test_v1_summary_alias_matches_legacy(client):
    a = client.get("/summary?store_id=store_yuhuan")
    b = client.get("/v1/summary?store_id=store_yuhuan")
    assert a.status_code == b.status_code == 200
    assert a.json() == b.json()


def test_legacy_has_deprecation_header(client):
    r = client.get("/summary?store_id=store_yuhuan")
    assert r.headers.get("Deprecation") == "true"


def test_v1_has_no_deprecation_header(client):
    r = client.get("/v1/summary?store_id=store_yuhuan")
    assert "Deprecation" not in r.headers
