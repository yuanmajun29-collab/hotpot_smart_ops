"""WeChat Work webhook E2E tests (DEV-415 / BL-03)."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any, Dict, List

import pytest
from fastapi.testclient import TestClient


class _WebhookCollector:
    def __init__(self) -> None:
        self.received: List[Dict[str, Any]] = []
        self.received_at: List[float] = []


def _start_mock_webhook() -> tuple[HTTPServer, _WebhookCollector, str]:
    collector = _WebhookCollector()

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length)
            collector.received.append(json.loads(body.decode()))
            collector.received_at.append(time.time())
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"errcode":0,"errmsg":"ok"}')

        def log_message(self, format: str, *args: Any) -> None:
            return

    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    return server, collector, f"http://127.0.0.1:{port}/webhook"


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


def test_critical_event_triggers_webhook_e2e(client):
    server, collector, webhook_url = _start_mock_webhook()
    os.environ["HOTPOT_WECHAT_WEBHOOK_STORE_YUHUAN"] = webhook_url
    client.app.state  # ensure app loaded
    from cloud.event_hub import app as hub_app_module
    from cloud.event_hub import runtime

    runtime.alert_gateway = hub_app_module.AlertGateway(
        Path(os.environ["HOTPOT_DB"])
    )

    t0 = time.time()
    r = client.post(
        "/events?store_id=store_yuhuan",
        json={
            "event_type": "kitchen_smoke",
            "source": "vision",
            "level": "critical",
            "store_id": "store_yuhuan",
            "message": "E2E 烟雾告警探针",
            "zone": "kitchen",
        },
    )
    assert r.status_code == 200
    data = r.json()
    assert data.get("_alert_push", {}).get("webhook_sent") is True

    deadline = t0 + 5.0
    while time.time() < deadline and not collector.received:
        time.sleep(0.05)
    assert collector.received, "mock webhook did not receive POST"
    payload = collector.received[0]
    assert payload["msgtype"] == "markdown"
    assert "烟雾" in payload["markdown"]["content"] or "kitchen_smoke" in payload["markdown"]["content"]
    assert "玉环" in payload["markdown"]["content"] or "store_yuhuan" in payload["markdown"]["content"]

    elapsed_ms = (collector.received_at[0] - t0) * 1000
    assert elapsed_ms < 30_000, f"SLA breach: {elapsed_ms:.0f}ms"

    pushes = client.get("/alerts/push-log?store_id=store_yuhuan").json()
    assert len(pushes.get("pushes", [])) >= 1

    server.shutdown()


def test_warn_not_pushed_without_flag(client):
    server, collector, webhook_url = _start_mock_webhook()
    os.environ["HOTPOT_WECHAT_WEBHOOK"] = webhook_url
    os.environ["HOTPOT_PUSH_WARN"] = "0"
    from cloud.event_hub import app as hub_app_module
    from cloud.event_hub import runtime

    runtime.alert_gateway = hub_app_module.AlertGateway(
        Path(os.environ["HOTPOT_DB"])
    )

    r = client.post(
        "/events?store_id=store_yuhuan",
        json={
            "event_type": "table_need_clean",
            "source": "vision",
            "level": "warn",
            "store_id": "store_yuhuan",
            "message": "warn should not push",
        },
    )
    assert r.status_code == 200
    assert "_alert_push" not in r.json()
    time.sleep(0.2)
    assert not collector.received
    server.shutdown()


def test_alerts_routes_and_test_push(client):
    server, collector, webhook_url = _start_mock_webhook()
    os.environ["HOTPOT_WECHAT_WEBHOOK_STORE_JIAOJIANG"] = webhook_url
    from cloud.event_hub import app as hub_app_module
    from cloud.event_hub import runtime

    runtime.alert_gateway = hub_app_module.AlertGateway(
        Path(os.environ["HOTPOT_DB"])
    )

    routes = client.get("/alerts/routes?store_id=store_jiaojiang").json()
    assert routes["routes"][0]["webhook_configured"] is True
    assert routes["routes"][0]["webhook_source"] == "env_store"

    r = client.post("/alerts/test-push?store_id=store_jiaojiang")
    assert r.status_code == 200
    assert r.json()["webhook_sent"] is True
    assert collector.received
    server.shutdown()
