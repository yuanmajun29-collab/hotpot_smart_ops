"""Tests for daily report API (DEV-423 / BL-06)."""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client():
    tmp = tempfile.mkdtemp()
    db_path = Path(tmp) / "test_hub.db"
    os.environ["HOTPOT_DB"] = str(db_path)
    os.environ["HOTPOT_AUTH_MODE"] = "demo"
    os.environ["HOTPOT_DAILY_REPORT_SCHEDULER"] = "0"
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


def test_daily_report_generate_and_list(client):
    client.post(
        "/events?store_id=store_yuhuan",
        json={
            "event_type": "table_empty",
            "source": "vision",
            "level": "info",
            "store_id": "store_yuhuan",
            "message": "seed for report",
        },
    )
    r = client.post(
        "/v1/reports/daily/generate",
        json={"store_id": "store_yuhuan", "push": False, "report_date": "2026-06-15"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert "运营日报" in data["markdown"]
    assert data["cached"] is False

    r2 = client.post(
        "/v1/reports/daily/generate",
        json={"store_id": "store_yuhuan", "report_date": "2026-06-15"},
    )
    assert r2.json()["cached"] is True

    listed = client.get("/v1/reports/daily?store_id=store_yuhuan").json()
    assert listed["count"] >= 1


def test_daily_report_forbidden_for_lingban(client):
    token = client.post(
        "/auth/token",
        json={"username": "lingban", "password": "demo", "store_id": "store_yuhuan", "role": "前厅领班"},
    ).json()["access_token"]
    r = client.post(
        "/v1/reports/daily/generate",
        json={"store_id": "store_yuhuan"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert r.status_code == 403


def test_daily_report_push_webhook_e2e(client):
    import json
    import threading
    import time
    from http.server import BaseHTTPRequestHandler, HTTPServer
    from pathlib import Path

    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            received.append(json.loads(self.rfile.read(length).decode()))
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"errcode":0,"errmsg":"ok"}')

        def log_message(self, *args) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    webhook_url = f"http://127.0.0.1:{server.server_address[1]}/hook"
    os.environ["HOTPOT_WECHAT_WEBHOOK_STORE_YUHUAN"] = webhook_url

    from cloud.event_hub import app as hub_app_module
    from cloud.event_hub import runtime

    runtime.alert_gateway = hub_app_module.AlertGateway(Path(os.environ["HOTPOT_DB"]))

    client.post(
        "/events?store_id=store_yuhuan",
        json={
            "event_type": "kitchen_smoke",
            "source": "vision",
            "level": "critical",
            "store_id": "store_yuhuan",
            "message": "for report metrics",
        },
    )
    r = client.post(
        "/v1/reports/daily/generate",
        json={"store_id": "store_yuhuan", "push": True, "report_date": "2026-06-16"},
    )
    assert r.status_code == 200
    data = r.json()
    assert data["pushed"] is True

    deadline = time.time() + 3
    while time.time() < deadline and len(received) < 2:
        time.sleep(0.05)
    daily_msgs = [
        m for m in received
        if "report.html" in m.get("markdown", {}).get("content", "")
    ]
    assert daily_msgs, f"expected daily report webhook, got {len(received)} payload(s)"
    md = daily_msgs[-1]["markdown"]["content"]
    assert "运营日报" in md or "运营摘要" in md
    assert "date=2026-06-16" in md

    pushes = client.get("/alerts/push-log?store_id=store_yuhuan").json()
    assert any("daily-report" in (p.get("event_id") or "") for p in pushes.get("pushes", []))

    server.shutdown()
